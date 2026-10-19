"""Undo: what one action just did, put back as it was.

A delete, a bulk action or a bulk edit answers with an *Undo* button for
a few minutes. Nothing new is stored to make it work: the history holds
every record as it was before (:mod:`generic.history.recording`), and
every version carries the unit of work - the batch - it was written in.
Undoing is putting back, for each record that unit of work touched, the
version it had before:

==========================  ==========================================
The action had               Undo
==========================  ==========================================
changed the record           writes back the version before it
deleted it                   creates it again, same key, from that version
created it                   deletes it
==========================  ==========================================

What makes it safe rather than a guess:

* **Offered only when it can be done whole.** A deletion is undone only
  where everything it took with it was recorded: a cascade reaching a
  model without a history (or a link of another model's many-to-many),
  or a resource keeping fields out of its versions (``history_exclude``),
  means no *Undo*. So does a change with no version before it.
* **Refused when somebody changed a record since.** Each record's newest
  version must still be the action's; otherwise nothing is undone and
  the answer names the record.
* **The reader's own, for a while.** The offer is a signed token naming
  the batches, the resource and the person; it expires after
  ``GENERIC["UNDO_SECONDS"]``. The permissions are checked again: the
  change permission to put a record back, the add permission to create
  it again, the delete permission to delete what was created.
* **All or nothing.** One transaction; the undo is itself recorded
  (source *Undo*), so the History tab tells the whole story.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any, Iterable

from django.core import signing
from django.db import IntegrityError, models, router, transaction
from django.db.models import ProtectedError, RestrictedError
from django.utils.encoding import force_str
from django.utils.translation import gettext, ngettext

from generic.conf import generic_settings
from generic.history.capture import Captured, capture
from generic.history.models import HistoryEntry
from generic.history.recording import is_recorded, tracked_fields

#: The signature's salt: a token of another feature never opens this.
SALT = "generic.history.undo"

#: The body field the token travels in.
TOKEN = "token"

#: On delete rules that leave the rows pointing at a record alone.
UNTOUCHED = (models.DO_NOTHING, models.PROTECT, models.RESTRICT)


class Refused(Exception):
    """An undo that cannot be done; nothing was changed."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class Step:
    """What one record needs to be as it was."""

    kind: str  # "restore", "recreate" or "delete"
    resource: Any
    object_id: str
    label: str
    last: int  # the pk of the action's newest version of it
    values: dict = field(default_factory=dict)


# -- what the action wrote ----------------------------------------------


def is_offered(resource: Any) -> bool:
    """Whether actions of ``resource`` answer with an *Undo*."""
    return bool(
        generic_settings.UNDO_SECONDS
        and getattr(resource, "undo", True)
        and is_recorded(resource)
    )


def deletion_is_recorded(site: Any, model: Any, seen: set | None = None):
    """Whether deleting a record of ``model`` leaves nothing behind that
    its history cannot bring back.

    Everything the delete cascades to, or empties a link of, has to be
    a recorded model of ``site`` - the deletion then writes a version
    of it in the same batch. A link of another model's many-to-many
    vanishes without a version, and so does whatever an unrecorded
    model held.
    """
    seen = set() if seen is None else seen

    if model in seen:
        return True

    seen.add(model)
    meta = model._meta

    for relation in meta.related_objects:
        related = relation.related_model

        if relation.many_to_many:
            # Declared on another model, or one way on this one: the
            # links other records held to this one go with it, and
            # their versions never say so. A symmetrical link of the
            # model's own is in this record's version too.
            own = relation.field.model is model
            if not (own and getattr(relation, "symmetrical", False)):
                return False

            continue

        on_delete = getattr(relation, "on_delete", None)

        if on_delete in UNTOUCHED:
            continue

        through_owner = related._meta.auto_created

        if through_owner:
            # A many-to-many of this model's own: its versions hold the
            # list, which a new creation sets back.
            if through_owner is model or issubclass(model, through_owner):
                continue

            return False

        resource = site.get_resource(related)

        if resource is None or not is_recorded(resource):
            return False

        if getattr(resource, "history_exclude", ()):
            return False

        if on_delete is models.CASCADE and not deletion_is_recorded(
            site, related, seen
        ):
            return False

    for private in meta.private_fields:
        related = getattr(private, "related_model", None)

        # A GenericRelation deletes the rows pointing at the record.
        if related is not None and getattr(private, "is_relation", False):
            resource = site.get_resource(related)

            if resource is None or not is_recorded(resource):
                return False

    return True


def plan(site: Any, batches: Iterable[str]) -> list[Step] | None:
    """What putting back everything ``batches`` wrote takes, newest
    first; ``None`` when some of it cannot be put back."""
    from django.contrib.contenttypes.models import ContentType

    batches = sorted(set(batches))

    if not batches:
        return None

    limit = int(generic_settings.UNDO_MAX_RECORDS or 0)
    entries = list(
        HistoryEntry.objects.filter(batch__in=batches).order_by("pk")[
            : (limit * len(batches)) + 1 if limit else None
        ]
    )

    if not entries:
        return None

    records: dict[tuple, list[HistoryEntry]] = {}

    for entry in entries:
        records.setdefault(
            (entry.content_type_id, entry.object_id), []
        ).append(entry)

    if limit and len(records) > limit:
        return None

    steps = []

    for (content_type_id, object_id), written in records.items():
        content_type = ContentType.objects.get_for_id(content_type_id)
        model = content_type.model_class()
        resource = site.get_resource(model) if model is not None else None

        if resource is None:
            return None

        first, last = written[0], written[-1]
        before = (
            HistoryEntry.objects.filter(
                content_type_id=content_type_id,
                object_id=object_id,
                version__lt=first.version,
            )
            .order_by("-version", "-pk")
            .first()
        )
        common = {
            "resource": resource,
            "object_id": object_id,
            "label": last.label or object_id,
            "last": last.pk,
        }

        if first.action == HistoryEntry.Action.CREATED:
            if last.action != HistoryEntry.Action.DELETED:
                steps.append(Step("delete", **common))

            continue

        if last.action == HistoryEntry.Action.DELETED:
            if before is not None:
                values = before.values
            elif first.action == HistoryEntry.Action.DELETED:
                # Older than its history: what it was when it went is
                # all there is, and all this unit of work changed.
                values = first.values
            else:
                return None

            if getattr(resource, "history_exclude", ()) or not (
                deletion_is_recorded(site, model)
            ):
                return None

            steps.append(Step("recreate", values=values or {}, **common))
            continue

        if before is None:
            return None

        steps.append(Step("restore", values=before.values or {}, **common))

    # The newest first: a cascade deleted the children before their
    # parent, so the parent comes back first.
    steps.sort(key=lambda step: step.last, reverse=True)

    return steps or None


# -- the offer ----------------------------------------------------------


def offer(resource: Any, request: Any, captured: Captured) -> dict | None:
    """The *Undo* an answer carries, or ``None``.

    ``captured`` holds the batches the action wrote in
    (:func:`generic.history.capture.capture`).
    """
    person = getattr(getattr(request, "user", None), "pk", None)

    if not (is_offered(resource) and person):
        return None

    steps = plan(resource.site, captured.batches)

    if not steps:
        return None

    token = signing.dumps(
        {
            "r": resource.label_lower,
            "u": force_str(person),
            "b": sorted(captured.batches),
        },
        salt=SALT,
        compress=True,
    )

    return {
        "token": token,
        "url": resource.get_undo_api_url(),
        "label": gettext("Undo"),
        "count": len(steps),
        "seconds": int(generic_settings.UNDO_SECONDS),
    }


#: How a message carries an offer to the next page: one tag word.
MESSAGE_TAG = "generic-undo="


def message_tags(offered: dict | None) -> str:
    """An offer as a message's extra tag, for a page that redirects
    (the delete page) - or nothing."""
    if not offered:
        return ""

    return f"{MESSAGE_TAG}{offered['url']}|{offered['token']}"


def from_message_tags(tags: str) -> dict | None:
    """The ``{url, token, label}`` a message's tags carry, if any."""
    for word in (tags or "").split():
        if not word.startswith(MESSAGE_TAG):
            continue

        url, _bar, token = word[len(MESSAGE_TAG) :].partition("|")

        if url.startswith("/") and not url.startswith("//") and token:
            return {"url": url, "token": token, "label": gettext("Undo")}

    return None


def read(resource: Any, request: Any, token: Any) -> list[str]:
    """The batches a token names, once it is shown to be this reader's,
    for this resource, and recent enough."""
    expired = Refused(
        gettext("This can no longer be undone."),
        status=400,
    )

    if not isinstance(token, str) or not token:
        raise expired

    try:
        payload = signing.loads(
            token,
            salt=SALT,
            max_age=int(generic_settings.UNDO_SECONDS or 0),
        )
    except signing.BadSignature:
        raise expired from None

    user = getattr(request, "user", None)

    if (
        not isinstance(payload, dict)
        or payload.get("r") != resource.label_lower
        or payload.get("u") != force_str(getattr(user, "pk", ""))
        or not isinstance(payload.get("b"), list)
    ):
        raise expired

    return [str(batch) for batch in payload["b"]]


# -- the undo -----------------------------------------------------------


def undo(resource: Any, request: Any, token: Any) -> dict:
    """Put back what the token's action did. Answers the message; raises
    :class:`Refused` - with nothing changed - when it cannot."""
    from generic.history.actor import acting_as
    from generic.sites.realtime import batch

    if not is_offered(resource):
        raise Refused(gettext("This can no longer be undone."), status=400)

    batches = read(resource, request, token)
    steps = plan(resource.site, batches)

    if not steps:
        raise Refused(gettext("This can no longer be undone."), status=400)

    planned = sum(1 for step in steps if step.kind == "delete")
    deleted = 0

    try:
        with ExitStack() as stack:
            stack.enter_context(
                transaction.atomic(using=router.db_for_write(resource.model))
            )
            stack.enter_context(
                acting_as(request.user, source=gettext("Undo"))
            )

            involved = {
                step.resource.label_lower: step.resource for step in steps
            }

            for each in involved.values():
                stack.enter_context(batch(each))

            for step in steps:
                still_last(step)

            for step in steps:
                if step.kind == "restore":
                    restore(step, request)
                elif step.kind == "recreate":
                    recreate(step, request)
                else:
                    deleted += delete(step, request)

            if deleted > planned:
                raise Refused(
                    gettext(
                        "Nothing was undone: deleting what was created "
                        "would take other records with it."
                    )
                )
    except (IntegrityError, ProtectedError, RestrictedError) as error:
        raise Refused(
            gettext("Nothing was undone: %(reason)s")
            % {"reason": force_str(error)}
        ) from None

    count = len(steps)

    return {
        "message": ngettext(
            "Undone: %(count)s record is back as it was.",
            "Undone: %(count)s records are back as they were.",
            count,
        )
        % {"count": count},
        "level": "success",
        "count": count,
    }


def still_last(step: Step) -> None:
    """Refuse when somebody wrote a version of the record since."""
    from django.contrib.contenttypes.models import ContentType

    newest = (
        HistoryEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(
                step.resource.model
            ),
            object_id=step.object_id,
        )
        .order_by("-version", "-pk")
        .values_list("pk", flat=True)
        .first()
    )

    if newest != step.last:
        raise Refused(
            gettext("Nothing was undone: “%(name)s” has changed " "since.")
            % {"name": step.label}
        )


def denied() -> Refused:
    return Refused(
        gettext("Nothing was undone: you may no longer make this change."),
        status=403,
    )


def current(step: Step) -> Any:
    """The record as it is now, trash or not; ``None`` when gone."""
    model = step.resource.model

    return model._base_manager.filter(pk=step.object_id).first()


def visible(step: Step, request: Any, obj: Any) -> bool:
    """Whether the reader still reaches the record - in its trash, too,
    where the action may have just put it."""
    from generic.trash import is_trashed

    resource = step.resource

    if resource.get_queryset(request).filter(pk=obj.pk).exists():
        return True

    return bool(resource.trash and is_trashed(obj))


def python_value(field_: Any, value: Any) -> Any:
    """A version's JSON value back as the field holds it."""
    if value is None:
        return None

    if field_.is_relation:
        return field_.target_field.to_python(value)

    return field_.to_python(value)


def concrete(step: Step, recreating: bool) -> list[Any]:
    """The fields put back. A field the database stamps on every save
    (``auto_now``) is left to it, unless the record is created again."""
    return [
        field_
        for field_ in tracked_fields(step.resource)
        if not field_.many_to_many
        and field_.name in step.values
        and (recreating or not getattr(field_, "auto_now", False))
    ]


def links(step: Step) -> list[Any]:
    return [
        field_
        for field_ in tracked_fields(step.resource)
        if field_.many_to_many and field_.name in step.values
    ]


def assign(obj: Any, fields: list[Any], values: dict) -> list[str]:
    """Set the fields from the version; the names of those that moved."""
    changed = []

    for field_ in fields:
        value = python_value(field_, values[field_.name])

        if field_.value_from_object(obj) != value:
            setattr(obj, field_.attname, value)
            changed.append(field_.attname)

    return changed


def set_links(obj: Any, fields: list[Any], values: dict) -> None:
    for field_ in fields:
        wanted = [
            python_value(field_.target_field, key)
            for key in values.get(field_.name) or []
        ]
        manager = getattr(obj, field_.name)
        held = set(manager.values_list("pk", flat=True))

        if held != set(wanted):
            manager.set(wanted)


def restore(step: Step, request: Any) -> None:
    resource = step.resource
    obj = current(step)

    if obj is None:
        raise Refused(
            gettext("Nothing was undone: “%(name)s” no longer exists.")
            % {"name": step.label}
        )

    if not (
        resource.has_change_permission(request, obj)
        and visible(step, request, obj)
    ):
        raise denied()

    changed = assign(obj, concrete(step, False), step.values)

    if changed:
        obj.save(update_fields=changed)

    set_links(obj, links(step), step.values)


def recreate(step: Step, request: Any) -> None:
    resource = step.resource
    model = resource.model

    if not resource.has_add_permission(request):
        raise denied()

    if current(step) is not None:
        raise Refused(
            gettext("Nothing was undone: “%(name)s” exists again.")
            % {"name": step.label}
        )

    obj = model()
    fields = concrete(step, True)
    assign(obj, fields, step.values)
    obj.pk = python_value(model._meta.pk, step.object_id)
    obj.save(force_insert=True)

    # A creation date is stamped on every insert: written back over the
    # stamp, as the record had it.
    stamped = {
        field_.attname: python_value(field_, step.values[field_.name])
        for field_ in fields
        if getattr(field_, "auto_now_add", False)
        or getattr(field_, "auto_now", False)
    }

    if stamped:
        model._base_manager.filter(pk=obj.pk).update(**stamped)

    set_links(obj, links(step), step.values)


def delete(step: Step, request: Any) -> int:
    """Delete what the action created. How many records went, links
    left out."""
    obj = current(step)

    if obj is None:
        # Gone already, with the parent created in the same action.
        return 0

    resource = step.resource

    if not (
        resource.has_delete_permission(request, obj)
        and visible(step, request, obj)
    ):
        raise denied()

    _total, by_model = obj.delete()

    return sum(
        count for label, count in by_model.items() if not is_link_model(label)
    )


def is_link_model(label: str) -> bool:
    """Whether ``app.Model`` is a many-to-many's own table."""
    from django.apps import apps

    try:
        return bool(apps.get_model(label)._meta.auto_created)
    except LookupError:  # pragma: no cover - a label Django just used
        return False


__all__ = [
    "Refused",
    "capture",
    "deletion_is_recorded",
    "from_message_tags",
    "is_offered",
    "message_tags",
    "offer",
    "plan",
    "undo",
]

"""Turning a save into a version.

Connected to the same models the site knows about, beside the signals
that already announce a change to open tables. Three rules keep it out
of everybody's way:

* **A version is the record's own fields.** Taken straight off the
  instance, so nothing here costs a query on the record's relations:
  a foreign key is stored as its key, and what it was called is looked
  up when the history is read.
* **A save that changed nothing writes nothing.** The values are
  compared with the last entry's before a row is written, so a form
  saved twice, or a ``save()`` that only touched a field nobody tracks,
  leaves no trace.
* **Recording must never break the save.** The entry is written in a
  savepoint of the caller's transaction: it rolls back with a change
  that is rolled back, and a failure to record is logged rather than
  raised.

Many-to-many fields are carried forward from the previous version and
refreshed when ``m2m_changed`` says so, which is the only moment they
can have changed. Bulk writes - ``update()``, ``bulk_create()`` - fire
no signal and so leave no history, exactly as they announce nothing.
"""

from __future__ import annotations

import datetime
import decimal
import logging
from typing import Any

from django.db import models, transaction
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.utils import timezone
from django.utils.encoding import force_str

from generic.conf import generic_settings
from generic.history.actor import current_actor
from generic.history.models import HistoryEntry

logger = logging.getLogger(__name__)

#: What a record was called, as an entry keeps it.
LABEL_LENGTH = 200


def json_safe(value: Any) -> Any:
    """A field's value, in something JSON can hold.

    Dates keep their ISO form rather than their local one: an entry is
    read back in whatever language and time zone the reader has, and
    only an unambiguous instant survives that.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, decimal.Decimal):
        return str(value)

    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}

    return force_str(value)


def is_recorded(resource: Any) -> bool:
    """Whether this resource's model keeps a history at all."""
    if not generic_settings.HISTORY:
        return False

    return bool(getattr(resource, "history", True))


def tracked_fields(resource: Any) -> list[Any]:
    """The fields a version of this model is made of.

    Its own columns and its own many-to-many fields - never a reverse
    relation, which belongs to the record at the other end and has a
    history of its own there.
    """
    excluded = set(getattr(resource, "history_exclude", ()) or ())
    fields = [
        *resource.model._meta.concrete_fields,
        *resource.model._meta.many_to_many,
    ]

    return [
        field
        for field in fields
        if field.name not in excluded and field.attname not in excluded
    ]


def snapshot(obj: Any, fields: list[Any], carry: dict[str, Any]) -> dict:
    """The record as it is now, by field name.

    ``carry`` is the previous version: many-to-many values come from it
    unchanged, because a save cannot have altered them and reading them
    would cost a query on every write.
    """
    values: dict[str, Any] = {}

    for field in fields:
        if field.many_to_many:
            if field.name in carry:
                values[field.name] = carry[field.name]

            continue

        values[field.name] = json_safe(stored_value(field, obj))

    return values


def stored_value(field: Any, obj: Any) -> Any:
    """A field's value as the database gives it back.

    ``Decimal(2)`` in a field of two places is read back as ``2.00``:
    kept as it was set, it would differ from the next version's as
    text, and a save changing something else would list it too.
    """
    value = field.value_from_object(obj)

    if (
        isinstance(field, models.DecimalField)
        and isinstance(value, decimal.Decimal)
        and value.is_finite()
    ):
        try:
            value = value.quantize(
                decimal.Decimal(1).scaleb(-field.decimal_places),
                context=field.context,
            )
        except decimal.InvalidOperation:
            pass

    return value


def last_entry(content_type: Any, object_id: str) -> HistoryEntry | None:
    """The newest version kept of one record, if there is one."""
    return (
        HistoryEntry.objects.filter(
            content_type=content_type,
            object_id=object_id,
        )
        .order_by("-version", "-pk")
        .first()
    )


# -- writing -------------------------------------------------------------


def record(
    resource: Any,
    obj: Any,
    action: str,
    object_id: Any = None,
) -> HistoryEntry | None:
    """Write the version ``obj`` is now at, if it is a new one.

    ``object_id`` is passed in by the deletion signal, which is the one
    moment the instance's own key is on its way out.
    """
    if not is_recorded(resource):
        return None

    identity = force_str(
        object_id if object_id is not None else (obj.pk or "")
    )

    if not identity:
        return None

    return _guarded(
        resource,
        identity,
        lambda: _version(resource, obj, action, identity),
    )


def _guarded(resource: Any, identity: str, write: Any) -> HistoryEntry | None:
    """Run a write in its own savepoint, and swallow what it raises.

    The change itself has already happened and is none of this module's
    business to undo; the savepoint means a failure here takes nothing
    else with it.
    """
    try:
        with transaction.atomic():
            return write()
    except Exception:
        logger.exception(
            "Could not record the history of %s %s",
            resource.label_lower,
            identity,
        )

        return None


def _version(
    resource: Any,
    obj: Any,
    action: str,
    identity: str,
) -> HistoryEntry | None:
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(resource.model)
    previous = last_entry(content_type, identity)
    before = (previous.values if previous is not None else {}) or {}
    values = snapshot(obj, tracked_fields(resource), before)

    # Saving a record without changing it is not a version of it. A
    # creation or a deletion always is: they are what happened.
    if (
        action == HistoryEntry.Action.UPDATED
        and previous is not None
        and before == values
    ):
        return None

    return _store(
        resource,
        obj,
        action,
        content_type,
        identity,
        previous,
        values,
    )


def _store(
    resource: Any,
    obj: Any,
    action: str,
    content_type: Any,
    identity: str,
    previous: HistoryEntry | None,
    values: dict[str, Any],
) -> HistoryEntry:
    """Add a version, or fold this write into the one being written."""
    actor = current_actor()
    label = force_str(resource.get_object_label(obj))[:LABEL_LENGTH]
    same_work = (
        previous is not None
        and previous.batch
        and previous.batch == actor.batch
    )

    if same_work and previous is not None:
        return _fold(previous, values, label, action)

    return HistoryEntry.objects.create(
        content_type=content_type,
        object_id=identity,
        label=label,
        version=(previous.version + 1) if previous is not None else 1,
        action=action,
        user=actor.person(),
        user_label=actor.label,
        source=actor.source,
        at=timezone.now(),
        batch=actor.batch,
        values=values,
    )


def _fold(
    previous: HistoryEntry,
    values: dict[str, Any],
    label: str,
    action: str,
) -> HistoryEntry:
    """Fold a second save of one unit of work into the entry it has.

    A form that saves a record and then its tags made one change, and a
    history saying so twice is a history nobody reads.
    """
    previous.values = values
    previous.label = label
    previous.at = timezone.now()

    # Created and then changed is still created; anything and then
    # deleted is deleted. What the record ended up as wins, except that
    # a creation never becomes an ordinary change.
    if action == HistoryEntry.Action.DELETED or (
        previous.action != HistoryEntry.Action.CREATED
    ):
        previous.action = action

    previous.save(update_fields=("values", "label", "at", "action"))

    return previous


def record_link(resource: Any, obj: Any, field: Any) -> None:
    """Record the new state of one many-to-many field.

    The only place the framework reads a relation in order to record
    it: a link changed, so the previous version's list is out of date
    and there is nothing to carry forward.
    """
    from django.contrib.contenttypes.models import ContentType

    if not is_recorded(resource):
        return

    identity = force_str(obj.pk or "")

    if not identity:
        return

    def write() -> HistoryEntry | None:
        keys = json_safe(
            list(getattr(obj, field.name).values_list("pk", flat=True))
        )
        content_type = ContentType.objects.get_for_model(resource.model)
        previous = last_entry(content_type, identity)
        before = (previous.values if previous is not None else {}) or {}

        if before.get(field.name) == keys:
            return None

        return _store(
            resource,
            obj,
            HistoryEntry.Action.UPDATED,
            content_type,
            identity,
            previous,
            {**before, field.name: keys},
        )

    _guarded(resource, identity, write)


# -- the signals ---------------------------------------------------------


def _dispatch_uid(resource: Any, signal: str) -> str:
    return (
        f"generic.history.{resource.site.name}."
        f"{resource.label_lower}.{signal}"
    )


def _m2m_field(model: Any, through: Any) -> Any:
    """Which many-to-many field this through model belongs to."""
    for field in model._meta.many_to_many:
        if field.remote_field.through is through:
            return field

    return None


def connect(resource: Any) -> None:
    """Start recording the versions of ``resource``'s model."""

    def saved(
        sender: Any,
        instance: Any,
        created: bool = False,
        raw: bool = False,
        **kwargs: Any,
    ) -> None:
        # A fixture being loaded is not somebody changing something.
        if raw:
            return

        record(
            resource,
            instance,
            (
                HistoryEntry.Action.CREATED
                if created
                else HistoryEntry.Action.UPDATED
            ),
        )

    def deleted(sender: Any, instance: Any, **kwargs: Any) -> None:
        record(
            resource,
            instance,
            HistoryEntry.Action.DELETED,
            object_id=instance.pk,
        )

    def linked(
        sender: Any,
        instance: Any,
        action: str = "",
        reverse: bool = False,
        **kwargs: Any,
    ) -> None:
        if action not in ("post_add", "post_remove", "post_clear"):
            return

        # Set from the other end, the record that changed is over
        # there, and its own history says so.
        if reverse or not isinstance(instance, resource.model):
            return

        field = _m2m_field(resource.model, sender)

        if field is not None:
            record_link(resource, instance, field)

    post_save.connect(
        saved,
        sender=resource.model,
        weak=False,
        dispatch_uid=_dispatch_uid(resource, "save"),
    )
    post_delete.connect(
        deleted,
        sender=resource.model,
        weak=False,
        dispatch_uid=_dispatch_uid(resource, "delete"),
    )

    for field in resource.model._meta.many_to_many:
        m2m_changed.connect(
            linked,
            sender=field.remote_field.through,
            weak=False,
            dispatch_uid=_dispatch_uid(resource, f"m2m.{field.name}"),
        )


def disconnect(resource: Any) -> None:
    post_save.disconnect(
        sender=resource.model,
        dispatch_uid=_dispatch_uid(resource, "save"),
    )
    post_delete.disconnect(
        sender=resource.model,
        dispatch_uid=_dispatch_uid(resource, "delete"),
    )

    for field in resource.model._meta.many_to_many:
        m2m_changed.disconnect(
            sender=field.remote_field.through,
            dispatch_uid=_dispatch_uid(resource, f"m2m.{field.name}"),
        )


__all__ = [
    "connect",
    "disconnect",
    "is_recorded",
    "json_safe",
    "last_entry",
    "record",
    "record_link",
    "snapshot",
    "tracked_fields",
]

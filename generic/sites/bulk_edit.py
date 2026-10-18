"""Several records changed at once, from the table that lists them.

A resource names the fields that may be given one value across a
selection, and the list gets the rest: an entry in the selection bar's
action menu, a dialog asking which fields to change and to what, a
review of what would happen, and the write::

    class TicketResource(ModelResource):
        bulk_edit_fields = ("team", "assignee", "priority", "tags")

What it has to get right:

* **Every record is still edited as its form would edit it.** Each one
  goes through the resource's own form serializer (partial: only the
  chosen fields) and ``save_bulk_edit`` - ``save_model`` by default -
  so a bulk edit refuses exactly what the form refuses, stamps what the
  form stamps, and cannot be a way round a rule.
* **Permissions are the record's, one record at a time.**
  ``has_change_permission(request, obj)`` and ``can_edit_column`` (the
  table's per-record rule) decide for each row; what may not be changed
  is left as it is and named, never half-written.
* **Nothing happens unseen.** The dialog first sends the edit as a dry
  run - the same work, rolled back - and shows how many records would
  change, how many already hold those values, and which would be left
  as they are and why. Only then does it write.
* **It is remembered.** One history version per record, by the reader,
  with the source ``Bulk edit: <fields>``; one live event for the whole
  edit (``realtime.batch``); watchers are told of each record.

A many-to-many field is not only replaced: tags are *added* to the
selection's or *removed* from it, keeping each record's others - which
is what one usually means by tagging forty tickets.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, models, router, transaction
from django.utils.encoding import force_str
from django.utils.translation import gettext, ngettext
from rest_framework import serializers

from generic.conf import generic_settings

#: What may be done to a field: give it a value, empty it, and - on a
#: many-to-many - add values to those it holds or take some away.
SET, CLEAR, ADD, REMOVE = "set", "clear", "add", "remove"
MODES = (SET, CLEAR, ADD, REMOVE)

#: Records named one by one in an answer: those left as they were.
MAX_PROBLEMS = 50

#: Fields a value is never shared by: what a record is told apart by,
#: what travels as a file.
NEVER = (models.FileField, models.AutoField)


@dataclasses.dataclass(frozen=True)
class BulkField:
    """One field a selection may be given a value of."""

    name: str
    field: Any

    @property
    def many(self) -> bool:
        return bool(self.field.many_to_many)

    @property
    def clearable(self) -> bool:
        """Whether the field may be left empty."""
        field = self.field

        if self.many:
            return bool(field.blank)

        if isinstance(field, models.BooleanField):
            return False

        return bool(
            field.null
            or (
                field.blank
                and isinstance(field, (models.CharField, models.TextField))
            )
        )

    @property
    def modes(self) -> tuple[str, ...]:
        if self.many:
            return (ADD, REMOVE, SET) + ((CLEAR,) if self.clearable else ())

        return (SET,) + ((CLEAR,) if self.clearable else ())

    @property
    def empty(self) -> Any:
        """What the field holds once cleared."""
        if self.many:
            return []

        return None if self.field.null else ""

    def value_for(self, obj: Any, mode: str, value: Any) -> Any:
        """What this record's field becomes, as a form would send it."""
        if mode == CLEAR:
            return self.empty

        if not self.many or mode == SET:
            return value

        current = list(getattr(obj, self.name).values_list("pk", flat=True))
        wanted = [str(item) for item in value]

        if mode == ADD:
            known = {str(item) for item in current}

            return current + [item for item in wanted if item not in known]

        dropped = set(wanted)

        return [item for item in current if str(item) not in dropped]


@dataclasses.dataclass(frozen=True)
class Change:
    """What a reader asked for one field."""

    field: BulkField
    mode: str
    value: Any = None


def check(resource: Any) -> dict[str, BulkField]:
    """The resource's bulk fields, resolved and checked, by name.

    Raises rather than guesses: a field offered in the dialog that no
    record can take is a dialog that fails after the reader filled it.
    """
    from generic.sites.transitions import state_fields

    if not resource.bulk_edit_fields:
        return {}

    owner = type(resource).__name__
    model = resource.model
    form_fields = set(resource.get_fields())
    read_only = set(resource.get_readonly_fields())
    states = set(state_fields(resource))
    resolved: dict[str, BulkField] = {}

    for name in resource.bulk_edit_fields:
        name = str(name)
        start = f"{owner}.bulk_edit_fields names '{name}'"

        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            raise ImproperlyConfigured(
                f"{start}, which is not a field of {model.__name__}."
            ) from None

        if field.auto_created or not field.concrete and not field.many_to_many:
            raise ImproperlyConfigured(
                f"{start}, which {model.__name__} does not hold itself: "
                f"edit it from the other side."
            )

        if name in states:
            raise ImproperlyConfigured(
                f"{start}, a state field: it changes through its "
                f"transitions, which are bulk actions already."
            )

        if isinstance(field, NEVER) or field.primary_key:
            raise ImproperlyConfigured(
                f"{start}: a file or a key is never given one value "
                f"across records."
            )

        if field.unique:
            raise ImproperlyConfigured(
                f"{start}, which is unique: two records could never "
                f"share its value."
            )

        if not field.editable or name in read_only:
            raise ImproperlyConfigured(
                f"{start}, which is read only on its form."
            )

        if name not in form_fields:
            raise ImproperlyConfigured(
                f"{start}, which is not on its form: a record is "
                f"validated by its form, and the form must know it."
            )

        resolved[name] = BulkField(name=name, field=field)

    return resolved


def infer(model: Any, form_fields: Any, exclude: Any = ()) -> tuple:
    """The fields a selection is usually given one value of.

    What sorts a record rather than names it: a choice, a yes or no, a
    relation, a date. Never free text - forty tickets rarely share a
    title - nor anything unique.
    """
    chosen = []

    for name in form_fields:
        if name in exclude:
            continue

        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            continue

        if (
            field.auto_created
            or not field.editable
            or isinstance(field, NEVER)
            or field.primary_key
            or getattr(field, "unique", False)
        ):
            continue

        if (
            field.choices
            or field.many_to_many
            or isinstance(
                field,
                (models.BooleanField, models.DateField, models.ForeignKey),
            )
        ):
            chosen.append(name)

    return tuple(chosen)


# -- the dialog -------------------------------------------------------------


MODE_LABELS = {
    SET: lambda: gettext("Set to"),
    CLEAR: lambda: gettext("Clear"),
    ADD: lambda: gettext("Add"),
    REMOVE: lambda: gettext("Remove"),
}


def describe(resource: Any, request: Any) -> dict[str, Any]:
    """The dialog's fields, as the form renderer describes them.

    Built from the resource's own form schema, so a relation searches
    what the form would offer (narrowed to the reader's teams), and a
    choice lists the form's choices.
    """
    fields = resource.get_bulk_edit_fields()
    schema = {
        entry["name"]: entry
        for entry in resource.get_form_serializer_for(request).get_form_fields(
            request=request
        )
    }
    described = []

    for name, bulk in fields.items():
        entry = schema.get(name)

        if entry is None or entry.get("readOnly"):
            continue

        # Whatever the form demands, a bulk edit asks only for what it
        # changes: the reader picks the field before giving the value.
        described.append(
            {
                **entry,
                "required": False,
                "modes": [
                    {"value": mode, "label": MODE_LABELS[mode]()}
                    for mode in bulk.modes
                ],
            }
        )

    return {
        "fields": described,
        "maxRows": generic_settings.BULK_EDIT_MAX_ROWS,
        "label": resource.get_label(),
        "labelPlural": resource.get_label_plural(),
        # For a sentence: "12 tickets selected."
        "name": force_str(resource.opts.verbose_name),
        "namePlural": force_str(resource.opts.verbose_name_plural),
    }


def read_changes(resource: Any, raw: Any) -> list[Change]:
    """The changes asked for, checked against the declaration.

    ``{"priority": {"mode": "set", "value": "high"}, "tags": {"mode":
    "add", "value": [3]}}``. The browser names fields the declaration
    lists, never anything else.
    """
    fields = resource.get_bulk_edit_fields()

    if not isinstance(raw, dict) or not raw:
        raise serializers.ValidationError(
            {"changes": [gettext("Choose at least one field to change.")]}
        )

    changes = []

    for name, entry in raw.items():
        bulk = fields.get(name)

        if bulk is None:
            raise serializers.ValidationError(
                {name: [gettext("This field cannot be changed in bulk.")]}
            )

        if not isinstance(entry, dict):
            entry = {"mode": SET, "value": entry}

        mode = entry.get("mode") or SET

        if mode not in bulk.modes:
            raise serializers.ValidationError(
                {name: [gettext("This field cannot be changed that way.")]}
            )

        value = entry.get("value")

        if bulk.many and mode != CLEAR:
            if value in (None, ""):
                value = []

            if not isinstance(value, list):
                raise serializers.ValidationError(
                    {name: [gettext("Expected a list of values.")]}
                )

            if mode in (ADD, REMOVE) and not value:
                raise serializers.ValidationError(
                    {name: [gettext("Choose at least one value.")]}
                )

        changes.append(Change(field=bulk, mode=mode, value=value))

    return changes


def messages_of(resource: Any, detail: Any) -> list[str]:
    """Serializer errors as sentences naming their field."""
    messages: list[str] = []

    if isinstance(detail, dict):
        for name, value in detail.items():
            try:
                label = force_str(
                    resource.model._meta.get_field(name).verbose_name
                )
            except FieldDoesNotExist:
                label = ""

            for message in messages_of(resource, value):
                messages.append(
                    f"{label[:1].upper()}{label[1:]}: {message}"
                    if label
                    else message
                )
    elif isinstance(detail, (list, tuple)):
        for item in detail:
            messages.extend(messages_of(resource, item))
    else:
        messages.append(force_str(detail))

    return messages


# -- the write --------------------------------------------------------------


def apply_one(
    resource: Any,
    request: Any,
    obj: Any,
    changes: list[Change],
    serializer_class: Any,
) -> tuple[str, list[str]]:
    """Change one record: what became of it, and why if it did not."""
    from generic.sites.imports import Importer

    if not resource.has_change_permission(request, obj):
        return "refused", [gettext("You may not change this record.")]

    frozen = [
        force_str(change.field.field.verbose_name)
        for change in changes
        if not resource.may_write_column(request, change.field.name, obj)
    ]

    if frozen:
        return "refused", [
            gettext("Not to be changed on this record: %(fields)s.")
            % {"fields": ", ".join(frozen)}
        ]

    data = {
        change.field.name: change.field.value_for(
            obj, change.mode, change.value
        )
        for change in changes
    }
    serializer = serializer_class(
        obj,
        data=data,
        partial=True,
        context={"request": request},
    )

    if not serializer.is_valid():
        return "invalid", messages_of(resource, serializer.errors)

    if Importer.is_unchanged(obj, serializer.validated_data):
        return "unchanged", []

    try:
        with transaction.atomic(using=router.db_for_write(resource.model)):
            resource.save_bulk_edit(request, serializer, obj)
    except serializers.ValidationError as error:
        return "invalid", messages_of(resource, error.detail)
    except DjangoValidationError as error:
        return "invalid", messages_of(
            resource,
            getattr(error, "message_dict", None) or error.messages,
        )
    except IntegrityError:
        return "invalid", [gettext("The database refused this change.")]

    return "changed", []


def run(
    resource: Any,
    request: Any,
    queryset: Any,
    raw_changes: Any,
    commit: bool = False,
) -> dict[str, Any]:
    """Apply the changes to every selected record - or, unless
    ``commit``, try them and roll everything back: the review.

    Records that may not be changed, or that their form refuses, are
    left as they were and named; the others are written. The review
    says which is which before anything is.
    """
    from generic.history import acting_as
    from generic.sites.realtime import batch

    changes = read_changes(resource, raw_changes)
    limit = generic_settings.BULK_EDIT_MAX_ROWS
    total = queryset.count()

    if limit and total > limit:
        raise serializers.ValidationError(
            {
                "detail": gettext(
                    "%(count)s records are selected; a bulk edit changes "
                    "%(limit)s at most. Narrow the selection with the "
                    "table's filters first."
                )
                % {"count": total, "limit": limit}
            }
        )

    counts = {
        "selected": total,
        "changed": 0,
        "unchanged": 0,
        "refused": 0,
        "invalid": 0,
    }
    problems: list[dict[str, Any]] = []
    serializer_class = resource.get_form_serializer_for(request)
    database = router.db_for_write(resource.model)
    names = ", ".join(change.field.name for change in changes)
    rows = queryset.order_by("pk")

    if any(change.field.many for change in changes):
        rows = rows.prefetch_related(
            *(change.field.name for change in changes if change.field.many)
        )

    with transaction.atomic(using=database):
        # The history says where the change came from (80 characters).
        source = f"Bulk edit: {names}"[:80]

        with acting_as(request.user, source=source):
            with batch(resource):
                for obj in rows:
                    outcome, messages = apply_one(
                        resource, request, obj, changes, serializer_class
                    )
                    counts[outcome] += 1

                    if messages and len(problems) < MAX_PROBLEMS:
                        problems.append(
                            {
                                "id": str(obj.pk),
                                "label": resource.get_object_label(obj),
                                "url": resource.get_object_url(obj.pk),
                                "status": outcome,
                                "messages": messages,
                            }
                        )

        # The review: everything done above is undone, and nobody is
        # told of it - events and notifications wait for a commit.
        if not commit:
            transaction.set_rollback(True, using=database)

    answer = {
        "counts": counts,
        "committed": bool(commit),
        "problems": problems,
        "moreProblems": counts["refused"] + counts["invalid"] > len(problems),
    }

    if commit:
        answer.update(report_of(resource, counts, problems))
    else:
        answer["message"] = review_message(resource, counts)
        answer["level"] = "info"

    return answer


def plural(resource: Any, count: int) -> str:
    return force_str(
        resource.opts.verbose_name
        if count == 1
        else resource.opts.verbose_name_plural
    )


def review_message(resource: Any, counts: dict[str, int]) -> str:
    changed = counts["changed"]

    return ngettext(
        "%(count)s %(name)s will change.",
        "%(count)s %(name)s will change.",
        changed,
    ) % {"count": changed, "name": plural(resource, changed)}


def report_of(
    resource: Any,
    counts: dict[str, int],
    problems: list[dict[str, Any]],
) -> dict[str, Any]:
    """The answer once written: a headline, and a report naming what
    was left as it was."""
    from generic.reports import Report
    from generic.tasks.operations import operation_payload

    report = Report()
    changed = counts["changed"]
    left = counts["refused"] + counts["invalid"]
    message = ngettext(
        "%(count)s %(name)s changed.",
        "%(count)s %(name)s changed.",
        changed,
    ) % {"count": changed, "name": plural(resource, changed)}

    if counts["unchanged"]:
        report.info(
            ngettext(
                "%(count)s already had these values.",
                "%(count)s already had these values.",
                counts["unchanged"],
            )
            % {"count": counts["unchanged"]}
        )

    if left:
        with report.section(
            ngettext(
                "%(count)s left as it was.",
                "%(count)s left as they were.",
                left,
            )
            % {"count": left}
        ) as section:
            for problem in problems:
                section.warning(
                    problem["label"],
                    " ".join(problem["messages"]),
                    url=problem["url"] or None,
                )

    payload = operation_payload(report, message)

    if left:
        payload["level"] = "warning"

    return payload


__all__ = [
    "ADD",
    "CLEAR",
    "MODES",
    "REMOVE",
    "SET",
    "BulkField",
    "Change",
    "check",
    "describe",
    "infer",
    "read_changes",
    "run",
]

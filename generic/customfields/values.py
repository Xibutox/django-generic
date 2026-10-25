"""Reading and writing what records hold in their custom fields.

A table reads its rows' values as annotations - one subquery a field -
so the same name is the cell, the filter and the order, and a page of
rows costs no query more. One record read on its own (a form, a summary)
loads all its values at once.

A value written is recorded in the record's own history, under
``cf:<key>``, folded into the version of the save it came with: the
record and its values are one unit of work.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any, Iterable

from django.db import models, transaction
from django.db.models import OuterRef, Subquery
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.encoding import force_str

from generic.customfields.definitions import definitions, is_enabled
from generic.customfields.models import (
    DECIMAL_DIGITS,
    DECIMAL_PLACES,
    HISTORY_PREFIX,
    CustomField,
    CustomValue,
)

#: Where an instance keeps the values loaded for it.
VALUES_ATTRIBUTE = "_generic_custom_values"


def identity(obj: Any) -> str:
    return force_str(obj.pk)


def output_field(definition: CustomField) -> models.Field:
    """The type of the annotation reading ``definition``'s values."""
    kind = definition.type

    if kind == CustomField.Type.INTEGER:
        return models.BigIntegerField()

    if kind == CustomField.Type.DECIMAL:
        return models.DecimalField(
            max_digits=DECIMAL_DIGITS, decimal_places=DECIMAL_PLACES
        )

    if kind == CustomField.Type.BOOLEAN:
        return models.BooleanField(null=True)

    if kind == CustomField.Type.DATE:
        return models.DateField()

    if kind == CustomField.Type.TIME:
        return models.TimeField()

    if kind == CustomField.Type.DATETIME:
        return models.DateTimeField()

    return models.TextField()


def subquery(definition: CustomField, outer: str = "pk") -> Subquery:
    """The value of the row ``outer`` points at, in ``definition``."""
    return Subquery(
        CustomValue.objects.filter(
            field_id=definition.pk,
            object_id=Cast(OuterRef(outer), models.CharField()),
        ).values(definition.column)[:1],
        output_field=output_field(definition),
    )


def subqueries(fields: Iterable[CustomField]) -> dict[str, Subquery]:
    """``{public name: subquery}`` for a table's queryset."""
    return {definition.name: subquery(definition) for definition in fields}


def annotate(queryset: Any, fields: Iterable[CustomField]) -> Any:
    found = subqueries(fields)

    return queryset.annotate(**found) if found else queryset


# -- one record -----------------------------------------------------------


def load(resource: Any, obj: Any, archived: bool = True) -> dict[str, Any]:
    """``{key: value}`` of ``obj``, loaded once and kept on it."""
    cached = getattr(obj, VALUES_ATTRIBUTE, None)

    if cached is not None:
        return cached

    if getattr(obj, "pk", None) is None:
        return {}

    fields = {
        definition.pk: definition
        for definition in definitions(resource, archived=archived)
    }
    found: dict[str, Any] = {}

    if fields:
        rows = CustomValue.objects.filter(
            field_id__in=list(fields), object_id=identity(obj)
        )

        for row in rows:
            definition = fields[row.field_id]
            found[definition.key] = clean(
                definition, getattr(row, definition.column)
            )

    setattr(obj, VALUES_ATTRIBUTE, found)

    return found


def forget(obj: Any) -> None:
    if hasattr(obj, VALUES_ATTRIBUTE):
        delattr(obj, VALUES_ATTRIBUTE)


def clean(definition: CustomField, value: Any) -> Any:
    """A stored value as the field holds it: a decimal to its places."""
    if value is None:
        return None

    if definition.type == CustomField.Type.DECIMAL:
        try:
            return decimal.Decimal(value).quantize(
                decimal.Decimal(1).scaleb(-definition.decimal_places)
            )
        except (decimal.InvalidOperation, TypeError, ValueError):
            return value

    if definition.type == CustomField.Type.DATETIME and isinstance(
        value, datetime.datetime
    ):
        if timezone.is_naive(value):
            return timezone.make_aware(value, datetime.timezone.utc)

    return value


def is_empty(value: Any) -> bool:
    return value is None or value == ""


def history_value(definition: CustomField, value: Any) -> Any:
    """``value`` as a version of the record keeps it."""
    from generic.history.recording import json_safe

    if is_empty(value):
        return None

    if (
        definition.type == CustomField.Type.DATETIME
        and isinstance(value, datetime.datetime)
        and timezone.is_aware(value)
    ):
        # One instant, one text: in UTC, as the database gives it back.
        value = value.astimezone(datetime.timezone.utc)

    return json_safe(clean(definition, value))


def python_value(definition: CustomField, raw: Any) -> Any:
    """A version's value back as the field takes it."""
    from django.utils.dateparse import parse_date, parse_datetime, parse_time

    if is_empty(raw):
        return None

    kind = definition.type

    try:
        if kind == CustomField.Type.INTEGER:
            return int(raw)

        if kind == CustomField.Type.DECIMAL:
            return decimal.Decimal(force_str(raw))

        if kind == CustomField.Type.BOOLEAN:
            return bool(raw)

        if kind == CustomField.Type.DATE:
            return parse_date(force_str(raw))

        if kind == CustomField.Type.TIME:
            return parse_time(force_str(raw))

        if kind == CustomField.Type.DATETIME:
            return parse_datetime(force_str(raw))
    except (TypeError, ValueError, decimal.InvalidOperation):
        return None

    return force_str(raw)


def write(
    resource: Any,
    obj: Any,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Set ``values`` (``{key: value}``) on ``obj``; empty clears.

    Only the keys given are touched. Answers what changed, as the
    history keeps it, and records it there.
    """
    if not values or not is_enabled(resource):
        return {}

    fields = {
        definition.key: definition
        for definition in definitions(resource, archived=True)
    }
    before = load(resource, obj)
    changes: dict[str, Any] = {}
    record_id = identity(obj)

    with transaction.atomic(using=CustomValue.objects.db):
        for key, value in values.items():
            definition = fields.get(key)

            if definition is None:
                continue

            value = None if is_empty(value) else clean(definition, value)
            was = before.get(key)

            if history_value(definition, was) == history_value(
                definition, value
            ):
                continue

            if value is None:
                CustomValue.objects.filter(
                    field=definition, object_id=record_id
                ).delete()
            else:
                CustomValue.objects.update_or_create(
                    field=definition,
                    object_id=record_id,
                    defaults=stored(definition, value),
                )

            changes[definition.history_name] = history_value(definition, value)

    current = {**before}

    for key, value in values.items():
        if key in fields:
            current[key] = (
                None if is_empty(value) else clean(fields[key], value)
            )

    setattr(
        obj,
        VALUES_ATTRIBUTE,
        {key: value for key, value in current.items() if value is not None},
    )

    if changes:
        record(resource, obj, changes)

    return changes


def stored(definition: CustomField, value: Any) -> dict[str, Any]:
    """The columns of a value row: its own set, the others empty."""
    columns = {
        "value_text": None,
        "value_integer": None,
        "value_decimal": None,
        "value_bool": None,
        "value_date": None,
        "value_time": None,
        "value_datetime": None,
    }
    columns[definition.column] = value

    return columns


def record(resource: Any, obj: Any, changes: dict[str, Any]) -> None:
    """Fold ``changes`` (``{"cf:<key>": value}``) into the record's
    history, like a many-to-many field's new state."""
    from django.contrib.contenttypes.models import ContentType

    from generic.history.models import HistoryEntry
    from generic.history.recording import (
        _guarded,
        _store,
        is_recorded,
        last_entry,
    )

    if not is_recorded(resource):
        return

    record_id = identity(obj)

    def store() -> Any:
        content_type = ContentType.objects.get_for_model(resource.model)
        previous = last_entry(content_type, record_id)
        before = dict((previous.values if previous is not None else {}) or {})
        after = {**before}

        for name, value in changes.items():
            if value is None:
                after.pop(name, None)
            else:
                after[name] = value

        if previous is not None and after == before:
            return None

        return _store(
            resource,
            obj,
            HistoryEntry.Action.UPDATED,
            content_type,
            record_id,
            previous,
            after,
        )

    _guarded(resource, record_id, store)


def restore(resource: Any, obj: Any, version: dict[str, Any]) -> None:
    """Put back the values a version of the record held (an undo)."""
    if not is_enabled(resource):
        return

    forget(obj)
    wanted = {
        definition.key: python_value(
            definition, version.get(definition.history_name)
        )
        for definition in definitions(resource, archived=True)
    }
    write(resource, obj, wanted)


def carried(values: dict[str, Any]) -> dict[str, Any]:
    """The custom values of a version, which a save carries forward."""
    return {
        name: value
        for name, value in (values or {}).items()
        if name.startswith(HISTORY_PREFIX)
    }


def delete_values(model: Any, record_id: Any) -> None:
    """Delete what a record held, once it is deleted itself."""
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(model)
    CustomValue.objects.filter(
        field__content_type=content_type, object_id=force_str(record_id)
    ).delete()


__all__ = [
    "annotate",
    "annotations",
    "carried",
    "delete_values",
    "history_value",
    "load",
    "python_value",
    "record",
    "restore",
    "subquery",
    "write",
]

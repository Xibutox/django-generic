"""A record's history, described for the page that shows it.

What changed is worked out here rather than stored: an entry holds the
record as it was, and the difference between two entries is the change
between them. Two consequences worth knowing:

* Adding or removing a tracked field never rewrites what is already
  recorded. The oldest entries simply have fewer fields.
* A page of history asks for one entry more than it shows, so the
  oldest one on the page still has something to be compared with.

Values arrive already written out - a key turned into the name of the
record it points at, a choice into its label, a date into the reader's
format - because the browser cannot know what any of them meant.
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import formats, timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.utils.encoding import force_str
from django.utils.text import capfirst
from django.utils.translation import gettext

from generic.history.models import HistoryEntry
from generic.history.recording import is_recorded, tracked_fields

#: Entries a page of history holds, and the most one may ask for.
PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def field_label(field: Any) -> str:
    name = getattr(field, "verbose_name", None) or field.name

    return capfirst(force_str(name))


def format_number(value: Any, decimal_places: int | None = None) -> str:
    return formats.number_format(
        value,
        decimal_pos=decimal_places,
        use_l10n=True,
        force_grouping=True,
    )


def is_empty(raw: Any) -> bool:
    if raw is None or raw == "":
        return True

    return isinstance(raw, (list, dict, tuple)) and not raw


def relation_keys(
    fields: dict[str, Any],
    entries: list[HistoryEntry],
) -> dict[str, set[str]]:
    """Every key each relation field mentions, across these entries."""
    wanted: dict[str, set[str]] = {}

    for entry in entries:
        for name, raw in (entry.values or {}).items():
            field = fields.get(name)

            if field is None or not field.is_relation or is_empty(raw):
                continue

            keys = raw if isinstance(raw, list) else [raw]
            wanted.setdefault(name, set()).update(
                force_str(key) for key in keys if key is not None
            )

    return wanted


def resolve_labels(
    fields: dict[str, Any],
    entries: list[HistoryEntry],
) -> dict[str, dict[str, str]]:
    """What every key mentioned is called, one query per model.

    A record that has since been deleted has no name left; its key is
    shown instead, which is still true and still says it changed.
    """
    found: dict[str, dict[str, str]] = {}

    for name, keys in relation_keys(fields, entries).items():
        model = fields[name].related_model

        try:
            rows = model._default_manager.filter(pk__in=sorted(keys))
            found[name] = {
                force_str(row.pk): force_str(row)[:200] for row in rows
            }
        except Exception:  # pragma: no cover - a key of the wrong shape
            found[name] = {}

    return found


def display_value(
    field: Any,
    raw: Any,
    labels: dict[str, dict[str, str]],
) -> str:
    """One stored value, written out the way a reader expects it."""
    if is_empty(raw):
        return ""

    known = labels.get(field.name, {})

    if field.many_to_many:
        keys = raw if isinstance(raw, list) else [raw]

        return ", ".join(known.get(force_str(key), f"#{key}") for key in keys)

    if field.is_relation:
        return known.get(force_str(raw), f"#{raw}")

    if getattr(field, "choices", None):
        return force_str(dict(field.flatchoices).get(raw, raw))

    if isinstance(field, models.BooleanField):
        return gettext("Yes") if raw else gettext("No")

    if isinstance(field, models.DateTimeField):
        moment = parse_datetime(force_str(raw))

        if moment is None:
            return force_str(raw)

        if timezone.is_aware(moment):
            moment = timezone.localtime(moment)

        return formats.date_format(moment, "DATETIME_FORMAT")

    if isinstance(field, models.DateField):
        day = parse_date(force_str(raw))

        return (
            formats.date_format(day, "DATE_FORMAT")
            if day is not None
            else force_str(raw)
        )

    if isinstance(field, models.TimeField):
        moment = parse_time(force_str(raw))

        return (
            formats.time_format(moment, "TIME_FORMAT")
            if moment is not None
            else force_str(raw)
        )

    if isinstance(field, models.DecimalField):
        try:
            return format_number(raw, field.decimal_places)
        except (TypeError, ValueError):
            return force_str(raw)

    if isinstance(field, models.JSONField):
        return json.dumps(raw, indent=2, ensure_ascii=False)

    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return format_number(raw)

    return force_str(raw)


def describe_values(
    fields: dict[str, Any],
    order: list[str],
    values: dict[str, Any],
    labels: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """The whole record as one version held it."""
    described = []

    for name in order:
        if name not in values:
            continue

        field = fields[name]
        raw = values[name]
        described.append(
            {
                "name": name,
                "label": field_label(field),
                "display": display_value(field, raw, labels),
                "empty": is_empty(raw),
            }
        )

    return described


def describe_changes(
    fields: dict[str, Any],
    order: list[str],
    before: dict[str, Any],
    after: dict[str, Any],
    labels: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """What one version altered, against the one before it."""
    changes = []

    for name in order:
        if name not in after and name not in before:
            continue

        was = before.get(name)
        now = after.get(name)

        if was == now:
            continue

        field = fields[name]
        changes.append(
            {
                "name": name,
                "label": field_label(field),
                "from": display_value(field, was, labels),
                "to": display_value(field, now, labels),
                "fromEmpty": is_empty(was),
                "toEmpty": is_empty(now),
            }
        )

    return changes


def describe_entry(
    entry: HistoryEntry,
    before: dict[str, Any] | None,
    fields: dict[str, Any],
    order: list[str],
    labels: dict[str, dict[str, str]],
) -> dict[str, Any]:
    moment = timezone.localtime(entry.at) if entry.at else None
    values = entry.values or {}

    return {
        "id": entry.pk,
        "version": entry.version,
        "action": entry.action,
        "actionLabel": force_str(
            HistoryEntry.Action(entry.action).label
            if entry.action in HistoryEntry.Action.values
            else entry.action
        ),
        "at": moment.isoformat() if moment is not None else "",
        "when": (
            formats.date_format(moment, "DATETIME_FORMAT")
            if moment is not None
            else ""
        ),
        "who": entry.who,
        "source": entry.source,
        "label": entry.label,
        # Nothing to compare the first version with: what it changed is
        # everything, which the values below already say.
        "changes": (
            describe_changes(fields, order, before, values, labels)
            if before is not None
            else []
        ),
        "values": describe_values(fields, order, values, labels),
    }


def page_size(asked: Any) -> int:
    try:
        wanted = int(asked)
    except (TypeError, ValueError):
        return PAGE_SIZE

    return max(1, min(MAX_PAGE_SIZE, wanted))


def entries_of(resource: Any, obj: Any) -> Any:
    """Every version kept of one record, newest first."""
    return HistoryEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(resource.model),
        object_id=force_str(obj.pk),
    ).order_by("-version", "-pk")


def build_history(
    resource: Any,
    request: Any,
    obj: Any,
    limit: Any = None,
    offset: Any = 0,
) -> dict[str, Any]:
    """A page of the record's history, as the tab draws it."""
    limit = page_size(limit)

    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0

    queryset = entries_of(resource, obj)
    count = queryset.count()
    # One more than the page: the oldest entry shown needs the version
    # before it to have anything to be a change from.
    rows = list(queryset.select_related("user")[offset : offset + limit + 1])
    page = rows[:limit]

    fields = {field.name: field for field in tracked_fields(resource)}
    order = list(fields)
    labels = resolve_labels(fields, rows)

    results = [
        describe_entry(
            entry,
            # None where there is no older version to be a change
            # from, which is the record's first entry and nothing else.
            (rows[index + 1].values or {}) if index + 1 < len(rows) else None,
            fields,
            order,
            labels,
        )
        for index, entry in enumerate(page)
    ]

    return {
        "count": count,
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(page) < count,
        "results": results,
    }


def last_change(resource: Any, obj: Any) -> dict[str, Any] | None:
    """Who last changed this record, and when. ``None`` if nobody has."""
    if not is_recorded(resource):
        return None

    entry = entries_of(resource, obj).select_related("user").first()

    if entry is None:
        return None

    moment = timezone.localtime(entry.at) if entry.at else None

    return {
        "version": entry.version,
        "action": entry.action,
        "actionLabel": force_str(
            HistoryEntry.Action(entry.action).label
            if entry.action in HistoryEntry.Action.values
            else entry.action
        ),
        "who": entry.who,
        "at": moment.isoformat() if moment is not None else "",
        "when": (
            formats.date_format(moment, "DATETIME_FORMAT")
            if moment is not None
            else ""
        ),
    }


__all__ = [
    "MAX_PAGE_SIZE",
    "PAGE_SIZE",
    "build_history",
    "describe_entry",
    "display_value",
    "entries_of",
    "last_change",
]

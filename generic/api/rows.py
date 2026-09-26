"""Tables over rows that are not in the database.

A list of dicts - an external API's answer, a file, a computation - is
served by the same protocol as a model's table: the same filter tree,
search box, ordering, facets and exports, worked out in Python::

    class ServiceSerializer(DataTableSerializer):
        name = CharColumn(title="Service")
        status = ChoiceColumn(choices=STATUSES)
        uptime = FloatColumn(title="Uptime %")

    class ServiceViewSet(RowsDataTableViewSet):
        serializer_class = ServiceSerializer
        ordering = ("name",)

        def get_rows(self):
            return statuspage.services()      # [{"name": ..., ...}, ...]

The conditions go through the same whitelist and engines as a
queryset's: they build a ``Q``, and :func:`matches` reads that ``Q``
against a row instead of handing it to the database. A value the API
sends as text - ``"2026-09-20T08:15:00Z"``, ``"99.95"`` - is read as the
date or the number the condition compares it with.

A row is a mapping, or any object: ``a__b`` walks ``row["a"]["b"]``, or
attributes. A list is several values, as a many-valued relation is: a
condition holds when one of them matches, and a negation when none does.
"""

from __future__ import annotations

import datetime
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.encoding import force_str

from generic.api.columns import (
    BooleanColumn,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    FloatColumn,
    IntegerColumn,
)
from generic.api.exports import localize_for_export
from generic.api.facets import IDS_PARAM, SEARCH_PARAM, coerce_keys, plain
from generic.api.filters import (
    FALSE_VALUES,
    TRUE_VALUES,
    AdvancedFilterBackend,
    DataTablesOrderingBackend,
    DataTablesSearchBackend,
    FilterTreeBuilder,
    split_search_terms,
)
from generic.api.viewsets import DataTableViewSet
from generic.search import TRANSFORM, fold, normalize

#: The lookups the filter engines write, read here against a value.
LOOKUPS = frozenset(
    {
        "exact",
        "iexact",
        "contains",
        "icontains",
        "startswith",
        "istartswith",
        "endswith",
        "iendswith",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "isnull",
    }
)

#: What the engines put between a field and its lookup: the date
#: engine's day, and the search's accents set aside (generic.search).
TRANSFORMS = frozenset({"date", TRANSFORM})

SEVERAL = (list, tuple, set, frozenset)


class RowList(list):
    """Rows the table machinery reads as it reads a queryset.

    Counted with ``count()``, sliced into more rows, iterated in chunks
    and asked whether it ``exists()``: the pagination, the total count
    and the exports then need nothing of their own.
    """

    def count(self, *args: Any) -> int:  # type: ignore[override]
        # ``list.count(value)`` keeps working.
        return super().count(*args) if args else len(self)

    def iterator(self, chunk_size: int | None = None) -> Iterable[Any]:
        return iter(self)

    def exists(self) -> bool:
        return bool(self)

    def __getitem__(self, index: Any) -> Any:
        result = super().__getitem__(index)

        return RowList(result) if isinstance(index, slice) else result


# ---------------------------------------------------------------------
# Reading a row
# ---------------------------------------------------------------------


def read(item: Any, name: str) -> Any:
    """One key of a mapping, or one attribute of an object."""
    if item is None:
        return None

    if isinstance(item, Mapping):
        return item.get(name)

    return getattr(item, name, None)


def values_at(row: Any, path: str | Sequence[str]) -> list[Any]:
    """Every value at ``a__b`` in ``row``, lists flattened.

    ``[None]`` where the key is missing or empty, ``[]`` where a list is
    empty - which is how "is empty" tells them apart from a value.
    """
    parts = path.split("__") if isinstance(path, str) else list(path)
    current = [row]

    for part in parts:
        following: list[Any] = []

        for item in current:
            value = read(item, part)

            if isinstance(value, SEVERAL):
                following.extend(value)
            else:
                following.append(value)

        current = following

    return current


def text_of(value: Any) -> str:
    """What a value reads as, for a text comparison or the search."""
    if isinstance(value, Mapping):
        value = value.get("label", value.get("name", ""))

    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()

    return force_str(value)


# ---------------------------------------------------------------------
# Values as the condition expects them
# ---------------------------------------------------------------------


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, (int, float, Decimal)):
        return bool(value)

    text = str(value).strip().lower()

    if text in TRUE_VALUES:
        return True

    if text in FALSE_VALUES:
        return False

    return None


def as_number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None

    return number if number.is_finite() else None


def as_datetime(value: Any) -> datetime.datetime | None:
    """An aware datetime: a naive one is read in the active timezone."""
    if isinstance(value, str):
        text = value.strip()
        value = parse_datetime(text) or parse_date(text[:10])

    if isinstance(value, datetime.datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value)

        return value

    if isinstance(value, datetime.date):
        return timezone.make_aware(
            datetime.datetime.combine(value, datetime.time.min)
        )

    return None


def as_date(value: Any) -> datetime.date | None:
    if isinstance(value, str):
        text = value.strip()
        value = parse_datetime(text) or parse_date(text[:10])

    if isinstance(value, datetime.datetime):
        return (
            timezone.localtime(value).date()
            if (timezone.is_aware(value))
            else value.date()
        )

    if isinstance(value, datetime.date):
        return value

    return None


def like(value: Any, target: Any) -> Any:
    """``value`` as the kind of thing ``target`` is, or ``None``."""
    if isinstance(target, bool):
        return as_bool(value)

    if isinstance(target, datetime.datetime):
        return as_datetime(value)

    if isinstance(target, datetime.date):
        return as_date(value)

    if isinstance(target, (int, float, Decimal)):
        return as_number(value)

    if isinstance(target, str):
        return text_of(value)

    return value


def equal(value: Any, target: Any) -> bool:
    converted = like(value, target)

    if converted is None:
        return False

    if isinstance(target, (int, float)) and not isinstance(target, bool):
        target = as_number(target)

    return converted == target


# ---------------------------------------------------------------------
# A condition against a row
# ---------------------------------------------------------------------


def split_lookup(key: str) -> tuple[list[str], str | None, str]:
    """``due__date__gte`` -> ``(["due"], "date", "gte")``."""
    parts = key.split("__")
    lookup = "exact"
    transform = None

    if len(parts) > 1 and parts[-1] in LOOKUPS:
        lookup = parts.pop()

    if len(parts) > 1 and parts[-1] in TRANSFORMS:
        transform = parts.pop()

    return parts, transform, lookup


def compare(value: Any, lookup: str, target: Any) -> bool:
    """Whether one value satisfies ``lookup`` against ``target``."""
    if lookup == "in":
        return any(equal(value, item) for item in target)

    if lookup == "exact":
        return equal(value, target)

    if lookup in {"gt", "gte", "lt", "lte"}:
        converted = like(value, target)

        if isinstance(target, (int, float)) and not isinstance(target, bool):
            target = as_number(target)

        if converted is None:
            return False

        try:
            return {
                "gt": converted > target,
                "gte": converted >= target,
                "lt": converted < target,
                "lte": converted <= target,
            }[lookup]
        except TypeError:
            return False

    text = text_of(value)
    wanted = force_str(target)

    if lookup.startswith("i"):
        text, wanted = text.casefold(), wanted.casefold()
        lookup = lookup[1:]

    if lookup == "exact":
        return text == wanted

    if lookup == "contains":
        return wanted in text

    if lookup == "startswith":
        return text.startswith(wanted)

    if lookup == "endswith":
        return text.endswith(wanted)

    return False


def match_lookup(row: Any, key: str, target: Any) -> bool:
    parts, transform, lookup = split_lookup(key)
    values = values_at(row, parts)

    if transform == "date":
        values = [as_date(value) for value in values]
    elif transform == TRANSFORM:
        values = [fold(text_of(value)) for value in values]
        target = (
            [fold(item) for item in target]
            if isinstance(target, SEVERAL)
            else fold(target)
        )

    present = [value for value in values if value is not None]

    if lookup == "isnull":
        return (not present) == bool(target)

    return any(compare(value, lookup, target) for value in present)


def matches(condition: Q, row: Any) -> bool:
    """Whether ``row`` satisfies ``condition``, as the database would."""
    results = (
        (
            matches(child, row)
            if isinstance(child, Q)
            else match_lookup(row, child[0], child[1])
        )
        for child in condition.children
    )

    if not condition.children:
        result = True
    elif condition.connector == Q.OR:
        result = any(results)
    else:
        result = all(results)

    return not result if condition.negated else result


def filter_rows(rows: Iterable[Any], conditions: Sequence[Q]) -> RowList:
    return RowList(
        row
        for row in rows
        if all(matches(condition, row) for condition in conditions)
    )


# ---------------------------------------------------------------------
# Search and ordering
# ---------------------------------------------------------------------


def search_rows(rows: Iterable[Any], fields: Sequence[str], raw: str) -> Any:
    """The search box over rows: every word in one of ``fields``, a
    ``!word`` in none of them - as :func:`generic.api.filters.apply_search`
    means it on a queryset."""
    terms = split_search_terms(raw)

    if not terms or not fields:
        return rows

    def texts(row: Any) -> list[str]:
        return [
            normalize(text_of(value))
            for field in fields
            for value in values_at(row, field)
            if value is not None
        ]

    kept = RowList()

    for row in rows:
        found = texts(row)

        if all(
            any(normalize(text) in value for value in found) != negated
            for text, negated in terms
        ):
            kept.append(row)

    return kept


def sort_key(value: Any) -> tuple[int, int, Any]:
    """Values of any kind in one order: empty last, then by kind."""
    if value is None or value == "":
        return (1, 0, "")

    if isinstance(value, bool):
        return (0, 0, int(value))

    if isinstance(value, (int, float, Decimal)):
        return (0, 0, value)

    if isinstance(value, (datetime.date, datetime.datetime)):
        if isinstance(value, datetime.datetime) and timezone.is_aware(value):
            value = value.astimezone(datetime.timezone.utc)

        return (0, 1, value.isoformat())

    return (0, 2, text_of(value).casefold())


def order_rows(rows: Iterable[Any], ordering: Sequence[str]) -> RowList:
    """Rows sorted by ``["-uptime", "name"]``, empty values last - and
    first when descending, as PostgreSQL sorts them."""
    ordered = list(rows)

    for item in reversed(list(ordering)):
        descending = item.startswith("-")
        path = item.lstrip("-")

        def key(row: Any, path: str = path) -> tuple[int, int, Any]:
            values = values_at(row, path)

            return sort_key(values[0] if values else None)

        ordered.sort(key=key, reverse=descending)

    return RowList(ordered)


# ---------------------------------------------------------------------
# Filter backends
# ---------------------------------------------------------------------


class RowFilterTreeBuilder(FilterTreeBuilder):
    """The tree's ``Q``, without the subqueries a database needs: a list
    in a row is matched value by value already."""

    def through(self, predicate: Q) -> Q:
        return predicate


class RowFilterBackend(AdvancedFilterBackend):
    builder_class = RowFilterTreeBuilder

    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        conditions = self.get_conditions(request, view, None)

        return filter_rows(queryset, conditions) if conditions else queryset


class RowSearchBackend(DataTablesSearchBackend):
    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        term = (
            request.query_params.get(self.search_param)
            or request.query_params.get(self.fallback_search_param)
            or ""
        ).strip()

        if not term:
            return queryset

        return search_rows(queryset, self.get_search_fields(view), term)


class RowOrderingBackend(DataTablesOrderingBackend):
    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        allowed = self.get_ordering_fields(view)
        ordering = self.get_ordering(request, allowed) if allowed else []

        if not ordering:
            ordering = list(getattr(view, "ordering", ()) or ())

        return order_rows(queryset, ordering) if ordering else queryset


#: What a table over rows installs, in order.
ROW_FILTER_BACKENDS = (
    RowFilterBackend,
    RowSearchBackend,
    RowOrderingBackend,
)


# ---------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------


class RowsDataTableViewSet(DataTableViewSet):
    """A read only table endpoint over rows from anywhere.

    ``serializer_class`` is a :class:`~generic.api.DataTableSerializer`
    declaring the columns; ``get_rows()`` returns the rows. Filters,
    search, ordering (``ordering`` when the client asks for none),
    pagination, facets and both exports work as they do on a model.
    """

    filter_backends = ROW_FILTER_BACKENDS

    #: The order when the client asks for none: ``("-uptime", "name")``.
    ordering: Sequence[str] = ()

    def get_rows(self) -> Iterable[Any]:
        raise NotImplementedError(
            f"{type(self).__name__} must define get_rows()."
        )

    def get_queryset(self) -> RowList:
        return RowList(self.get_rows())

    # -- exports ------------------------------------------------------

    def iter_export_rows(
        self,
        queryset: Any,
        columns: list[dict[str, Any]],
    ) -> Iterable[list[Any]]:
        """As a model's, with dates and numbers the API sent as text
        written as dates and numbers: a spreadsheet can sort those."""
        fields = self.get_serializer_class()().fields
        readers = [
            export_reader(fields[column["data"]])
            for column in columns
            if column["data"] in fields
        ]

        for values in super().iter_export_rows(queryset, columns):
            yield [
                read(value) if isinstance(value, str) else value
                for read, value in zip(readers, values)
            ]

    # -- facets -------------------------------------------------------

    def get_facet_queryset(self, filtered: Any) -> Any:
        return filtered

    def range_facet(self, queryset: Any, spec: Any) -> dict[str, Any]:
        read_as = as_date if spec.type in {"date", "datetime"} else as_number
        found = []
        empty = 0

        for row in queryset:
            values = [
                converted
                for converted in (
                    read_as(value) for value in values_at(row, spec.field)
                )
                if converted is not None
            ]

            if values:
                found.extend(values)
            else:
                empty += 1

        return {
            "kind": "range",
            "min": plain(min(found)) if found else None,
            "max": plain(max(found)) if found else None,
            "empty": empty,
        }

    def value_facet(
        self,
        queryset: Any,
        field: Any,
        options: Any,
        spec: Any,
        request: Any,
    ) -> dict[str, Any]:
        choices = dict(getattr(field, "choices", None) or {})
        counts: Counter = Counter()

        for row in queryset:
            keys = {
                facet_key(value)
                for value in values_at(row, spec.field)
                if value is not None and value != ""
            }

            counts.update(keys or {None})

        raw_ids = request.query_params.get(IDS_PARAM)
        term = (request.query_params.get(SEARCH_PARAM) or "").strip()[:100]
        wanted = (
            {str(item) for item in coerce_keys(spec, raw_ids)}
            if raw_ids is not None
            else set()
        )
        style = getattr(field, "tag_style", None)
        entries = []

        for key, count in counts.items():
            label = self.facet_label(key, None, choices, spec)

            if raw_ids is not None:
                if str(key) not in wanted:
                    continue
            elif term and normalize(term) not in normalize(label):
                continue

            entry = {"value": plain(key), "label": label, "count": count}

            if style is not None and key is not None:
                tag = style.describe(key, label)

                if tag:
                    entry["tag"] = tag

            entries.append(entry)

        entries.sort(key=lambda item: (-item["count"], item["label"]))
        limit = self.facet_limit

        return {
            "kind": "values",
            "values": entries[:limit],
            "more": len(entries) > limit,
        }


def export_reader(field: Any) -> Any:
    """How a column's text is read back for a spreadsheet."""

    def keep(value: str) -> Any:
        return value

    def fallback(reader: Any) -> Any:
        def read(value: str) -> Any:
            converted = reader(value)

            return value if converted is None else converted

        return read

    if isinstance(field, DateTimeColumn):

        def moment(value: str) -> Any:
            found = as_datetime(value)

            return localize_for_export(found) if found is not None else None

        return fallback(moment)

    if isinstance(field, DateColumn):
        return fallback(as_date)

    if isinstance(field, (IntegerColumn, FloatColumn, DecimalColumn)):
        return fallback(as_number)

    if isinstance(field, BooleanColumn):
        return fallback(as_bool)

    return keep


def facet_key(value: Any) -> Any:
    """What one value is counted as: a tag by its id or its label."""
    if isinstance(value, Mapping):
        return value.get("id", value.get("value", value.get("label")))

    return value


__all__ = [
    "ROW_FILTER_BACKENDS",
    "RowFilterBackend",
    "RowList",
    "RowOrderingBackend",
    "RowSearchBackend",
    "RowsDataTableViewSet",
    "as_bool",
    "as_date",
    "as_datetime",
    "as_number",
    "filter_rows",
    "matches",
    "order_rows",
    "search_rows",
    "values_at",
]

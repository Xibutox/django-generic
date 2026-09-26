"""Server side filtering, searching and ordering for data tables.

The client sends public column names and operators. Every name is
resolved through the serializer declaration before it reaches the ORM, so
a client supplied lookup path is never interpolated into a query.

Three DRF filter backends, applied in this order:

``AdvancedFilterBackend``
    The conditions: a tree sent as ``filters`` - conditions grouped with
    *all* or *any*, as deep as ``MAX_DEPTH`` - or the older flat
    ``advanced_filters`` payload, one condition per column.

``DataTablesSearchBackend``
    The global search box, spanning every searchable text column.

``DataTablesOrderingBackend``
    ``order[i][column]`` resolved through the columns the client echoed
    back, then validated against the orderable whitelist.

A filter tree::

    {
      "match": "all",
      "conditions": [
        {"column": "status", "operator": "any_of", "value": ["open"]},
        {"column": "opened_at", "operator": "last_days", "value": 30},
        {"match": "any", "conditions": [
          {"column": "priority", "operator": "any_of", "value": ["urgent"]},
          {"column": "tags", "operator": "empty"}
        ]}
      ]
    }
"""

from __future__ import annotations

import datetime
import json
import operator as operators
import re
from decimal import Decimal, InvalidOperation
from functools import reduce
from typing import Any, Callable, Iterable, Sequence

from django.contrib.admin.utils import lookup_spawns_duplicates
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend

from generic.api.columns import (
    FILTER_BOOLEAN,
    FILTER_DATE,
    FILTER_DATETIME,
    FILTER_FLOAT,
    FILTER_INTEGER,
    FILTER_MULTISELECT,
    FILTER_TEXT,
    FilterSpec,
)

#: Query parameter carrying a filter tree.
FILTERS_PARAM = "filters"

#: Query parameter carrying the older flat payload: one condition per
#: column, all of them required. Still accepted - saved views, presets
#: and links made before the tree exist.
ADVANCED_FILTERS_PARAM = "advanced_filters"

#: Refuse absurd payloads outright rather than building the query.
MAX_FILTERS = 50
MAX_DEPTH = 4
MAX_MULTISELECT_VALUES = 1000
MAX_SEARCH_TERMS = 10
MAX_DAYS = 36600

MATCH_ALL = "all"
MATCH_ANY = "any"

TRUE_VALUES = frozenset({"true", "1", "yes", "on", "t", "y"})
FALSE_VALUES = frozenset({"false", "0", "no", "off", "f", "n"})

#: Operators every engine understands: no value, a null or blank field.
EMPTY_OPERATORS = frozenset({"empty", "not_empty"})

#: Calendar periods around today, in the active timezone.
RELATIVE_PERIODS = frozenset(
    {
        "today",
        "yesterday",
        "tomorrow",
        "this_week",
        "last_week",
        "next_week",
        "this_month",
        "last_month",
        "next_month",
        "this_quarter",
        "last_quarter",
        "next_quarter",
        "this_year",
        "last_year",
        "next_year",
    }
)

#: Date operators taking a number of days.
DAY_OPERATORS = frozenset({"last_days", "next_days", "older_than_days"})

#: Operators needing no value: an empty ``value`` does not drop them.
VALUELESS_OPERATORS = (
    EMPTY_OPERATORS | RELATIVE_PERIODS | frozenset({"is_true", "is_false"})
)


def _error(message: Any) -> ValidationError:
    return ValidationError({FILTERS_PARAM: [message]})


def _start_of_day(value: datetime.date) -> datetime.datetime:
    return timezone.make_aware(
        datetime.datetime.combine(value, datetime.time.min),
        timezone.get_current_timezone(),
    )


def _end_of_day(value: datetime.date) -> datetime.datetime:
    return timezone.make_aware(
        datetime.datetime.combine(value, datetime.time.max),
        timezone.get_current_timezone(),
    )


def _parse_date(name: str, raw_value: Any) -> datetime.date:
    value = parse_date(str(raw_value)[:10]) if raw_value else None

    if value is None:
        raise _error(
            _("%(column)s must use the YYYY-MM-DD format.") % {"column": name}
        )

    return value


def _any(conditions: Iterable[Q]) -> Q:
    return reduce(operators.or_, conditions)


def _all(conditions: Iterable[Q]) -> Q:
    return reduce(operators.and_, conditions)


def _empty(spec: FilterSpec, blank: bool = False) -> Q:
    """No value: a null, and for text an empty string too."""
    condition = Q(**{f"{spec.field}__isnull": True})

    if blank:
        condition |= Q(**{spec.field: ""})

    return condition


# ---------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------

#: A quoted phrase, optionally negated, or a bare word.
_TERM_PATTERN = re.compile(r'([!-]?)"([^"]*)"|(\S+)')


def split_search_terms(raw: str) -> list[tuple[str, bool]]:
    """Split a search box value into ``(text, negated)`` terms.

    Every term must match, which is what users expect of a search box:
    ``invoice blank`` finds rows mentioning both. A term starting with
    ``!`` or ``-`` must *not* match, and double quotes keep a phrase
    whole: ``"password reset" -closed``.
    """
    terms: list[tuple[str, bool]] = []

    for prefix, phrase, word in _TERM_PATTERN.findall(raw or ""):
        if word:
            negated = len(word) > 1 and word[0] in "!-"
            text = word[1:] if negated else word
        else:
            negated = bool(prefix)
            text = phrase

        text = text.strip()

        if text:
            terms.append((text, negated))

    return terms[:MAX_SEARCH_TERMS]


def apply_search(
    queryset: QuerySet,
    fields: Sequence[str],
    raw_term: str,
) -> QuerySet:
    """Filter ``queryset`` on a search box value across ``fields``.

    Used by the table search, the autocomplete endpoints and the command
    palette alike, so the three agree on what a search means.
    """
    terms = split_search_terms(raw_term)

    if not terms or not fields:
        return queryset

    model = queryset.model

    # Searching through a many-valued relation would list a row once
    # per match; matching through a subquery on the primary key keeps
    # each row once and leaves annotations untouched.
    spawns_duplicates = any(
        lookup_spawns_duplicates(model._meta, field) for field in fields
    )

    for text, negated in terms:
        condition = Q()

        for field in fields:
            condition |= Q(**{f"{field}__icontains": text})

        if spawns_duplicates:
            condition = Q(
                pk__in=model._default_manager.filter(condition).values("pk")
            )

        queryset = (
            queryset.exclude(condition)
            if negated
            else queryset.filter(condition)
        )

    return queryset


# ---------------------------------------------------------------------
# Filter engines
# ---------------------------------------------------------------------

#: An engine turns one condition into a queryset predicate. It returns
#: the predicate and whether it is negated. The negation is applied by
#: the caller: across a many-valued relation "does not contain" has to
#: mean "has no value containing", which only a subquery says.
EngineResult = tuple[Q, bool]
Engine = Callable[[str, FilterSpec, str, Any], EngineResult]


#: Operator -> (lookup, negated). The first four names are the older
#: spelling, still accepted.
TEXT_LOOKUPS = {
    "exact": ("iexact", False),
    "not_exact": ("iexact", True),
    "starts": ("istartswith", False),
    "ends": ("iendswith", False),
    "contains": ("icontains", False),
    "not_contains": ("icontains", True),
    "equals": ("iexact", False),
    "not_equals": ("iexact", True),
    "starts_with": ("istartswith", False),
    "not_starts_with": ("istartswith", True),
    "ends_with": ("iendswith", False),
    "not_ends_with": ("iendswith", True),
}

#: Operator -> (lookup, negated), for numbers. Older spelling first.
COMPARISON_LOOKUPS = {
    "exact": ("exact", False),
    "not_exact": ("exact", True),
    "greater_than": ("gt", False),
    "greater_or_equal": ("gte", False),
    "less_than": ("lt", False),
    "less_or_equal": ("lte", False),
    "equals": ("exact", False),
    "not_equals": ("exact", True),
    "gt": ("gt", False),
    "gte": ("gte", False),
    "lt": ("lt", False),
    "lte": ("lte", False),
}


def _values(name: str, raw_value: Any) -> list[Any]:
    """One value or a list of them, blanks dropped."""
    values = raw_value if isinstance(raw_value, list) else [raw_value]

    if len(values) > MAX_MULTISELECT_VALUES:
        raise _error(_("%(column)s holds too many values.") % {"column": name})

    return [value for value in values if value not in (None, "")]


def text_engine(
    name: str,
    spec: FilterSpec,
    operator: str,
    raw_value: Any,
) -> EngineResult:
    if operator in EMPTY_OPERATORS:
        return _empty(spec, blank=True), operator == "not_empty"

    entry = TEXT_LOOKUPS.get(operator)

    if entry is None:
        raise _error(
            _("Invalid text operator '%(operator)s' for %(column)s.")
            % {"operator": operator, "column": name}
        )

    lookup, negate = entry
    values = [str(value) for value in _values(name, raw_value)]

    if not values:
        raise _error(_("%(column)s needs a value.") % {"column": name})

    # Several values: any of them matches - and with a negated operator,
    # none of them may.
    return (
        _any(Q(**{f"{spec.field}__{lookup}": value}) for value in values),
        negate,
    )


def _number(name: str, spec: FilterSpec, raw_value: Any) -> Decimal:
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, ValueError) as error:
        raise _error(
            _("%(column)s must be a number.") % {"column": name}
        ) from error

    if not value.is_finite():
        raise _error(_("%(column)s must be a number.") % {"column": name})

    if spec.value_type == "integer" and value != value.to_integral_value():
        raise _error(
            _("%(column)s must be a whole number.") % {"column": name}
        )

    return value


def _bounds(raw_value: Any) -> tuple[Any, Any]:
    """``[low, high]`` or ``{"from": low, "to": high}``."""
    if isinstance(raw_value, dict):
        return raw_value.get("from"), raw_value.get("to")

    if isinstance(raw_value, (list, tuple)) and len(raw_value) == 2:
        return raw_value[0], raw_value[1]

    return None, None


def numeric_engine(
    name: str,
    spec: FilterSpec,
    operator: str,
    raw_value: Any,
) -> EngineResult:
    if operator in EMPTY_OPERATORS:
        return _empty(spec), operator == "not_empty"

    if operator == "between":
        low, high = _bounds(raw_value)
        low = _number(name, spec, low) if low not in (None, "") else None
        high = _number(name, spec, high) if high not in (None, "") else None

        if low is None and high is None:
            raise _error(
                _("%(column)s needs at least one bound.") % {"column": name}
            )

        if low is not None and high is not None and low > high:
            raise _error(
                _("%(column)s: the lower bound is above the upper one.")
                % {"column": name}
            )

        condition = Q()

        if low is not None:
            condition &= Q(**{f"{spec.field}__gte": low})

        if high is not None:
            condition &= Q(**{f"{spec.field}__lte": high})

        return condition, False

    entry = COMPARISON_LOOKUPS.get(operator)

    if entry is None:
        raise _error(
            _("Invalid numeric operator '%(operator)s' for %(column)s.")
            % {"operator": operator, "column": name}
        )

    value = _number(name, spec, raw_value)
    lookup, negate = entry

    return Q(**{f"{spec.field}__{lookup}": value}), negate


def boolean_engine(
    name: str,
    spec: FilterSpec,
    operator: str,
    raw_value: Any,
) -> EngineResult:
    if operator in EMPTY_OPERATORS:
        return _empty(spec), operator == "not_empty"

    if operator in {"is_true", "is_false"}:
        return Q(**{spec.field: operator == "is_true"}), False

    if isinstance(raw_value, bool):
        value = raw_value
    else:
        normalized = str(raw_value).strip().lower()

        if normalized in TRUE_VALUES:
            value = True
        elif normalized in FALSE_VALUES:
            value = False
        else:
            raise _error(
                _("%(column)s must be true or false.") % {"column": name}
            )

    if operator not in {"exact", "not_exact", "equals", "not_equals"}:
        raise _error(
            _("Invalid boolean operator '%(operator)s' for %(column)s.")
            % {"operator": operator, "column": name}
        )

    return Q(**{spec.field: value}), operator in {"not_exact", "not_equals"}


def _date_range(
    spec: FilterSpec,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
) -> Q:
    """Days from ``date_from`` to ``date_to``, both included."""
    is_datetime = spec.value_type == "datetime"
    condition = Q()

    if date_from is not None:
        boundary = _start_of_day(date_from) if is_datetime else date_from
        condition &= Q(**{f"{spec.field}__gte": boundary})

    if date_to is not None:
        boundary = _end_of_day(date_to) if is_datetime else date_to
        condition &= Q(**{f"{spec.field}__lte": boundary})

    return condition


def _date_range_condition(
    name: str,
    spec: FilterSpec,
    operator: str,
    raw_value: Any,
) -> EngineResult:
    """Handle the ``{"from": ..., "to": ...}`` payload shape."""
    if not isinstance(raw_value, dict):
        raise _error(
            _(
                "%(column)s expects an object holding 'from' and/or "
                "'to' dates."
            )
            % {"column": name}
        )

    raw_from = raw_value.get("from")
    raw_to = raw_value.get("to")

    date_from = _parse_date(name, raw_from) if raw_from else None
    date_to = _parse_date(name, raw_to) if raw_to else None

    required = {
        "between": (date_from is not None and date_to is not None),
        "after": date_from is not None,
        "before": date_to is not None,
    }

    if not required[operator]:
        raise _error(
            _("%(column)s is missing a required date bound.")
            % {"column": name}
        )

    if date_from and date_to and date_from > date_to:
        raise _error(
            _("%(column)s: 'from' must not be after 'to'.") % {"column": name}
        )

    return _date_range(spec, date_from, date_to), False


def _add_months(value: datetime.date, months: int) -> datetime.date:
    month = value.month - 1 + months

    return value.replace(year=value.year + month // 12, month=month % 12 + 1)


def relative_period(
    name: str,
    today: datetime.date | None = None,
) -> tuple[datetime.date, datetime.date]:
    """The first and last day of a period named relative to today."""
    today = today or timezone.localdate()
    one_day = datetime.timedelta(days=1)

    if name in {"today", "yesterday", "tomorrow"}:
        offset = {"today": 0, "yesterday": -1, "tomorrow": 1}[name]
        day = today + datetime.timedelta(days=offset)
        return day, day

    step = {"this": 0, "last": -1, "next": 1}[name.split("_")[0]]
    unit = name.split("_")[1]

    if unit == "week":
        start = today - datetime.timedelta(days=today.weekday())
        start += datetime.timedelta(weeks=step)
        return start, start + datetime.timedelta(days=6)

    if unit == "month":
        start = _add_months(today.replace(day=1), step)
        return start, _add_months(start, 1) - one_day

    if unit == "quarter":
        first = today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1)
        start = _add_months(first, 3 * step)
        return start, _add_months(start, 3) - one_day

    start = today.replace(year=today.year + step, month=1, day=1)

    return start, start.replace(month=12, day=31)


def _day_count(name: str, raw_value: Any) -> int:
    try:
        days = int(str(raw_value))
    except (TypeError, ValueError) as error:
        raise _error(
            _("%(column)s needs a number of days.") % {"column": name}
        ) from error

    if not 0 < days <= MAX_DAYS:
        raise _error(
            _("%(column)s needs a number of days.") % {"column": name}
        )

    return days


#: New spelling of the older comparison names, for dates.
DATE_ALIASES = {
    "exact": "on",
    "not_exact": "not_on",
    "greater_than": "after",
    "greater_or_equal": "on_or_after",
    "less_than": "before",
    "less_or_equal": "on_or_before",
    "equals": "on",
    "not_equals": "not_on",
}


def date_engine(
    name: str,
    spec: FilterSpec,
    operator: str,
    raw_value: Any,
) -> EngineResult:
    if operator in EMPTY_OPERATORS:
        return _empty(spec), operator == "not_empty"

    # A range: {"from", "to"}. "after" and "before" with an object are
    # the older, inclusive range forms.
    if isinstance(raw_value, dict) and operator in {
        "between",
        "after",
        "before",
    }:
        return _date_range_condition(name, spec, operator, raw_value)

    if operator == "between":
        low, high = _bounds(raw_value)

        return _date_range_condition(
            name, spec, "between", {"from": low, "to": high}
        )

    if operator in RELATIVE_PERIODS:
        return _date_range(spec, *relative_period(operator)), False

    if operator in DAY_OPERATORS:
        days = _day_count(name, raw_value)
        today = timezone.localdate()

        if operator == "last_days":
            start = today - datetime.timedelta(days=days - 1)
            return _date_range(spec, start, today), False

        if operator == "next_days":
            end = today + datetime.timedelta(days=days - 1)
            return _date_range(spec, today, end), False

        # Older than N days: before the start of that day.
        limit = today - datetime.timedelta(days=days)
        is_datetime = spec.value_type == "datetime"
        boundary = _start_of_day(limit) if is_datetime else limit

        return Q(**{f"{spec.field}__lt": boundary}), False

    operator = DATE_ALIASES.get(operator, operator)
    value = _parse_date(name, raw_value)
    is_datetime = spec.value_type == "datetime"

    if operator in {"on", "not_on"}:
        # ``__date`` only exists on datetimes; a plain date compares
        # directly.
        lookup = f"{spec.field}__date" if is_datetime else spec.field

        return Q(**{lookup: value}), operator == "not_on"

    if is_datetime:
        # Comparing a day against a timestamp means comparing against
        # the right edge of that day.
        boundaries = {
            "after": ("gt", _end_of_day(value)),
            "on_or_after": ("gte", _start_of_day(value)),
            "before": ("lt", _start_of_day(value)),
            "on_or_before": ("lte", _end_of_day(value)),
        }
    else:
        boundaries = {
            "after": ("gt", value),
            "on_or_after": ("gte", value),
            "before": ("lt", value),
            "on_or_before": ("lte", value),
        }

    entry = boundaries.get(operator)

    if entry is None:
        raise _error(
            _("Invalid date operator '%(operator)s' for %(column)s.")
            % {"operator": operator, "column": name}
        )

    lookup, boundary = entry

    return Q(**{f"{spec.field}__{lookup}": boundary}), False


#: New spelling of the older multiple choice names.
MULTISELECT_ALIASES = {"include": "any_of", "exclude": "none_of"}


def _choice_values(name: str, spec: FilterSpec, raw_value: Any) -> list[Any]:
    if not isinstance(raw_value, list):
        raise _error(
            _("%(column)s must hold a list of values.") % {"column": name}
        )

    if len(raw_value) > MAX_MULTISELECT_VALUES:
        raise _error(_("%(column)s holds too many values.") % {"column": name})

    try:
        if spec.value_type == "integer":
            values: list[Any] = [int(value) for value in raw_value]
        else:
            values = [str(value) for value in raw_value]
    except (TypeError, ValueError) as error:
        raise _error(
            _("%(column)s holds an invalid value.") % {"column": name}
        ) from error

    # Preserve order while dropping duplicates.
    return list(dict.fromkeys(values))


def multiselect_engine(
    name: str,
    spec: FilterSpec,
    operator: str,
    raw_value: Any,
) -> EngineResult:
    if operator in EMPTY_OPERATORS:
        return _empty(spec), operator == "not_empty"

    operator = MULTISELECT_ALIASES.get(operator, operator)

    if operator not in {"any_of", "none_of", "all_of"}:
        raise _error(
            _(
                "Invalid multiple choice operator '%(operator)s' for "
                "%(column)s."
            )
            % {"operator": operator, "column": name}
        )

    values = _choice_values(name, spec, raw_value)

    if operator == "all_of":
        return _all(Q(**{spec.field: value}) for value in values), False

    return Q(**{f"{spec.field}__in": values}), operator == "none_of"


ENGINES: dict[str, Engine] = {
    FILTER_TEXT: text_engine,
    FILTER_INTEGER: numeric_engine,
    FILTER_FLOAT: numeric_engine,
    FILTER_BOOLEAN: boolean_engine,
    FILTER_DATE: date_engine,
    FILTER_DATETIME: date_engine,
    FILTER_MULTISELECT: multiselect_engine,
}


# ---------------------------------------------------------------------
# Filter trees
# ---------------------------------------------------------------------


def legacy_to_tree(filters: dict[str, Any]) -> dict[str, Any]:
    """The flat ``advanced_filters`` payload, as a tree requiring all."""
    return {
        "match": MATCH_ALL,
        "conditions": [
            (
                {"column": name, **condition}
                if isinstance(condition, dict)
                else {"column": name, "invalid": True}
            )
            for name, condition in filters.items()
        ],
    }


def is_empty_tree(tree: Any) -> bool:
    return not (isinstance(tree, dict) and tree.get("conditions"))


class FilterTreeBuilder:
    """Turn a filter tree into one ``Q``, through the whitelist.

    ``exclude_column`` leaves out the conditions on one column: the
    facets of a column count what choosing among its values would give,
    under every *other* condition.
    """

    def __init__(
        self,
        specs: dict[str, FilterSpec],
        model: Any,
        exclude_column: str | None = None,
    ) -> None:
        self.specs = specs
        self.model = model
        self.exclude_column = exclude_column
        self.count = 0

    def build(self, tree: Any) -> Q | None:
        return self.node(tree, depth=0)

    def node(self, node: Any, depth: int) -> Q | None:
        if not isinstance(node, dict):
            raise _error(_("A filter must be a JSON object."))

        if "column" in node or node.get("invalid"):
            return self.condition(node)

        if depth >= MAX_DEPTH:
            raise _error(_("Filter groups are nested too deeply."))

        match = node.get("match", MATCH_ALL)

        if match not in {MATCH_ALL, MATCH_ANY}:
            raise _error(_("A group matches 'all' or 'any' of its filters."))

        children = node.get("conditions", [])

        if not isinstance(children, list):
            raise _error(_("A group holds a list of conditions."))

        parts = [
            part
            for part in (self.node(child, depth + 1) for child in children)
            if part is not None
        ]

        if not parts:
            return None

        return _all(parts) if match == MATCH_ALL else _any(parts)

    def condition(self, node: dict[str, Any]) -> Q | None:
        self.count += 1

        if self.count > MAX_FILTERS:
            raise _error(_("Too many filters requested."))

        name = str(node.get("column") or "")

        if node.get("invalid"):
            raise _error(
                _("Invalid filter condition for %(column)s.")
                % {"column": name}
            )

        spec = self.specs.get(name)

        if spec is None:
            raise _error(
                _("Filtering is not allowed on %(column)s.") % {"column": name}
            )

        if self.exclude_column is not None and name == self.exclude_column:
            return None

        operator = str(node.get("operator") or "")
        value = node.get("value")

        # An empty control means "no filter", not "match empty".
        if operator not in VALUELESS_OPERATORS and value in (None, "", []):
            return None

        engine = ENGINES.get(spec.type)

        if engine is None:
            raise _error(
                _("Unsupported filter type for %(column)s.") % {"column": name}
            )

        # "Has all of" across a many-valued relation: one subquery per
        # value, since a single joined row holds only one of them.
        if (
            spec.many
            and spec.type == FILTER_MULTISELECT
            and operator == "all_of"
        ):
            values = _choice_values(name, spec, value)

            return _all(
                self.through(Q(**{spec.field: item})) for item in values
            )

        predicate, negate = engine(name, spec, operator, value)

        if spec.many:
            # Across a many-valued relation a direct filter repeats the
            # row once per match. The subquery keeps it once, and makes a
            # negation mean "has none of these" as users expect.
            predicate = self.through(predicate)

        return ~predicate if negate else predicate

    def through(self, predicate: Q) -> Q:
        return Q(
            pk__in=self.model._default_manager.filter(predicate).values("pk")
        )


def _messages(error: ValidationError) -> Any:
    detail = error.detail

    if isinstance(detail, dict):
        return detail.get(FILTERS_PARAM, list(detail.values()))

    return detail


def parse_json_payload(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise _error(_("Invalid JSON filter payload.")) from error


# ---------------------------------------------------------------------
# Filter backends
# ---------------------------------------------------------------------


class SerializerColumnsMixin:
    """Read the column declaration off the view's serializer."""

    @staticmethod
    def get_table_serializer(view: Any) -> Any:
        serializer_class = getattr(view, "serializer_class", None)

        if serializer_class is None and hasattr(view, "get_serializer_class"):
            serializer_class = view.get_serializer_class()

        return serializer_class


class AdvancedFilterBackend(SerializerColumnsMixin, BaseFilterBackend):
    """Apply the conditions sent by the client.

    ``filters`` holds a tree - see the module documentation. The older
    ``advanced_filters`` holds one condition per column::

        {
            "utilisateur": {"operator": "not_contains", "value": "Martin"},
            "temps_passe": {"operator": "greater_or_equal", "value": "8"}
        }

    Both may be sent; every condition of both must then hold.
    """

    #: Builds the ``Q`` of a tree. Rows that are not in the database use
    #: one that stays out of subqueries (``generic.api.rows``).
    builder_class: type[FilterTreeBuilder] = FilterTreeBuilder

    def filter_queryset(
        self,
        request: Any,
        queryset: QuerySet,
        view: Any,
    ) -> QuerySet:
        for condition in self.get_conditions(request, view, queryset.model):
            queryset = queryset.filter(condition)

        return queryset

    def get_conditions(
        self,
        request: Any,
        view: Any,
        model: Any,
    ) -> list[Q]:
        """What the request asks for, as ``Q`` objects every row must
        match: one for the older payload, one for the tree."""
        raw_legacy = request.query_params.get(ADVANCED_FILTERS_PARAM)
        raw_tree = request.query_params.get(FILTERS_PARAM)

        if not (raw_legacy or raw_tree):
            return []

        builder = self.builder_class(
            self.get_filter_specs(view),
            model,
            exclude_column=getattr(view, "facet_column", None),
        )
        conditions: list[Q | None] = []

        if raw_legacy:
            try:
                conditions.append(
                    builder.build(
                        legacy_to_tree(self.parse_payload(raw_legacy))
                    )
                )
            except ValidationError as error:
                # The error names the parameter the client sent.
                raise ValidationError(
                    {ADVANCED_FILTERS_PARAM: _messages(error)}
                ) from error

        if raw_tree:
            conditions.append(builder.build(self.parse_tree(raw_tree)))

        return [condition for condition in conditions if condition is not None]

    def get_filter_specs(self, view: Any) -> dict[str, FilterSpec]:
        if hasattr(view, "get_filter_specs"):
            return view.get_filter_specs()

        serializer_class = self.get_table_serializer(view)

        if serializer_class is None or not hasattr(
            serializer_class, "get_filter_specs"
        ):
            return {}

        return serializer_class.get_filter_specs()

    def parse_payload(self, raw_filters: str) -> dict[str, Any]:
        filters = parse_json_payload(raw_filters)

        if not isinstance(filters, dict):
            raise _error(_("A JSON object is expected."))

        if len(filters) > MAX_FILTERS:
            raise _error(_("Too many filters requested."))

        return filters

    def parse_tree(self, raw_tree: str) -> dict[str, Any]:
        tree = parse_json_payload(raw_tree)

        if not isinstance(tree, dict):
            raise _error(_("A JSON object is expected."))

        return tree

    def apply_condition(
        self,
        queryset: QuerySet,
        *,
        name: str,
        condition: Any,
        specs: dict[str, FilterSpec],
    ) -> QuerySet:
        """Apply one condition of the flat payload. Kept for callers of
        the previous backend."""
        builder = FilterTreeBuilder(specs, queryset.model)
        predicate = builder.build(legacy_to_tree({name: condition}))

        return queryset if predicate is None else queryset.filter(predicate)


class DataTablesSearchBackend(
    SerializerColumnsMixin,
    BaseFilterBackend,
):
    """Global search box, spanning every searchable text column.

    Several words must all match, ``!word`` or ``-word`` excludes, and a
    "quoted phrase" stays whole; see :func:`split_search_terms`.
    """

    search_param = "search[value]"
    fallback_search_param = "search"

    def filter_queryset(
        self,
        request: Any,
        queryset: QuerySet,
        view: Any,
    ) -> QuerySet:
        term = (
            request.query_params.get(self.search_param)
            or request.query_params.get(self.fallback_search_param)
            or ""
        ).strip()

        if not term:
            return queryset

        return apply_search(queryset, self.get_search_fields(view), term)

    def get_search_fields(self, view: Any) -> list[str]:
        if hasattr(view, "get_table_search_fields"):
            return view.get_table_search_fields()

        serializer_class = self.get_table_serializer(view)

        if serializer_class is None or not hasattr(
            serializer_class, "get_search_fields"
        ):
            return []

        return serializer_class.get_search_fields()


class DataTablesOrderingBackend(
    SerializerColumnsMixin,
    BaseFilterBackend,
):
    """Ordering, resolved through the orderable whitelist.

    DataTables sends ``order[i][column]`` as an index into the columns it
    echoed back in ``columns[j][data]``. The index is resolved against
    that echo, then the resulting public name is validated against the
    serializer, so reordering or hiding columns client side stays safe.

    A plain ``ordering=-name,other`` parameter is also accepted, which
    keeps the endpoint usable outside DataTables.
    """

    ordering_param = "ordering"
    max_ordering_fields = 5

    def filter_queryset(
        self,
        request: Any,
        queryset: QuerySet,
        view: Any,
    ) -> QuerySet:
        allowed = self.get_ordering_fields(view)

        if not allowed:
            return queryset

        ordering = self.get_ordering(request, allowed)

        if not ordering:
            return queryset

        return queryset.order_by(*ordering)

    def get_ordering_fields(self, view: Any) -> dict[str, str]:
        if hasattr(view, "get_table_ordering_fields"):
            return view.get_table_ordering_fields()

        serializer_class = self.get_table_serializer(view)

        if serializer_class is None or not hasattr(
            serializer_class, "get_ordering_fields"
        ):
            return {}

        return serializer_class.get_ordering_fields()

    def get_ordering(
        self,
        request: Any,
        allowed: dict[str, str],
    ) -> list[str]:
        datatables_ordering = self.get_datatables_ordering(
            request,
            allowed,
        )

        if datatables_ordering:
            return datatables_ordering

        return self.get_plain_ordering(request, allowed)

    def get_datatables_ordering(
        self,
        request: Any,
        allowed: dict[str, str],
    ) -> list[str]:
        params = request.query_params
        ordering: list[str] = []

        for index in range(self.max_ordering_fields):
            raw_column = params.get(f"order[{index}][column]")

            if raw_column is None:
                break

            try:
                column_index = int(raw_column)
            except (TypeError, ValueError):
                raise _error(_("Invalid ordering column index.")) from None

            name = params.get(f"columns[{column_index}][data]")

            if not name:
                continue

            field = allowed.get(name)

            if field is None:
                # A column the client may display but not order on.
                continue

            descending = (
                params.get(f"order[{index}][dir]", "asc").lower() == "desc"
            )
            ordering.append(f"-{field}" if descending else field)

        return ordering

    def get_plain_ordering(
        self,
        request: Any,
        allowed: dict[str, str],
    ) -> list[str]:
        raw_ordering = request.query_params.get(self.ordering_param)

        if not raw_ordering:
            return []

        ordering: list[str] = []

        for item in raw_ordering.split(",")[: self.max_ordering_fields]:
            item = item.strip()

            if not item:
                continue

            descending = item.startswith("-")
            name = item.lstrip("-")
            field = allowed.get(name)

            if field is None:
                raise _error(
                    _("Ordering is not allowed on %(column)s.")
                    % {"column": name}
                )

            ordering.append(f"-{field}" if descending else field)

        return ordering


#: Backends every data table endpoint installs, in order.
DATATABLE_FILTER_BACKENDS = (
    AdvancedFilterBackend,
    DataTablesSearchBackend,
    DataTablesOrderingBackend,
)

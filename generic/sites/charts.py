"""Charts of a resource's records, computed by the database.

A chart is declared on the resource, like its columns, and served by
the resource's endpoint - so it answers to the same permissions, the
same table filters and the same ``_related`` narrowing as the table::

    class TicketResource(ModelResource):
        charts = (
            Chart("by_status", title=_("By status"), type="donut",
                  group_by="status"),
            Chart("opened", title=_("Opened"), type="line",
                  group_by="opened_at", period="week",
                  periods=("day", "week", "month")),
            Chart("workload", title=_("Open work by team"),
                  group_by="team", split_by="priority", stacked=True),
            Chart("hours", title=_("Hours by agent"), horizontal=True,
                  group_by="time_entries__agent",
                  value=Sum("time_entries__hours"),
                  value_label=_("Hours"), unit="h"),
        )
        # Above the list, following its filters.
        list_charts = ("by_status", "opened")

``GET api/<app>/<model>/charts/<name>/`` returns the data, in a shape
that names no charting library::

    {"type": "bar", "categories": ["Front office", "Infrastructure"],
     "keys": [1, 2], "series": [{"name": "Tickets", "data": [12, 7]}],
     "value": {"label": "Tickets", "format": "integer"}, ...}

and ``generic/js/charts.js`` draws it with Apache ECharts.

Anything the declarative form cannot say, ``data`` computes: a callable
``(chart, request, queryset, period)`` returning at least
``categories`` and ``series``.
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import uuid
from typing import Any, Callable, Mapping, Sequence

from django.contrib.admin.utils import get_fields_from_path
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Count
from django.db.models.functions import Trunc
from django.utils import formats
from django.utils.encoding import force_str
from django.utils.text import capfirst
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from generic.api.tags import TagStyle, clean_color, json_key

#: What the declarative form draws. ``data`` may return any other type
#: the client knows, and ``options`` any ECharts setting.
CHART_TYPES = frozenset(
    {"bar", "line", "area", "pie", "donut", "funnel", "heatmap"}
)

#: How a date dimension is bucketed.
PERIODS = ("day", "week", "month", "quarter", "year")

PERIOD_LABELS = {
    "day": _("Day"),
    "week": _("Week"),
    "month": _("Month"),
    "quarter": _("Quarter"),
    "year": _("Year"),
}

#: Buckets a date dimension may be filled out to, at most.
MAX_BUCKETS = 1000

#: Key of the bucket gathering what ``limit`` leaves out.
OTHER_KEY = "__other__"

VALUE_FORMATS = frozenset({"integer", "decimal", "percent"})


# ---------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------


def period_start(value: datetime.date, period: str) -> datetime.date:
    if isinstance(value, datetime.datetime):
        value = value.date()

    if period == "week":
        return value - datetime.timedelta(days=value.weekday())

    if period == "month":
        return value.replace(day=1)

    if period == "quarter":
        return value.replace(month=(value.month - 1) // 3 * 3 + 1, day=1)

    if period == "year":
        return value.replace(month=1, day=1)

    return value


def next_period(value: datetime.date, period: str) -> datetime.date:
    if period == "day":
        return value + datetime.timedelta(days=1)

    if period == "week":
        return value + datetime.timedelta(days=7)

    months = {"month": 1, "quarter": 3, "year": 12}[period]
    month = value.month - 1 + months

    return value.replace(year=value.year + month // 12, month=month % 12 + 1)


def period_label(value: datetime.date, period: str) -> str:
    if period == "year":
        return str(value.year)

    if period == "quarter":
        return gettext("Q%(quarter)s %(year)s") % {
            "quarter": (value.month - 1) // 3 + 1,
            "year": value.year,
        }

    if period == "month":
        return formats.date_format(value, "YEAR_MONTH_FORMAT")

    return formats.date_format(value, "SHORT_DATE_FORMAT")


# ---------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------


@dataclasses.dataclass
class Dimension:
    """One axis of a chart: what the records are grouped by."""

    #: The declared path, also the table column it filters.
    name: str
    #: ``relation``, ``choice``, ``boolean``, ``date`` or ``value``.
    kind: str
    #: The key ``values()`` reads.
    lookup: str
    #: An annotation computing that key, for a date bucket.
    expression: Any = None
    field: Any = None
    period: str = ""
    #: The model a relation's keys belong to.
    related_model: Any = None

    def labels(self, keys: Sequence[Any], site: Any) -> dict[Any, str]:
        """The label of each key."""
        labels: dict[Any, str] = {}
        present = [key for key in keys if key is not None]

        if self.kind == "relation":
            resource = site.get_resource(self.related_model)
            records = self.records(present)

            for key in present:
                record = records.get(key)

                if record is None:
                    labels[key] = force_str(key)
                elif resource is not None:
                    labels[key] = resource.get_object_label(record)
                else:
                    labels[key] = force_str(record)
        elif self.kind == "choice":
            choices = dict(self.field.flatchoices)

            for key in present:
                labels[key] = force_str(choices.get(key, key))
        elif self.kind == "boolean":
            # "Billable: Yes" says more than "Yes" in a legend.
            name = capfirst(force_str(self.field.verbose_name))

            for key in present:
                labels[key] = gettext("%(name)s: %(value)s") % {
                    "name": name,
                    "value": gettext("Yes") if key else gettext("No"),
                }
        elif self.kind == "date":
            for key in present:
                labels[key] = period_label(key, self.period)
        else:
            for key in present:
                labels[key] = force_str(key)

        if None in keys:
            labels[None] = gettext("None")

        return labels

    def records(self, keys: Sequence[Any]) -> dict[Any, Any]:
        if self.kind != "relation" or not keys:
            return {}

        return self.related_model._default_manager.in_bulk(list(keys))

    def natural_order(self, keys: Sequence[Any]) -> list[Any] | None:
        """Keys in the dimension's own order, or None when it has none."""
        present = [key for key in keys if key is not None]

        if self.kind == "date":
            ordered = sorted(present)
        elif self.kind == "choice":
            position = {
                value: index
                for index, (value, _label) in enumerate(self.field.flatchoices)
            }
            ordered = sorted(
                present, key=lambda key: position.get(key, len(position))
            )
        elif self.kind == "boolean":
            ordered = sorted(present, reverse=True)
        else:
            return None

        return ordered + ([None] if None in keys else [])

    def describe(self) -> dict[str, Any]:
        described = {"name": self.name, "kind": self.kind}

        if self.period:
            described["period"] = self.period

        return described


def resolve_dimension(
    model: Any,
    path: str,
    period: str,
    alias: str,
) -> Dimension:
    """What grouping ``model`` rows by ``path`` means."""
    try:
        fields = get_fields_from_path(model, path)
    except Exception as error:
        raise ImproperlyConfigured(
            f"A chart groups {model.__name__} by '{path}', which is not a "
            f"field path of that model."
        ) from error

    field = fields[-1]

    if field.is_relation:
        return Dimension(
            name=path,
            kind="relation",
            lookup=path,
            field=field,
            related_model=field.related_model,
        )

    if getattr(field, "choices", None):
        return Dimension(name=path, kind="choice", lookup=path, field=field)

    if isinstance(field, models.BooleanField):
        return Dimension(name=path, kind="boolean", lookup=path, field=field)

    if isinstance(field, models.DateField):
        return Dimension(
            name=path,
            kind="date",
            lookup=alias,
            expression=Trunc(path, period, output_field=models.DateField()),
            field=field,
            period=period,
        )

    return Dimension(name=path, kind="value", lookup=path, field=field)


# ---------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------


def plain_number(value: Any) -> int | float:
    if value is None:
        return 0

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    if isinstance(value, decimal.Decimal) and value == value.to_integral():
        return int(value)

    return float(value)


@dataclasses.dataclass(frozen=True)
class Chart:
    """A chart of a resource's records."""

    #: Identifies the chart in its resource's URL.
    name: str
    title: Any = None
    description: Any = ""
    icon: str = ""
    #: bar, line, area, pie, donut, funnel or heatmap.
    type: str = "bar"

    #: The categories: a field path - a relation, a choice, a boolean,
    #: a date (bucketed by ``period``) or any plain value.
    group_by: str | None = None
    #: A second dimension: one series per value, or the rows of a
    #: heatmap.
    split_by: str | None = None
    #: The aggregate each bucket shows. Counts the records by default.
    value: Any = None
    value_label: Any = None
    #: integer, decimal or percent. Worked out from the values when
    #: left out.
    value_format: str | None = None
    unit: str = ""
    decimals: int | None = None

    #: The bucket of a date dimension, and the ones the user may switch
    #: to.
    period: str = "month"
    periods: Sequence[str] | None = None

    stacked: bool | None = None
    horizontal: bool = False
    #: Keep the largest categories, gathering the rest under "Other".
    limit: int | None = None
    #: "value", "-value" or "label". Dates, choices and booleans keep
    #: their own order by default; anything else is largest first.
    order: str | None = None
    #: Colours by key, the name of a colour attribute of the related
    #: records, or a TagStyle. Defaults to the resource's tag_fields.
    colors: Any = None
    #: Height of the drawing, as CSS.
    height: str = "18rem"
    #: ECharts settings merged over the generated ones.
    options: Mapping[str, Any] | None = None
    #: A permission string, or ``callable(request)``, on top of the
    #: resource's view permission.
    permission: Any = None
    #: Computes the data instead: ``(chart, request, queryset, period)``
    #: returning ``{"categories": [...], "series": [...], ...}``.
    data: Callable[..., Mapping[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.data is None and not self.group_by:
            raise ImproperlyConfigured(
                f"Chart '{self.name}' needs a group_by, or a data callable."
            )

        if self.data is None and self.type not in CHART_TYPES:
            raise ImproperlyConfigured(
                f"Chart '{self.name}': unknown type '{self.type}'. Known "
                f"types: {', '.join(sorted(CHART_TYPES))}."
            )

        for period in self.get_periods():
            if period not in PERIODS:
                raise ImproperlyConfigured(
                    f"Chart '{self.name}': unknown period '{period}'."
                )

        if self.value_format and self.value_format not in VALUE_FORMATS:
            raise ImproperlyConfigured(
                f"Chart '{self.name}': unknown value_format "
                f"'{self.value_format}'."
            )

    # -- identity -------------------------------------------------------

    def get_title(self, resource: Any) -> str:
        if self.title:
            return force_str(self.title)

        return self.name.replace("_", " ").capitalize()

    def get_periods(self) -> tuple[str, ...]:
        return tuple(self.periods or (self.period,))

    def is_visible(self, request: Any, resource: Any) -> bool:
        if not resource.has_view_permission(request):
            return False

        if self.permission is None:
            return True

        if callable(self.permission):
            return bool(self.permission(request))

        user = getattr(request, "user", None)

        return bool(user and user.has_perm(self.permission))

    def get_config(
        self,
        resource: Any,
        request: Any,
        **overrides: Any,
    ) -> dict[str, Any]:
        """What the page hands the browser to draw this chart."""
        periods = self.get_periods()
        config = {
            "name": self.name,
            "title": self.get_title(resource),
            "description": force_str(self.description),
            "icon": self.icon,
            "type": self.type,
            "url": resource.get_chart_url(self.name),
            "height": self.height,
            "period": self.period if self.period in periods else periods[0],
            "periods": (
                [
                    {
                        "value": period,
                        "label": force_str(PERIOD_LABELS[period]),
                    }
                    for period in periods
                ]
                if len(periods) > 1 and self.uses_periods(resource)
                else []
            ),
            "model": resource.label_lower,
            "topic": resource.topic_name if resource.realtime else "",
            "extraParams": {},
            "table": "",
        }
        config.update(
            {key: value for key, value in overrides.items() if value}
        )

        return config

    def uses_periods(self, resource: Any) -> bool:
        """Whether a period switch means anything for this chart."""
        if self.data is not None:
            return True

        for path in (self.group_by, self.split_by):
            if not path:
                continue

            try:
                field = get_fields_from_path(resource.model, path)[-1]
            except Exception:
                continue

            if isinstance(field, models.DateField) and not field.is_relation:
                return True

        return False

    # -- data -------------------------------------------------------------

    def get_payload(
        self,
        resource: Any,
        request: Any,
        queryset: Any,
        period: str | None = None,
    ) -> dict[str, Any]:
        """The chart, as the endpoint returns it."""
        period = period or self.period

        payload: dict[str, Any] = {
            "name": self.name,
            "title": self.get_title(resource),
            "type": self.type,
            "stacked": bool(self.stacked),
            "horizontal": self.horizontal,
            "period": period,
            "options": dict(self.options or {}),
        }

        if self.data is not None:
            computed = dict(self.data(self, request, queryset, period) or {})
            payload.update(computed)
            payload.setdefault("categories", [])
            payload.setdefault("series", [])
            payload.setdefault("value", self.describe_value(resource, None))
        else:
            payload.update(self.compute(resource, queryset, period))

        payload["empty"] = not any(
            any(plain_number(value) for value in series_values(entry))
            for entry in payload["series"]
        )

        return payload

    def compute(
        self,
        resource: Any,
        queryset: Any,
        period: str,
    ) -> dict[str, Any]:
        model = resource.model
        site = resource.site
        group = resolve_dimension(model, self.group_by, period, "_chart_x")
        split = (
            resolve_dimension(model, self.split_by, period, "_chart_y")
            if self.split_by
            else None
        )

        value = (
            self.value
            if self.value is not None
            else (Count("pk", distinct=True))
        )
        annotations = {
            dimension.lookup: dimension.expression
            for dimension in (group, split)
            if dimension is not None and dimension.expression is not None
        }
        lookups = [group.lookup] + ([split.lookup] if split else [])

        rows = queryset.order_by()

        if annotations:
            rows = rows.annotate(**annotations)

        rows = rows.values(*lookups).annotate(_chart_value=value)

        # (category key, series key) -> value
        cells: dict[tuple[Any, Any], Any] = {}
        raw_values = []

        for row in rows:
            x = normalize_key(row[group.lookup])
            y = normalize_key(row[split.lookup]) if split else None
            number = row["_chart_value"]
            raw_values.append(number)
            cells[(x, y)] = cells.get((x, y), 0) + plain_number(number)

        category_keys = list(dict.fromkeys(x for x, _y in cells))
        series_keys = (
            list(dict.fromkeys(y for _x, y in cells)) if split else [None]
        )

        if group.kind == "date":
            category_keys = fill_periods(category_keys, period)

        totals = {
            key: sum(cells.get((key, y), 0) for y in series_keys)
            for key in category_keys
        }
        category_keys = self.ordered(group, category_keys, totals)
        category_keys, cells = self.limited(
            group, category_keys, series_keys, cells, totals
        )

        if split is not None:
            series_totals = {
                y: sum(cells.get((x, y), 0) for x in category_keys)
                for y in series_keys
            }
            series_keys = split.natural_order(series_keys) or sorted(
                series_keys,
                key=lambda key: (key is None, -series_totals[key]),
            )

        category_labels = group.labels(
            [key for key in category_keys if key != OTHER_KEY], site
        )
        category_labels[OTHER_KEY] = gettext("Other")
        value_description = self.describe_value(resource, raw_values)

        series = []

        if split is None:
            series.append(
                {
                    "name": value_description["label"],
                    "key": None,
                    "data": [cells.get((x, None), 0) for x in category_keys],
                }
            )
        else:
            series_labels = split.labels(series_keys, site)
            colors = self.colors_for(resource, split, series_keys)

            for y in series_keys:
                entry = {
                    "name": series_labels.get(y, force_str(y)),
                    "key": json_key(y),
                    "data": [cells.get((x, y), 0) for x in category_keys],
                }

                if colors.get(y):
                    entry["color"] = colors[y]

                series.append(entry)

        payload: dict[str, Any] = {
            "dimension": group.describe(),
            "split": split.describe() if split else None,
            "categories": [category_labels[key] for key in category_keys],
            "keys": [
                (
                    json_key(key)
                    if not isinstance(key, datetime.date)
                    else key.isoformat()
                )
                for key in category_keys
            ],
            "series": series,
            "value": value_description,
            "total": sum(sum(entry["data"]) for entry in series),
        }

        if group.kind == "date":
            payload["ranges"] = [
                {
                    "from": key.isoformat(),
                    "to": (
                        next_period(key, period) - datetime.timedelta(days=1)
                    ).isoformat(),
                }
                for key in category_keys
            ]

        if split is None:
            colors = self.colors_for(resource, group, category_keys)

            if any(colors.values()):
                payload["colors"] = [colors.get(key) for key in category_keys]

        return payload

    def ordered(
        self,
        dimension: Dimension,
        keys: list[Any],
        totals: Mapping[Any, Any],
    ) -> list[Any]:
        order = self.order
        natural = dimension.natural_order(keys)

        if order is None and natural is not None:
            return natural

        present = [key for key in keys if key is not None]

        if order == "label":
            if dimension.kind == "relation":
                records = dimension.records(present)
                labels = {
                    key: force_str(records.get(key, key)) for key in present
                }
            else:
                labels = dimension.labels(present, None)

            present.sort(key=lambda key: labels[key].lower())
        elif order == "value":
            present.sort(key=lambda key: totals.get(key, 0))
        else:
            present.sort(key=lambda key: -totals.get(key, 0))

        return present + ([None] if None in keys else [])

    def limited(
        self,
        dimension: Dimension,
        keys: list[Any],
        series_keys: list[Any],
        cells: dict[tuple[Any, Any], Any],
        totals: Mapping[Any, Any],
    ) -> tuple[list[Any], dict[tuple[Any, Any], Any]]:
        """The ``limit`` largest categories, the rest gathered."""
        if not self.limit or dimension.kind == "date":
            return keys, cells

        if len(keys) <= self.limit:
            return keys, cells

        largest = sorted(keys, key=lambda key: -totals.get(key, 0))
        kept = set(largest[: self.limit])
        cells = dict(cells)

        for key in keys:
            if key in kept:
                continue

            for y in series_keys:
                value = cells.pop((key, y), 0)
                cells[(OTHER_KEY, y)] = cells.get((OTHER_KEY, y), 0) + value

        return [key for key in keys if key in kept] + [OTHER_KEY], cells

    def colors_for(
        self,
        resource: Any,
        dimension: Dimension,
        keys: Sequence[Any],
    ) -> dict[Any, str | None]:
        """A colour per key, from ``colors`` or the resource's tags."""
        colors = self.colors

        if colors is None:
            colors = resource.get_tag_style(dimension.name)

        if colors is None:
            return {}

        present = [key for key in keys if key not in (None, OTHER_KEY)]
        records = (
            dimension.records(present)
            if isinstance(colors, (str, TagStyle))
            else {}
        )
        result: dict[Any, str | None] = {}

        for key in present:
            record = records.get(key)
            color: Any = None

            if isinstance(colors, TagStyle):
                tag = colors.describe(record if record is not None else key)
                color = tag and (tag.get("background") or tag.get("color"))
            elif isinstance(colors, str):
                color = getattr(record, colors, None) if record else None
            elif isinstance(colors, Mapping):
                color = colors.get(key, colors.get(force_str(key)))

                if isinstance(color, Mapping):
                    color = color.get("background") or color.get("color")

            result[key] = clean_color(color)

        return result

    def describe_value(
        self,
        resource: Any,
        values: Sequence[Any] | None,
    ) -> dict[str, Any]:
        value_format = self.value_format

        if value_format is None:
            numbers = [value for value in values or () if value is not None]
            whole = all(
                isinstance(value, int)
                or (
                    isinstance(value, decimal.Decimal)
                    and value == value.to_integral()
                    and self.value is None
                )
                for value in numbers
            )
            value_format = "integer" if whole else "decimal"

        decimals = self.decimals

        if decimals is None:
            decimals = 0 if value_format == "integer" else 2

        label = self.value_label

        if label is None:
            # A count counts the resource's records: "Tickets".
            label = (
                resource.get_label_plural()
                if self.value is None
                else self.name.replace("_", " ").capitalize()
            )

        return {
            "label": force_str(label),
            "format": value_format,
            "unit": force_str(self.unit),
            "decimals": decimals,
        }


def normalize_key(value: Any) -> Any:
    if isinstance(value, datetime.datetime):
        return value.date()

    return value


def series_values(entry: Any) -> list[Any]:
    """The plain numbers of a series, whatever shape its data takes."""
    values = []

    for item in (
        (entry or {}).get("data", ()) if isinstance(entry, Mapping) else ()
    ):
        if isinstance(item, Mapping):
            item = item.get("value")

        if isinstance(item, (list, tuple)):
            item = item[-1] if item else 0

        if isinstance(item, (int, float, decimal.Decimal)):
            values.append(item)

    return values


def fill_periods(keys: list[Any], period: str) -> list[Any]:
    """Every bucket between the first and the last, empty ones too."""
    dates = sorted(key for key in keys if isinstance(key, datetime.date))

    if not dates:
        return keys

    filled = []
    current = period_start(dates[0], period)
    last = dates[-1]

    while current <= last and len(filled) < MAX_BUCKETS:
        filled.append(current)
        current = next_period(current, period)

    return filled + ([None] if None in keys else [])


def chart_entries(configs: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Chart configurations, each with an id for its JSON script."""
    return [
        {"config_id": f"chart-{uuid.uuid4().hex[:12]}", "config": config}
        for config in configs
    ]


def chart_payload(
    *,
    categories: Sequence[Any],
    series: Sequence[Mapping[str, Any]],
    type: str = "bar",
    **extra: Any,
) -> dict[str, Any]:
    """A chart payload for any DRF view, in the shape charts.js draws.

    ::

        return Response(chart_payload(
            type="bar",
            categories=["Mon", "Tue"],
            series=[{"name": "Hours", "data": [7.5, 6]},
                    {"name": "Capacity", "type": "line", "data": [8, 8]}],
            value={"label": "Hours", "format": "decimal", "unit": "h"},
        ))
    """
    payload: dict[str, Any] = {
        "type": type,
        "categories": [force_str(category) for category in categories],
        "series": [
            {
                **entry,
                "data": [
                    (
                        plain_number(value)
                        if isinstance(value, (int, float, decimal.Decimal))
                        or value is None
                        else value
                    )
                    for value in entry.get("data", ())
                ],
            }
            for entry in series
        ],
        "stacked": False,
        "horizontal": False,
        "options": {},
        "value": {"label": "", "format": "decimal", "unit": "", "decimals": 2},
    }
    payload.update(extra)
    payload["empty"] = not any(
        any(plain_number(value) for value in series_values(entry))
        for entry in payload["series"]
    )

    return payload

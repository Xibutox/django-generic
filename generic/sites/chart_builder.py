"""A chart above the list that its reader draws: what it groups the
rows by, what it measures, which form it takes.

``charts`` and ``list_charts`` are the charts a project decided on.
This is the other half: a *Chart* button in the table's toolbar opens a
panel above the list - closed until someone opens it - where the reader
picks the form (bars, lines, a donut...), a field to group by, another
to split by, and a count or the sum or average of a number::

    class EquipmentResource(ModelResource):
        chart_builder = True                       # fields worked out
        chart_builder = ("state", "supplier")      # these, grouped by
        chart_builder = ChartBuilder(
            group_by=("state", "kind", "supplier", "purchased_on"),
            values=("price",),
            types=("bar", "line", "donut"),
        )

``auto(...)`` resources have it already; ``chart_builder = False``
takes it away.

What it has to get right:

* **The request never names a field path.** It names one of the
  dimensions and values offered here, by key; everything else is a 400.
  The fields are the declaration's, worked out from the model when it
  says ``True``: no secret, nothing excluded.
* **It is a chart like the others.** The selection becomes a ``Chart``
  and goes through the same computation, over the same rows as the
  table - its filters, its search, ``get_queryset`` - so the panel
  follows the table, and a click on a bar filters it.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any, Sequence

from django.contrib.admin.utils import get_fields_from_path
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Avg, Sum
from django.utils.encoding import force_str
from django.utils.text import capfirst
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from generic.sites.auto import is_private
from generic.sites.charts import PERIOD_LABELS, PERIODS, Chart

#: What the panel offers to draw, with the icon of each.
TYPES = {
    "bar": (_("Bars"), "bar_chart"),
    "line": (_("Lines"), "show_chart"),
    "area": (_("Areas"), "area_chart"),
    "pie": (_("Pie"), "pie_chart"),
    "donut": (_("Donut"), "donut_large"),
    "funnel": (_("Funnel"), "filter_alt"),
    "heatmap": (_("Heatmap"), "grid_on"),
}
DEFAULT_TYPES = ("bar", "line", "area", "pie", "donut", "heatmap")

#: Forms with one series only: a second field means nothing to them.
SINGLE_SERIES = frozenset({"pie", "donut", "funnel"})

#: The dimensions worth grouping by: a few values shared by many rows.
GROUPED_KINDS = frozenset({"relation", "choice", "boolean", "date"})

#: Categories drawn at most, the rest gathered as "Other": a slice per
#: supplier is a pie nobody can read.
LIMITS = {"pie": 8, "donut": 8, "funnel": 8}
LIMIT = 20

#: The measure counting the rows, always offered.
COUNT = "count"


@dataclasses.dataclass(frozen=True)
class ChartBuilder:
    """What the reader may chart: ``None`` works it out from the model."""

    #: Field paths the rows may be grouped and split by: relations,
    #: choices, booleans, dates.
    group_by: Sequence[str] | None = None
    #: Number fields whose sum and average may be drawn, besides the
    #: count of rows.
    values: Sequence[str] | None = None
    #: The forms offered, the first one drawn first.
    types: Sequence[str] = DEFAULT_TYPES

    def __post_init__(self) -> None:
        for kind in self.types:
            if kind not in TYPES:
                raise ImproperlyConfigured(
                    f"ChartBuilder: unknown type '{kind}'. Known types: "
                    f"{', '.join(TYPES)}."
                )

        if not self.types:
            raise ImproperlyConfigured("ChartBuilder needs a type.")


@dataclasses.dataclass(frozen=True)
class Dimension:
    name: str
    field: Any
    kind: str

    @property
    def label(self) -> str:
        # Read at request time: in the reader's language.
        return label_of(self.field)


@dataclasses.dataclass(frozen=True)
class Measure:
    key: str
    model: Any
    #: "count", "sum" or "avg".
    how: str = "count"
    path: str = ""
    field: Any = None

    @property
    def aggregate(self) -> Any:
        """Sum("price"); None counts the rows."""
        if self.how == "sum":
            return Sum(self.path)

        if self.how == "avg":
            return Avg(self.path)

        return None

    @property
    def value_format(self) -> str | None:
        return "decimal" if self.how == "avg" else None

    @property
    def label(self) -> str:
        if self.how == "sum":
            return gettext("%(field)s (total)") % {
                "field": label_of(self.field)
            }

        if self.how == "avg":
            return gettext("%(field)s (average)") % {
                "field": label_of(self.field)
            }

        return gettext("Number of %(name)s") % {
            "name": force_str(self.model._meta.verbose_name_plural)
        }


def builder_of(declared: Any) -> ChartBuilder | None:
    """The declaration, as a ``ChartBuilder`` - or None, switched off."""
    if not declared:
        return None

    if declared is True:
        return ChartBuilder()

    if isinstance(declared, ChartBuilder):
        return declared

    if isinstance(declared, (list, tuple)):
        return ChartBuilder(group_by=tuple(declared))

    raise ImproperlyConfigured(
        "chart_builder is True, False, a tuple of field paths or a "
        f"ChartBuilder(...), not {declared!r}."
    )


def label_of(field: Any) -> str:
    return capfirst(force_str(getattr(field, "verbose_name", field.name)))


def kind_of(field: Any) -> str:
    """How the chart groups by ``field``, as ``charts.Dimension`` does."""
    if field.is_relation:
        return "relation"

    if getattr(field, "choices", None):
        return "choice"

    if isinstance(field, models.BooleanField):
        return "boolean"

    if isinstance(field, models.DateField):
        return "date"

    return "value"


def is_number(field: Any) -> bool:
    return (
        isinstance(
            field,
            (models.IntegerField, models.DecimalField, models.FloatField),
        )
        and not isinstance(field, models.AutoField)
        and not field.primary_key
        and not field.is_relation
        and not getattr(field, "choices", None)
    )


def candidates(resource: Any) -> list[str]:
    """The list's columns that are field paths, then the model's own
    fields: what a chart is usually asked about first, first."""
    names = [
        entry
        for entry in resource.get_list_display()
        if isinstance(entry, str) and entry != "__str__"
    ]
    opts = resource.model._meta
    names += [field.name for field in opts.fields]
    names += [field.name for field in opts.many_to_many]

    return list(dict.fromkeys(names))


def field_at(model: Any, path: str) -> Any:
    try:
        return get_fields_from_path(model, path)[-1]
    except Exception:
        return None


def offered(resource: Any, field: Any, path: str) -> bool:
    """Whether a worked-out field may be charted: never a secret -
    grouped, it is told (``auto``'s rule for columns) - nor what the
    resource excludes."""
    excluded = set(getattr(resource, "exclude", ()) or ())

    return not (
        path in excluded
        or path.split("__")[0] in excluded
        or is_private(field)
        or (field.auto_created and not field.concrete)
        or field.primary_key
        or isinstance(field, (models.FileField, models.UUIDField))
    )


class BoundChartBuilder:
    """A resource's chart builder: its dimensions and values, checked."""

    def __init__(self, resource: Any, declaration: ChartBuilder) -> None:
        self.resource = resource
        self.declaration = declaration
        self.dimensions = self.resolve_dimensions()
        self.measures = self.resolve_measures()
        self.types = tuple(declaration.types)

    def without(self, hidden: Any) -> BoundChartBuilder | None:
        """This builder for a reader who may not see ``hidden``
        (``field_permissions``): what is grouped or summed through one of
        them is not offered. None when nothing is left to group by."""
        if not hidden:
            return self

        bound = copy.copy(self)
        bound.dimensions = {
            path: entry
            for path, entry in self.dimensions.items()
            if path.split("__")[0] not in hidden
        }
        bound.measures = {
            key: entry
            for key, entry in self.measures.items()
            if not entry.path or entry.path.split("__")[0] not in hidden
        }

        return bound if bound.dimensions else None

    # -- what is offered ----------------------------------------------------

    def resolve_dimensions(self) -> dict[str, Dimension]:
        resource = self.resource
        model = resource.model
        owner = type(resource).__name__
        declared = self.declaration.group_by
        dimensions: dict[str, Dimension] = {}

        for path in declared if declared is not None else candidates(resource):
            path = str(path)
            field = field_at(model, path)

            if declared is not None:
                if field is None:
                    raise ImproperlyConfigured(
                        f"{owner}.chart_builder groups by '{path}', which "
                        f"is not a field path of {model.__name__}."
                    )

                if kind_of(field) not in GROUPED_KINDS:
                    raise ImproperlyConfigured(
                        f"{owner}.chart_builder groups by '{path}': a "
                        f"chart groups by a relation, a choice, a yes or "
                        f"no or a date - a value of its own per row is "
                        f"a bar per row."
                    )
            elif (
                field is None
                or kind_of(field) not in GROUPED_KINDS
                or not offered(resource, field, path)
            ):
                continue

            dimensions[path] = Dimension(
                name=path, field=field, kind=kind_of(field)
            )

        return dimensions

    def resolve_measures(self) -> dict[str, Measure]:
        resource = self.resource
        model = resource.model
        owner = type(resource).__name__
        declared = self.declaration.values
        measures = {COUNT: Measure(key=COUNT, model=model)}

        if declared is None:
            paths = [
                name
                for name in candidates(resource)
                if (field := field_at(model, name)) is not None
                and is_number(field)
                and offered(resource, field, name)
            ]
        else:
            paths = [str(path) for path in declared]

        for path in paths:
            field = field_at(model, path)

            if field is None or not is_number(field):
                raise ImproperlyConfigured(
                    f"{owner}.chart_builder sums '{path}', which is not a "
                    f"number field of {model.__name__}."
                )

            for how in ("sum", "avg"):
                key = f"{how}:{path}"
                measures[key] = Measure(
                    key=key, model=model, how=how, path=path, field=field
                )

        return measures

    def describe(self) -> dict[str, Any]:
        """What the panel offers, for the page."""
        dimensions = list(self.dimensions.values())
        first = next(
            (entry for entry in dimensions if entry.kind == "choice"),
            dimensions[0] if dimensions else None,
        )

        return {
            "dimensions": [
                {"value": entry.name, "label": entry.label, "kind": entry.kind}
                for entry in dimensions
            ],
            "values": [
                {"value": entry.key, "label": entry.label}
                for entry in self.measures.values()
            ],
            "types": [
                {
                    "value": kind,
                    "label": force_str(TYPES[kind][0]),
                    "icon": TYPES[kind][1],
                }
                for kind in self.types
            ],
            "periods": [
                {"value": period, "label": force_str(PERIOD_LABELS[period])}
                for period in PERIODS
            ],
            "single": sorted(SINGLE_SERIES),
            "defaults": {
                "type": self.types[0],
                "group_by": first.name if first else "",
                "split_by": "",
                "value": COUNT,
                "period": "month",
            },
        }

    # -- what is asked ------------------------------------------------------

    def chart(self, params: Any) -> Chart:
        """The chart a request asks for, or a ``ValueError`` per wrong
        parameter, by name."""
        errors: dict[str, list[str]] = {}

        kind = params.get("type") or self.types[0]
        group_by = params.get("group_by") or ""
        split_by = params.get("split_by") or ""
        value = params.get("value") or COUNT
        period = params.get("period") or "month"

        if kind not in self.types:
            errors["type"] = [gettext("This type is not offered.")]

        if group_by not in self.dimensions:
            errors["group_by"] = [gettext("This field is not offered.")]

        if kind in SINGLE_SERIES:
            # One series: a second field would only be dropped.
            split_by = ""

        if split_by and (
            split_by not in self.dimensions or split_by == group_by
        ):
            errors["split_by"] = [gettext("This field is not offered.")]

        if kind == "heatmap" and not split_by and "split_by" not in errors:
            errors["split_by"] = [gettext("A heatmap needs a second field.")]

        if value not in self.measures:
            errors["value"] = [gettext("This value is not offered.")]

        if period not in PERIODS:
            errors["period"] = [gettext("This period is not offered.")]

        if errors:
            raise BuilderError(errors)

        measure = self.measures[value]
        dates = self.dimensions[group_by].kind == "date"

        return Chart(
            "builder",
            title=self.title(measure, group_by, split_by),
            type=kind,
            group_by=group_by,
            split_by=split_by or None,
            value=measure.aggregate,
            value_label=measure.label if measure.aggregate else None,
            value_format=measure.value_format,
            period=period,
            periods=PERIODS,
            stacked=bool(split_by) and is_on(params.get("stacked")),
            horizontal=kind == "bar" and is_on(params.get("horizontal")),
            limit=None if dates else LIMITS.get(kind, LIMIT),
        )

    def title(self, measure: Measure, group_by: str, split_by: str) -> str:
        values = {
            "value": measure.label,
            "group": self.dimensions[group_by].label.lower(),
        }

        if not split_by:
            return gettext("%(value)s by %(group)s") % values

        return gettext("%(value)s by %(group)s and %(split)s") % {
            **values,
            "split": self.dimensions[split_by].label.lower(),
        }


class BuilderError(ValueError):
    def __init__(self, errors: dict[str, list[str]]) -> None:
        super().__init__(errors)
        self.errors = errors


def is_on(value: Any) -> bool:
    return str(value or "").lower() in ("1", "true", "on", "yes")


def bind(resource: Any) -> BoundChartBuilder | None:
    """The resource's chart builder, checked - None when it has none or
    nothing to group by."""
    declaration = builder_of(resource.chart_builder)

    if declaration is None:
        return None

    bound = BoundChartBuilder(resource, declaration)

    return bound if bound.dimensions else None


__all__ = ["ChartBuilder", "BoundChartBuilder", "bind"]

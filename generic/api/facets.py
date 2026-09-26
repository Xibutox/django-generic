"""Facets: the values a column holds, and how many rows hold each.

``GET <table endpoint>/facets/?column=status`` answers with the values of
one column among the rows the table would show - the search, the
``_related`` narrowing and every *other* filter applied - so the filter
editor can offer what exists, with a count beside each value, and never
a choice leading to an empty table::

    {"column": "status", "kind": "values", "more": false,
     "values": [{"value": "open", "label": "Open", "count": 40},
                {"value": null, "label": "Empty", "count": 2}]}

A number or a date answers with its range instead::

    {"column": "hours", "kind": "range", "min": 0.25, "max": 12, "empty": 3}

``q`` narrows the values by their label, ``ids=1,2`` asks for the labels
of known values - how a filter restored from a link names what it holds.
Only columns the serializer declares filterable and facetable answer.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any

from django.contrib.admin.utils import get_fields_from_path
from django.core.exceptions import FieldDoesNotExist, FieldError
from django.db import models
from django.db.models import Count, Max, Min
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.translation import gettext
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from generic.api.columns import (
    FILTER_BOOLEAN,
    FILTER_DATE,
    FILTER_DATETIME,
    FILTER_FLOAT,
    FILTER_INTEGER,
    FILTER_TEXT,
)

#: Query parameters.
COLUMN_PARAM = "column"
SEARCH_PARAM = "q"
IDS_PARAM = "ids"

#: Values listed, at most, before ``more`` says there are others.
FACET_LIMIT = 50
MAX_IDS = 100

RANGE_TYPES = frozenset(
    {FILTER_INTEGER, FILTER_FLOAT, FILTER_DATE, FILTER_DATETIME}
)

#: Text fields a related record is usually named by, in order.
LABEL_CANDIDATES = (
    "name",
    "title",
    "label",
    "reference",
    "code",
    "username",
    "email",
)


def plain(value: Any) -> Any:
    """A value JSON carries as it is."""
    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)

        return value.date().isoformat()

    if isinstance(value, datetime.date):
        return value.isoformat()

    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral() else float(value)

    return value


def related_model_of(model: Any, path: str) -> Any:
    """The model at the end of ``path``, when it ends on a relation."""
    try:
        field = get_fields_from_path(model, path)[-1]
    except Exception:
        return None

    return field.related_model if field.is_relation else None


def label_lookup(related: Any, spec: Any, options: Any) -> str | None:
    """Which field of the related model a search by label looks into."""
    prefix = f"{spec.field}__"
    search = options.search_field or ""

    if search.startswith(prefix):
        return search[len(prefix) :]

    for name in LABEL_CANDIDATES:
        try:
            field = related._meta.get_field(name)
        except FieldDoesNotExist:
            continue

        if isinstance(field, (models.CharField, models.TextField)):
            return name

    return None


def coerce_keys(spec: Any, raw: str) -> list[Any]:
    keys: list[Any] = []

    for item in raw.split(",")[:MAX_IDS]:
        item = item.strip()

        if not item:
            continue

        if spec.value_type == "integer":
            try:
                keys.append(int(item))
            except ValueError:
                continue
        else:
            keys.append(item)

    return keys


class FacetMixin:
    """Add a ``facets`` action to a table endpoint."""

    #: Switch off for an endpoint whose rows are not model instances -
    #: an aggregated table, for one.
    facets_enabled = True
    facet_limit = FACET_LIMIT

    #: Set while a facet is computed: the filter backend then leaves out
    #: the conditions on that column.
    facet_column: str | None = None

    @action(
        detail=False,
        methods=["get"],
        url_path="facets",
        url_name="facets",
    )
    def facets(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        if not self.facets_enabled:
            raise NotFound(gettext("This table offers no facets."))

        name = request.query_params.get(COLUMN_PARAM, "")
        serializer_class = self.get_serializer_class()  # type: ignore
        entry = next(
            (
                (field_name, field, options)
                for field_name, field, options in (
                    serializer_class.get_datatable_fields()
                )
                if field_name == name
            ),
            None,
        )

        if (
            entry is None
            or not entry[2].filterable
            or not entry[1].resolve_facetable(entry[2])
        ):
            raise ValidationError(
                {COLUMN_PARAM: [gettext("This column has no facets.")]}
            )

        field_name, field, options = entry
        spec = field.build_filter(field_name, options)

        self.facet_column = field_name

        try:
            filtered = self.filter_queryset(  # type: ignore[attr-defined]
                self.get_queryset()  # type: ignore[attr-defined]
            )
            base = self.get_facet_queryset(filtered)
            payload = self.compute_facets(base, field, options, spec, request)
        except FieldError:
            # A column filtering on an annotation has no plain values to
            # count; the editor simply offers no suggestions.
            payload = {"kind": "values", "values": [], "more": False}
            payload["unavailable"] = True
        finally:
            self.facet_column = None

        payload["column"] = field_name

        return Response(payload)

    def get_facet_queryset(self, filtered: Any) -> Any:
        """The rows to count: the filtered ones, without the table's
        annotations and joins, which would count a row twice."""
        model = filtered.model

        return model._default_manager.filter(
            pk__in=filtered.order_by().values("pk")
        )

    def compute_facets(
        self,
        queryset: Any,
        field: Any,
        options: Any,
        spec: Any,
        request: Any,
    ) -> dict[str, Any]:
        if spec.type in RANGE_TYPES:
            return self.range_facet(queryset, spec)

        return self.value_facet(queryset, field, options, spec, request)

    def range_facet(self, queryset: Any, spec: Any) -> dict[str, Any]:
        bounds = queryset.aggregate(low=Min(spec.field), high=Max(spec.field))
        empty = queryset.filter(**{f"{spec.field}__isnull": True}).count()

        return {
            "kind": "range",
            "min": plain(bounds["low"]),
            "max": plain(bounds["high"]),
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
        related = related_model_of(queryset.model, spec.field)
        rows = (
            queryset.order_by()
            .values(spec.field)
            .annotate(facet_count=Count("pk", distinct=True))
        )

        raw_ids = request.query_params.get(IDS_PARAM)
        term = (request.query_params.get(SEARCH_PARAM) or "").strip()[:100]

        if raw_ids is not None:
            rows = rows.filter(
                **{f"{spec.field}__in": coerce_keys(spec, raw_ids)}
            )
        elif term:
            rows = self.search_values(
                rows, term, choices, related, options, spec
            )

        limit = self.facet_limit
        found = list(rows.order_by("-facet_count", spec.field)[: limit + 1])
        keys = [row[spec.field] for row in found[:limit]]
        records = (
            related._default_manager.in_bulk(
                [key for key in keys if key is not None]
            )
            if related is not None
            else {}
        )
        style = getattr(field, "tag_style", None)
        values = []

        for row in found[:limit]:
            key = row[spec.field]
            record = records.get(key)
            label = self.facet_label(key, record, choices, spec)
            entry = {
                "value": plain(key),
                "label": label,
                "count": row["facet_count"],
            }

            if style is not None and key is not None:
                tag = style.describe(
                    record if record is not None else key, label
                )

                if tag:
                    entry["tag"] = tag

            values.append(entry)

        return {
            "kind": "values",
            "values": values,
            "more": len(found) > limit,
        }

    @staticmethod
    def search_values(
        rows: Any,
        term: str,
        choices: dict[Any, Any],
        related: Any,
        options: Any,
        spec: Any,
    ) -> Any:
        lowered = term.lower()

        if choices:
            keys = [
                key
                for key, label in choices.items()
                if lowered in force_str(label).lower()
            ]

            return rows.filter(**{f"{spec.field}__in": keys})

        if related is not None:
            lookup = label_lookup(related, spec, options)

            if lookup is None:
                return rows.none()

            matching = related._default_manager.filter(
                **{f"{lookup}__icontains": term}
            ).values("pk")

            return rows.filter(**{f"{spec.field}__in": matching})

        if spec.type == FILTER_TEXT:
            return rows.filter(**{f"{spec.field}__icontains": term})

        return rows

    @staticmethod
    def facet_label(
        key: Any,
        record: Any,
        choices: dict[Any, Any],
        spec: Any,
    ) -> str:
        if key is None or key == "":
            return gettext("Empty")

        if record is not None:
            return force_str(record)

        if spec.type == FILTER_BOOLEAN:
            return gettext("Yes") if key else gettext("No")

        if key in choices:
            return force_str(choices[key])

        if force_str(key) in choices:
            return force_str(choices[force_str(key)])

        return force_str(plain(key))

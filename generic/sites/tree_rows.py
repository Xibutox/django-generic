"""A tree laid flat: everything a record holds, at every depth, as a table.

``Tree(..., flat=True)`` gives each record a page listing every record
below it - one row per place it takes, with its level, what holds it,
the path from the record down to it and, with ``quantity``, how many of
it one of the record needs - in an ordinary table: filters on every
column, search, sorting, the column selector, Excel and CSV::

    Tree(
        "bom",
        through=BomLine,
        parent="parent",
        child="child",
        link_columns=("position", "quantity"),
        flat=True,
        flat_title=_("Exploded BOM"),
        quantity="quantity",
    )

``?grouped=1`` lists each record once instead, with how many places it
takes and its quantities added up: what to buy for one of the record.

The rows are worked out per request, from the same links as the tree -
the resources' querysets, a level a query - and the table protocol of
rows that are not a model's (generic.api.rows) filters, sorts, pages
and exports them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils.encoding import force_str
from django.utils.translation import gettext, gettext_lazy
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError

from generic.api.columns import (
    BooleanColumn,
    CharColumn,
    ChoiceColumn,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    FloatColumn,
    IntegerColumn,
)
from generic.api.rows import RowsDataTableViewSet
from generic.api.serializers import DataTableSerializer
from generic.sites.pages import ResourcePage, ResourcePageView
from generic.sites.serializers import ROW_KEY, resolve_display_callable
from generic.sites.trees import DOWN, WALK_CHUNK, BoundTree, entry_label

#: The most rows a flat table lists: a shared assembly is listed in
#: each place it takes, so a deep tree can list many times its records.
MAX_ROWS = 20_000

#: The parameter asking for one row per record rather than per place.
GROUPED_PARAM = "grouped"

#: Between the records of a path.
PATH_SEPARATOR = " › "

#: The columns every flat table has, by the key of their values.
LEVEL = "level"
LABEL = "label"
PARENT = "parent"
PATH = "path"
PLACES = "places"
TOTAL = "total_quantity"
#: Hidden: the key of a row's record, which its name links to.
RECORD = "record"

RESERVED = frozenset({ROW_KEY, LEVEL, LABEL, PARENT, PATH, PLACES, TOTAL})


def link_key(name: str) -> str:
    """The key of a link's value in a row: apart from the record's."""
    return f"link_{name}"


def column_for_field(field: Any, title: str) -> Any:
    """A table column for the values of ``field`` (None: computed)."""
    if field is None or field.is_relation:
        return CharColumn(title=title)

    if field.choices:
        return ChoiceColumn(choices=field.flatchoices, title=title)

    for kind, column in (
        (models.BooleanField, BooleanColumn),
        (models.FloatField, FloatColumn),
        (models.IntegerField, IntegerColumn),
        (models.DateTimeField, DateTimeColumn),
        (models.DateField, DateColumn),
    ):
        if isinstance(field, kind):
            return column(title=title)

    if isinstance(field, models.DecimalField):
        return DecimalColumn(max_digits=None, decimal_places=None, title=title)

    return CharColumn(title=title)


def get_field(model: Any, name: str) -> Any:
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def read_value(resource: Any, model: Any, obj: Any, name: str) -> Any:
    """The value of a column: a field's, or what a method computes."""
    field = get_field(model, name)

    if field is None:
        function = resolve_display_callable(name, resource, model)
        value = function(obj) if function is not None else None
    else:
        value = getattr(obj, field.name, None)

    if isinstance(value, models.Model):
        return force_str(value)

    return value


class FlatTree:
    """The flat table of one tree."""

    def __init__(self, bound: BoundTree) -> None:
        self.bound = bound
        self._serializers: dict[tuple[bool, bool], Any] = {}

    @property
    def resource(self) -> Any:
        return self.bound.resource

    @property
    def definition(self) -> Any:
        return self.bound.definition

    @property
    def page_name(self) -> str:
        return f"{self.bound.name}-flat"

    def get_title(self) -> str:
        if self.definition.flat_title:
            return force_str(self.definition.flat_title)

        return gettext("Every level")

    def shows_quantity(self, request: Any) -> bool:
        """The quantities are the links': for whoever may read them."""
        quantity = self.definition.quantity

        return bool(quantity) and self.links_readable(request)

    def links_readable(self, request: Any) -> bool:
        link_resource = self.bound.get_link_resource()

        return self.bound.linked and (
            link_resource is None or link_resource.has_view_permission(request)
        )

    # -- the columns ---------------------------------------------------

    def get_serializer_class(self, request: Any, grouped: bool) -> Any:
        links = self.links_readable(request)
        cached = self._serializers.get((grouped, links))

        if cached is not None:
            return cached

        resource = self.resource
        model = resource.model
        attributes: dict[str, Any] = {
            ROW_KEY: serializers.CharField(read_only=True),
            RECORD: serializers.CharField(read_only=True),
        }

        if not grouped:
            attributes[LEVEL] = IntegerColumn(title=gettext_lazy("Level"))

        attributes[LABEL] = CharColumn(title=resource.get_label())

        if grouped:
            attributes[PLACES] = IntegerColumn(title=gettext_lazy("Places"))
            attributes[LEVEL] = IntegerColumn(
                title=gettext_lazy("First level")
            )
        else:
            attributes[PARENT] = CharColumn(title=gettext_lazy("Held by"))
            attributes[PATH] = CharColumn(
                title=gettext_lazy("Path"), visible=False
            )

            for name in self.definition.link_columns if links else ():
                attributes[link_key(name)] = column_for_field(
                    get_field(self.bound.link_model, name),
                    entry_label(
                        self.bound.get_link_resource(),
                        self.bound.link_model,
                        name,
                    ),
                )

        for name in self.definition.columns:
            field = get_field(model, name)
            function = (
                resolve_display_callable(name, resource, model)
                if field is None
                else None
            )
            title = entry_label(resource, model, name)

            if function is not None and getattr(function, "boolean", False):
                attributes[name] = BooleanColumn(title=title)
            else:
                attributes[name] = column_for_field(field, title)

        if self.definition.quantity and links:
            attributes[TOTAL] = DecimalColumn(
                max_digits=None,
                decimal_places=None,
                title=gettext_lazy("Total quantity"),
            )

        template = resource.get_object_url_template("{" + RECORD + "}")
        attributes["datatable_overrides"] = (
            {LABEL: {"display_type": "link", "link_url": template}}
            if template
            else {}
        )
        attributes["__module__"] = __name__
        serializer = type(
            f"{type(resource).__name__}{self.bound.name.title()}Rows",
            (DataTableSerializer,),
            attributes,
        )
        self._serializers[(grouped, links)] = serializer

        return serializer

    # -- the rows ------------------------------------------------------

    def get_rows(self, request: Any, root: Any, grouped: bool) -> list[dict]:
        """Every record below ``root``: one row per place - or, grouped,
        per record - in the tree's order."""
        bound = self.bound
        below, met, _cut = bound.walk(request, DOWN, [root.pk])
        records = self.read_records(request, met)
        links = (
            self.read_links(request, below)
            if self.links_readable(request)
            else {}
        )
        quantity = self.definition.quantity if links else None
        values = {
            pk: {
                name: read_value(self.resource, self.resource.model, obj, name)
                for name in self.definition.columns
            }
            for pk, obj in records.items()
        }
        labels = {
            pk: self.resource.get_object_label(obj)
            for pk, obj in records.items()
        }
        rows: list[dict[str, Any]] = []
        totals: dict[Any, dict[str, Any]] = {}
        # Depth first, the first child on top: (key, record, level,
        # ancestors, keys above, quantity of one root).
        stack = [
            (key, held, 1, (root.pk,), (), Decimal(1))
            for key, held in reversed(below.get(root.pk, ()))
        ]

        while stack and len(rows) < MAX_ROWS:
            key, pk, level, ancestors, keys, above = stack.pop()

            if pk not in records:
                continue

            link = links.get(key)
            amount = None

            if quantity:
                each = getattr(link, quantity, None) if link else None
                amount = (
                    above * Decimal(force_str(each))
                    if above is not None and each is not None
                    else None
                )

            place = (*keys, key)

            if grouped:
                entry = totals.get(pk)

                if entry is None:
                    entry = totals[pk] = {
                        ROW_KEY: force_str(pk),
                        RECORD: pk,
                        LABEL: labels[pk],
                        PLACES: 0,
                        LEVEL: level,
                        **values[pk],
                    }

                    if quantity:
                        entry[TOTAL] = Decimal(0)

                    rows.append(entry)

                entry[PLACES] += 1
                entry[LEVEL] = min(entry[LEVEL], level)

                if quantity:
                    entry[TOTAL] = (
                        entry[TOTAL] + amount
                        if entry[TOTAL] is not None and amount is not None
                        else None
                    )
            else:
                row = {
                    ROW_KEY: "-".join(force_str(part) for part in place),
                    RECORD: pk,
                    LEVEL: level,
                    LABEL: labels[pk],
                    PARENT: labels.get(ancestors[-1], ""),
                    PATH: PATH_SEPARATOR.join(
                        labels.get(holder, "") for holder in ancestors
                    ),
                    **values[pk],
                }

                for name in self.definition.link_columns if links else ():
                    row[link_key(name)] = (
                        getattr(link, name, None) if link else None
                    )

                if quantity:
                    row[TOTAL] = self.tidy(amount)

                rows.append(row)

            # Met again below itself: listed, not walked into again.
            if pk in ancestors:
                continue

            stack.extend(
                (
                    child_key,
                    held,
                    level + 1,
                    (*ancestors, pk),
                    place,
                    amount if quantity else above,
                )
                for child_key, held in reversed(below.get(pk, ()))
            )

        if grouped and quantity:
            for entry in rows:
                entry[TOTAL] = self.tidy(entry[TOTAL])

        return rows

    def tidy(self, amount: Decimal | None) -> Decimal | None:
        """A product of quantities, written with the quantity's own
        decimals - more only where they matter."""
        if amount is None:
            return None

        field = get_field(self.bound.link_model, self.definition.quantity)
        places = getattr(field, "decimal_places", None)

        if places is not None:
            rounded = amount.quantize(Decimal(1).scaleb(-places))

            if rounded == amount:
                return rounded

        return (
            amount.normalize()
            if amount != amount.to_integral()
            else (amount.quantize(Decimal(1)))
        )

    def read_records(self, request: Any, pks: list[Any]) -> dict[Any, Any]:
        model = self.resource.model
        related = [
            name
            for name in self.definition.columns
            if (field := get_field(model, name)) is not None
            and field.many_to_one
        ]
        records: dict[Any, Any] = {}

        for start in range(0, len(pks), WALK_CHUNK):
            queryset = self.bound.visible(request).filter(
                pk__in=pks[start : start + WALK_CHUNK]
            )

            if related:
                queryset = queryset.select_related(*related)

            records.update((record.pk, record) for record in queryset)

        return records

    def read_links(
        self,
        request: Any,
        below: dict[Any, list[tuple[Any, Any]]],
    ) -> dict[Any, Any]:
        keys = [key for entries in below.values() for key, _held in entries]
        links: dict[Any, Any] = {}

        for start in range(0, len(keys), WALK_CHUNK):
            links.update(
                (link.pk, link)
                for link in self.bound.links(request).filter(
                    pk__in=keys[start : start + WALK_CHUNK]
                )
            )

        return links

    # -- where it shows -------------------------------------------------

    def get_api_url(self) -> str:
        return self.resource._reverse(
            f"{self.resource.site.name}:{self.get_url_basename()}-list"
        )

    def get_url_basename(self) -> str:
        return f"api_{self.resource.url_prefix}_tree_{self.bound.name}"

    def get_url_prefix(self) -> str:
        resource = self.resource

        return (
            f"api/{resource.app_label}/{resource.model_name}/trees/"
            f"{self.bound.name}/flat"
        )

    def get_page_url(self, obj: Any, grouped: bool = False) -> str:
        url = self.resource.get_page_url(self.page_name, obj)

        return f"{url}?{GROUPED_PARAM}=1" if url and grouped else url

    def get_table_config(
        self, request: Any, obj: Any, grouped: bool
    ) -> dict[str, Any]:
        from generic.sites.resources import _preferences_for
        from generic.views.datatable import filter_row_option

        resource = self.resource
        serializer = self.get_serializer_class(request, grouped)
        preferences = _preferences_for(request)
        page_length = (
            int(preferences.table_page_size)
            if preferences is not None and preferences.table_page_size
            else 50
        )
        shape = "grouped" if grouped else "places"
        name = f"{resource.model_name}-{self.bound.name}"

        return {
            "url": self.get_api_url(),
            "columns": [
                dict(column) for column in serializer.get_datatable_columns()
            ],
            "options": {
                "pageLength": page_length,
                "lengthMenu": [25, 50, 100, 250, 500],
                "stateKey": (
                    f"{resource.state_key}.tree.{self.bound.name}.{shape}"
                ),
                "columnSelector": True,
                "filters": True,
                "filterRow": filter_row_option(resource),
                "excel": True,
                "csv": True,
                "copy": True,
                "print": True,
                "rowKey": ROW_KEY,
                "rowActions": [],
                "label": resource.get_label(),
                "labelPlural": resource.get_label_plural(),
                "exportName": f"{name}-{obj.pk}",
                "syncUrl": False,
                "extraParams": {
                    "root": force_str(obj.pk),
                    **({GROUPED_PARAM: "1"} if grouped else {}),
                },
            },
        }

    def get_viewset_class(self) -> type:
        return type(
            f"{type(self.resource).__name__}{self.bound.name.title()}"
            f"RowsViewSet",
            (FlatTreeViewSet,),
            {"flat": self, "__module__": __name__},
        )


def is_grouped(params: Any) -> bool:
    return (params.get(GROUPED_PARAM) or "") in ("1", "true", "yes")


class FlatTreePermission(permissions.BasePermission):
    """The resource's view permission, on the flat table's endpoint."""

    def has_permission(self, request: Any, view: Any) -> bool:
        return bool(view.flat.resource.has_view_permission(request))


class FlatTreeViewSet(RowsDataTableViewSet):
    """``api/<app>/<model>/trees/<name>/flat/?root=<pk>``: everything
    the record holds, a row per place (``grouped=1``: per record)."""

    flat: Any = None
    permission_classes = (permissions.IsAuthenticated, FlatTreePermission)

    @property
    def export_file_name(self) -> str:  # type: ignore[override]
        resource = self.flat.resource

        return f"{resource.model_name}-{self.flat.bound.name}"

    def get_grouped(self) -> bool:
        return is_grouped(self.request.query_params)

    def get_serializer_class(self) -> Any:
        return self.flat.get_serializer_class(self.request, self.get_grouped())

    def get_rows(self) -> Iterable[Any]:
        value = self.request.query_params.get("root")

        if not value:
            raise ValidationError(
                {"root": [gettext("Name the record the table starts from.")]}
            )

        root = self.flat.bound.find(self.request, value)

        return self.flat.get_rows(self.request, root, self.get_grouped())


def flat_page(bound: BoundTree) -> ResourcePage:
    """The page of each record listing everything below it."""
    flat = FlatTree(bound)

    return ResourcePage(
        flat.page_name,
        view=FlatTreePageView,
        title=bound.definition.flat_title or gettext_lazy("Every level"),
        icon="table_rows",
        detail=True,
    )


class FlatTreePageView(ResourcePageView):
    """A record's flat table: a row per place, or per record."""

    template_name = "generic/resource/tree_flat.html"

    def get_flat(self) -> FlatTree:
        name = self.page.name.removesuffix("-flat")

        return self.resource.get_tree(name).get_flat()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        flat = self.get_flat()
        grouped = is_grouped(self.request.GET)
        bound = flat.bound
        context.update(
            flat=flat,
            grouped=grouped,
            table=flat.get_table_config(self.request, self.object, grouped),
            places_url=flat.get_page_url(self.object),
            grouped_url=flat.get_page_url(self.object, grouped=True),
            tree_url=bound.get_record_page_url(self.object),
            shows_quantity=flat.shows_quantity(self.request),
            max_rows=MAX_ROWS,
        )

        return context


__all__ = [
    "FlatTree",
    "FlatTreePageView",
    "FlatTreeViewSet",
    "MAX_ROWS",
    "flat_page",
]

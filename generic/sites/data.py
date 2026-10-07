"""Pages for rows that are not a model's: ``DataResource``.

An external API's answer, a file, a computation - a list of dicts - gets
a list page and a page per row, the way a model does, and nothing to
write: those rows are read, not edited::

    from generic.api import CharColumn, FloatColumn, TagsColumn
    from generic.sites import DataResource, register_data

    @register_data
    class ServiceResource(DataResource):
        name = "services"                  # data/services/
        label = _("service")
        label_plural = _("services")
        icon = "cloud"
        key = "id"                         # data/services/<id>/
        columns = {
            "name": CharColumn(title=_("Service")),
            "status": TagsColumn(choices=STATUSES, filter_type="multiselect"),
            "uptime": FloatColumn(title=_("Uptime %")),
            "checked_at": datetime.datetime,     # a type is enough
        }

        def get_rows(self, request):
            return statuspage.services()      # [{"id": ..., ...}, ...]

The table filters, searches, sorts, counts its values and exports as a
model's does (``generic.api.rows``), and the row's page shows every
column - or ``detail_fieldsets`` - as a summary page shows a record.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime
import re
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Sequence

from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import Http404
from django.urls import NoReverseMatch, reverse
from django.utils.encoding import force_str
from django.utils.text import capfirst, slugify
from django.utils.translation import gettext
from rest_framework import permissions, serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from generic.api.columns import (
    BooleanColumn,
    CharColumn,
    ChoiceColumn,
    DataTableFieldMixin,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    FloatColumn,
    IntegerColumn,
    TagsColumn,
    prettify_field_name,
)
from generic.api.rows import (
    RowsDataTableViewSet,
    as_bool,
    as_date,
    as_datetime,
    as_number,
    values_at,
)
from generic.api.serializers import DataTableSerializer
from generic.conf import generic_settings
from generic.sites.pages import PagesMixin, allows
from generic.sites.related import RELATED_PARAM
from generic.sites.serializers import ROW_KEY
from generic.sites.summary import describe_value, format_number
from generic.views.datatable import filter_row_option, saved_view_options

#: A name is a piece of address: ``data/<name>/``.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: Replaced by the row's key in an address template.
KEY_PLACEHOLDER = "__key__"

#: The hidden field carrying the key a link leads to.
LINK_KEY = "_link_{}"

#: A plain type is enough for a column: it says which one.
COLUMN_TYPES: tuple[tuple[type, type], ...] = (
    (bool, BooleanColumn),
    (int, IntegerColumn),
    (float, FloatColumn),
    (Decimal, DecimalColumn),
    (datetime.datetime, DateTimeColumn),
    (datetime.date, DateColumn),
    (str, CharColumn),
)


class RowDateTimeColumn(DateTimeColumn):
    """A timestamp an API sends as text, shown as a model's is: in the
    active time zone, in the reader's language."""

    def to_representation(self, value: Any) -> Any:
        if isinstance(value, str):
            value = as_datetime(value) or value

        return super().to_representation(value)


class RowDateColumn(DateColumn):
    """A date an API sends as text - or as a timestamp - as a date."""

    def to_representation(self, value: Any) -> Any:
        if isinstance(value, str):
            value = as_date(value) or value

        return super().to_representation(value)


#: Date columns, as rows from elsewhere need them.
ROW_COLUMNS: dict[type, type] = {
    DateTimeColumn: RowDateTimeColumn,
    DateColumn: RowDateColumn,
}


def column_for(name: str, declared: Any) -> DataTableFieldMixin:
    """A column declared as a column, or as the type of its values."""
    if isinstance(declared, DataTableFieldMixin):
        replacement = ROW_COLUMNS.get(type(declared))

        if replacement is not None:
            # Built again from what it was declared with, as DRF copies a
            # field: the declaration stays as it was written.
            return replacement(
                *declared._args, **declared._kwargs  # type: ignore
            )

        return copy.deepcopy(declared)

    if isinstance(declared, type):
        if issubclass(declared, (list, tuple, set)):
            return TagsColumn(
                filter_type="multiselect",
                filter_many=True,
                orderable=False,
            )

        for kind, column_class in COLUMN_TYPES:
            if issubclass(declared, kind):
                if column_class is DecimalColumn:
                    return DecimalColumn(max_digits=None, decimal_places=None)

                return ROW_COLUMNS.get(column_class, column_class)()

    raise ImproperlyConfigured(
        f"The column {name!r} is declared as {declared!r}: a column "
        f"(CharColumn(...), TagsColumn(...)) or a type (str, int, float, "
        f"Decimal, bool, date, datetime, list) is expected."
    )


@dataclasses.dataclass(frozen=True)
class RowLink:
    """A field naming a row of another data resource.

    ``links = {"service_name": RowLink("services", key="service")}``: the
    column shows ``service_name`` and leads to the service whose key is
    in ``service`` - in the table and on the row's page, for whoever may
    see that resource. ``key`` defaults to the field itself; a plain
    resource name stands for ``RowLink(name)``.
    """

    resource: str
    key: str | None = None


@dataclasses.dataclass(frozen=True)
class RelatedRows:
    """A table of another data resource's rows, on a row's page.

    ``RelatedRows("incidents", resource="incidents", field="service")``:
    the incidents whose ``service`` holds this row's key, as a tab of
    the service's page - their own table, filters and exports, each
    opening on its own page. ``rows(request, parent_row)`` fetches them
    instead, for an API answering ``/services/<id>/incidents``.
    """

    #: The tab, and what the table's ``_related`` parameter names.
    name: str
    #: The data resource the rows are, by its ``name``.
    resource: str
    #: The field of those rows holding this row's key.
    field: str | None = None
    #: ``rows(request, parent_row)``: the rows, fetched by the project.
    rows: Callable[[Any, Any], Iterable[Any]] | None = None
    title: Any = None
    icon: str | None = None
    description: Any = ""
    #: The columns shown at first; the others stay in the column picker.
    columns: Sequence[str] | None = None
    page_length: int | None = 10


class DataPermission(permissions.BasePermission):
    """The resource's view permission, on its endpoint."""

    def has_permission(self, request: Any, view: Any) -> bool:
        return bool(view.resource.has_view_permission(request))


class DataResourceViewSet(RowsDataTableViewSet):
    """The endpoint of one data resource: its rows, their facets and
    exports, and ``<key>/summary/`` for one row's page."""

    resource: Any = None
    permission_classes = (permissions.IsAuthenticated, DataPermission)
    # A key is one piece of an address.
    lookup_value_regex = "[^/]+"

    @property
    def ordering(self) -> Sequence[str]:  # type: ignore[override]
        return tuple(self.resource.ordering or ())

    @property
    def export_file_name(self) -> str:  # type: ignore[override]
        return self.resource.name

    def get_serializer_class(self) -> Any:
        return self.resource.get_table_serializer_class()

    def get_rows(self) -> Iterable[Any]:
        related = self.request.query_params.get(RELATED_PARAM)

        # A tab of another row's page: the rows belonging to it.
        if related:
            return self.resource.get_rows_related_to(self.request, related)

        return self.resource.get_rows(self.request)

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request: Any, pk: str = "") -> Response:
        row = self.resource.get_row(request, pk)

        if row is None:
            raise NotFound

        return Response(self.resource.build_summary(request, row))


class DataResource(PagesMixin):
    """How rows that are not a model's appear in the application.

    Declare ``name``, ``columns`` and ``get_rows``; the rest has a
    default. Registered with ``@register_data`` or
    ``site.register_data(ServiceResource)``.
    """

    # -- identity and navigation ------------------------------------------

    #: The piece of address: ``data/<name>/``. Lower case, digits and
    #: dashes; the class name when left out.
    name: str = ""
    label: Any = None
    label_plural: Any = None
    icon: str = "dataset"
    #: Sidebar group.
    group: Any = ""
    order: int = 0
    show_in_navigation: bool = True
    description: Any = ""

    #: Who sees it: a permission string, an iterable of them (all
    #: required), ``callable(user)``, or ``None`` for any signed-in user.
    permission: Any = None

    # -- the rows -----------------------------------------------------------

    #: The field naming a row in its address - unique, and without "/".
    key: str = "id"
    #: The table's columns, in order: a column (``CharColumn(title=...)``,
    #: ``TagsColumn(...)``) or the type of the values (``str``, ``int``,
    #: ``float``, ``Decimal``, ``bool``, ``date``, ``datetime``,
    #: ``list``).
    columns: Mapping[str, Any] = {}
    #: Columns linking to the row's page. Defaults to the first.
    list_display_links: Sequence[str] | None = None
    #: The order when the reader asks for none: ``("-uptime", "name")``.
    ordering: Sequence[str] = ()
    list_per_page: int | None = None
    show_export: bool = True
    #: The row of search fields under the headers: ``"open"``,
    #: ``"toggle"`` or ``False``.
    filter_row: str | bool = "open"
    #: Named layouts offered to every user in the **Views** menu, beside
    #: each user's own saved views - as on a ``ModelResource``.
    presets: dict[str, dict[str, Any]] = {}
    table_options: dict[str, Any] = {}

    # -- a row's page ---------------------------------------------------------

    #: The field a row is called by. Defaults to the first column.
    label_field: str | None = None
    #: Sections of the row's page, fieldsets style; any key of the row
    #: may appear, a column or not. Defaults to one section of every
    #: column.
    detail_fieldsets: Any = None
    #: Figures shown as tiles above the sections.
    detail_stats: Sequence[str] = ()
    #: Tabs of other data resources' rows belonging to this one:
    #: ``RelatedRows("incidents", resource="incidents", field="service")``.
    related_tables: Sequence[RelatedRows] = ()

    # -- other resources' rows ------------------------------------------------

    #: Fields naming a row of another data resource, drawn as a link to
    #: its page: ``{"service_name": RowLink("services", key="service")}``,
    #: or ``{"service": "services"}`` when the field holds the key.
    links: Mapping[str, Any] = {}

    #: What the shared templates ask of a resource: these rows are not
    #: watched, and nobody announces their changes.
    watchable = False
    realtime = False

    def __init__(self, site: Any) -> None:
        self.site = site
        self._serializer_class: Any = None

        if not self.name:
            self.name = slugify(type(self).__name__.replace("Resource", ""))

        if not NAME_PATTERN.match(self.name):
            raise ImproperlyConfigured(
                f"{type(self).__name__}.name must be lower case letters, "
                f"digits and dashes, not {self.name!r}."
            )

        if not self.columns:
            raise ImproperlyConfigured(
                f"{type(self).__name__} declares no columns."
            )

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}>"

    # -- the rows -------------------------------------------------------------

    def get_rows(self, request: Any) -> Iterable[Any]:
        """Every row: a list of dicts, or of objects. Called on every
        request the table makes - cache what is slow to fetch."""
        raise NotImplementedError(
            f"{type(self).__name__} must define get_rows(request)."
        )

    def get_row(self, request: Any, key: str) -> Any:
        """The row whose ``key`` reads as ``key``, or ``None``.

        Override to fetch one row on its own when the source can."""
        for row in self.get_rows(request):
            value = self.read(row, self.key)

            if value is not None and force_str(value) == key:
                return row

        return None

    @staticmethod
    def read(row: Any, name: str) -> Any:
        if isinstance(row, Mapping):
            return row.get(name)

        return getattr(row, name, None)

    def get_object_label(self, row: Any) -> str:
        name = self.label_field or next(iter(self.columns))
        value = self.read(row, name)

        return force_str(value if value not in (None, "") else "")

    # -- other resources' rows --------------------------------------------

    def get_link(self, name: str) -> RowLink | None:
        """How the field ``name`` leads to another resource's row."""
        link = self.links.get(name)

        if isinstance(link, str):
            return RowLink(link)

        return link

    def get_linked_resource(self, link: RowLink) -> Any:
        target = self.site.get_data_resource(link.resource)

        if target is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__} links to the data resource "
                f"{link.resource!r}, which is not registered."
            )

        return target

    def get_related(self, name: str) -> RelatedRows | None:
        for relation in self.related_tables:
            if relation.name == name:
                return relation

        return None

    def get_related_resource(self, relation: RelatedRows) -> Any:
        target = self.site.get_data_resource(relation.resource)

        if target is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__}.related_tables: {relation.name!r} "
                f"names the data resource {relation.resource!r}, which is "
                f"not registered."
            )

        return target

    def check(self) -> None:
        """Every resource this one names exists: asked when the URLs are
        built, once every ``resources.py`` has registered its own."""
        for name in self.links:
            if name not in self.columns:
                raise ImproperlyConfigured(
                    f"{type(self).__name__}.links names {name!r}, which is "
                    f"not one of its columns."
                )

            self.get_linked_resource(self.get_link(name))

        for relation in self.related_tables:
            self.get_related_resource(relation)

            if not (relation.field or relation.rows):
                raise ImproperlyConfigured(
                    f"{type(self).__name__}.related_tables: "
                    f"{relation.name!r} needs a 'field' holding this "
                    f"row's key, or 'rows' fetching them."
                )

    def get_related_rows(
        self,
        request: Any,
        relation: RelatedRows,
        row: Any,
    ) -> list[Any]:
        """The rows of ``relation`` belonging to ``row``."""
        if relation.rows is not None:
            return list(relation.rows(request, row))

        target = self.get_related_resource(relation)
        key = force_str(self.read(row, self.key))

        return [
            candidate
            for candidate in target.get_rows(request)
            if any(
                value is not None and force_str(value) == key
                for value in values_at(candidate, relation.field)
            )
        ]

    def get_rows_related_to(self, request: Any, raw: str) -> list[Any]:
        """This resource's rows named by ``_related=<parent>.<tab>:<key>``.

        Resolved through the parent's declaration: the client names a
        tab, never a field to filter on.
        """
        label, _, key = raw.partition(":")
        parent_name, _, name = label.rpartition(".")
        parent = self.site.get_data_resource(parent_name)
        relation = parent.get_related(name) if parent is not None else None

        if relation is None or relation.resource != self.name:
            raise ValidationError(
                {RELATED_PARAM: [gettext("Unknown related table.")]}
            )

        if not parent.has_view_permission(request):
            raise PermissionDenied

        row = parent.get_row(request, key)

        if row is None:
            raise NotFound

        return parent.get_related_rows(request, relation, row)

    def get_related_tables(
        self, request: Any
    ) -> list[tuple[RelatedRows, Any]]:
        """The tabs this reader may see, each with its resource."""
        tables = []

        for relation in self.related_tables:
            target = self.get_related_resource(relation)

            if target.has_view_permission(request):
                tables.append((relation, target))

        return tables

    def get_related_table_config(
        self,
        request: Any,
        relation: RelatedRows,
        target: Any,
        row: Any,
    ) -> dict[str, Any]:
        """The related resource's own table, narrowed to ``row``."""
        key = force_str(self.read(row, self.key))
        config = target.get_table_config(request)
        # The column naming this row says the same thing on every line.
        pointing = {relation.field} | {
            name
            for name in target.links
            if target.get_link(name).resource == self.name
            and (target.get_link(name).key or name) == relation.field
        }
        columns = [
            column
            for column in config["columns"]
            if column.get("data") not in pointing
        ]

        if relation.columns is not None:
            shown = set(relation.columns)
            columns = [
                {**column, "visible": column.get("data") in shown}
                for column in columns
            ]

        options = dict(config["options"])
        options.update(
            stateKey=f"{options['stateKey']}.in.{self.name}.{relation.name}",
            syncUrl=False,
            extraParams={RELATED_PARAM: f"{self.name}.{relation.name}:{key}"},
            exportName=f"{target.name}-{self.name}-{key}",
        )

        if relation.page_length:
            options["pageLength"] = relation.page_length

        return {**config, "columns": columns, "options": options}

    # -- pages of its own ----------------------------------------------------
    #
    # ``generic.sites.pages``: what a row is, for the pages the project
    # declares - its key in the address, and how it is found.

    page_object_argument = "key"
    page_object_converter = "str"

    def get_page_object(self, request: Any, value: str) -> Any:
        row = self.get_row(request, value)

        if row is None:
            raise Http404

        return row

    def get_page_object_key(self, obj: Any) -> Any:
        if isinstance(obj, (str, int)):
            return obj

        return self.read(obj, self.key)

    # -- identity -------------------------------------------------------------

    @property
    def label_lower(self) -> str:
        """Stands where a model's ``app.model`` does."""
        return f"data.{self.name}"

    @property
    def url_prefix(self) -> str:
        return f"data_{self.name}"

    @property
    def state_key(self) -> str:
        return f"{self.site.name}.{self.label_lower}"

    def get_label(self) -> str:
        return force_str(self.label or prettify_field_name(self.name))

    def get_label_plural(self) -> str:
        return capfirst(force_str(self.label_plural or self.get_label()))

    def get_group(self) -> str:
        return force_str(self.group or "")

    def get_icon(self) -> str:
        return self.icon

    # -- permissions -------------------------------------------------------

    def has_view_permission(self, request: Any, row: Any = None) -> bool:
        user = getattr(request, "user", None)

        if user is None or not user.is_active or not user.is_authenticated:
            return False

        return self.permission is None or allows(user, self.permission)

    def has_module_permission(self, request: Any) -> bool:
        return self.has_view_permission(request)

    # Read only: nothing is added, changed or deleted here.
    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, row: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, row: Any = None) -> bool:
        return False

    # -- URLs -----------------------------------------------------------------

    def url_name(self, page: str) -> str:
        return f"{self.site.name}:{self.url_prefix}_{page}"

    def api_url_name(self, action: str = "list") -> str:
        return f"{self.site.name}:api_{self.url_prefix}-{action}"

    @staticmethod
    def _reverse(name: str, **kwargs: Any) -> str:
        try:
            return reverse(name, kwargs=kwargs or None)
        except NoReverseMatch:
            return ""

    def get_list_url(self) -> str:
        return self._reverse(self.url_name("list"))

    def get_add_url(self) -> str:
        return ""

    def get_detail_url(self, key: Any) -> str:
        return self._reverse(self.url_name("detail"), key=force_str(key))

    def get_object_url(self, key: Any) -> str:
        return self.get_detail_url(key)

    def get_row_url_template(self) -> str:
        """The row's page, its key left for the table to fill."""
        url = self._reverse(self.url_name("detail"), key=KEY_PLACEHOLDER)

        return url.replace(KEY_PLACEHOLDER, "{" + ROW_KEY + "}") if url else ""

    def get_api_url(self) -> str:
        return self._reverse(self.api_url_name("list"))

    def get_summary_api_url(self, key: Any) -> str:
        return self._reverse(self.api_url_name("summary"), pk=force_str(key))

    # -- the table ---------------------------------------------------------

    def get_table_serializer_class(self) -> Any:
        if self._serializer_class is None:
            attributes: dict[str, Any] = {
                name: column_for(name, declared)
                for name, declared in self.columns.items()
            }
            links = (
                list(self.list_display_links)
                if self.list_display_links is not None
                else list(self.columns)[:1]
            )
            template = self.get_row_url_template()

            attributes[ROW_KEY] = serializers.ReadOnlyField(source=self.key)

            # Hidden beside each link: the key of the row it leads to,
            # which the link's address is filled from.
            for name in self.links:
                attributes[LINK_KEY.format(name)] = serializers.ReadOnlyField(
                    source=self.get_link(name).key or name
                )

            attributes["datatable_overrides"] = {
                name: {"display_type": "link", "link_url": template}
                for name in links
                if template
                and name in attributes
                and name not in self.links
                and not isinstance(attributes[name], TagsColumn)
            }
            attributes["__module__"] = type(self).__module__

            self._serializer_class = type(
                f"{type(self).__name__}Serializer",
                (DataTableSerializer,),
                attributes,
            )

        return self._serializer_class

    def get_viewset_class(self) -> type[DataResourceViewSet]:
        return type(
            f"{type(self).__name__}ViewSet",
            (DataResourceViewSet,),
            {"resource": self, "__module__": type(self).__module__},
        )

    def get_page_size(self, request: Any) -> int:
        from generic.sites.resources import _preferences_for

        preferences = _preferences_for(request)

        if preferences is not None and preferences.table_page_size:
            return int(preferences.table_page_size)

        return self.list_per_page or generic_settings.TABLE_PAGE_SIZE

    def get_table_options(self, request: Any) -> dict[str, Any]:
        detail = self.get_row_url_template()
        options: dict[str, Any] = {
            "pageLength": self.get_page_size(request),
            "lengthMenu": [10, 15, 25, 50, 100],
            "stateKey": self.state_key,
            "columnSelector": True,
            "filters": True,
            "filterRow": filter_row_option(self),
            "excel": self.show_export,
            "csv": self.show_export,
            "copy": True,
            "print": True,
            "rowKey": ROW_KEY,
            "rowActions": [
                *(
                    [
                        {
                            "name": "open",
                            "label": gettext("Open"),
                            "icon": "article",
                            "url": detail,
                        }
                    ]
                    if detail
                    else []
                ),
                # The row's pages of the project's own, where asked for.
                *self.get_page_row_actions(request, "{" + ROW_KEY + "}"),
            ],
            "label": self.get_label(),
            "labelPlural": self.get_label_plural(),
            "exportName": self.name,
            "syncUrl": True,
            **saved_view_options(request, self.presets),
        }
        options.update(self.table_options)

        return options

    def get_table_config(self, request: Any) -> dict[str, Any]:
        columns = [
            dict(column)
            for column in (
                self.get_table_serializer_class().get_datatable_columns()
            )
        ]

        # A link to another resource's row, for whoever may open it.
        for column in columns:
            name = column.get("data")

            if name not in self.links:
                continue

            target = self.get_linked_resource(self.get_link(name))
            template = target.get_row_url_template()

            if template and target.has_view_permission(request):
                column.update(
                    type="link",
                    linkUrl=template.replace(
                        "{" + ROW_KEY + "}", "{" + LINK_KEY.format(name) + "}"
                    ),
                )

        return {
            "url": self.get_api_url(),
            "columns": columns,
            "options": self.get_table_options(request),
        }

    # -- a row's page ------------------------------------------------------

    def get_detail_fieldsets(self, request: Any) -> Any:
        if self.detail_fieldsets is not None:
            return self.detail_fieldsets

        return ((None, {"fields": tuple(self.columns)}),)

    def get_detail_stats(self, request: Any) -> Sequence[str]:
        return tuple(self.detail_stats)

    def describe(self, request: Any, row: Any, name: str) -> dict[str, Any]:
        """One value of the row, typed as its column says."""
        fields = self.get_table_serializer_class()().fields
        field = fields.get(name)
        value = (
            field.get_attribute(row)
            if field is not None and field.source != "*"
            else self.read(row, name)
        )
        entry = describe_row_value(self.site, request, field, value)

        if name in self.links and not entry.get("empty"):
            entry = self.describe_link(request, row, name, value)

        title = (
            field.resolve_title(name, field.datatable)
            if isinstance(field, DataTableFieldMixin)
            else prettify_field_name(name)
        )
        entry.update(name=name, label=capfirst(title))
        count = len(entry.get("items", ()))
        entry["wide"] = bool(
            entry.get("multiline")
            or (entry.get("type") == "tags" and count > 8)
        )

        return entry

    def describe_link(
        self,
        request: Any,
        row: Any,
        name: str,
        value: Any,
    ) -> dict[str, Any]:
        """A field naming another resource's row: a link to its page,
        for whoever may open it, and its text for anyone else."""
        link = self.get_link(name)
        target = self.get_linked_resource(link)
        key = self.read(row, link.key or name)
        url = (
            target.get_detail_url(key)
            if key not in (None, "") and target.has_view_permission(request)
            else ""
        )

        return {"type": "link", "display": force_str(value), "url": url}

    def build_sections(
        self,
        request: Any,
        row: Any,
        fieldsets: Any,
    ) -> list[dict[str, Any]]:
        """Sections of values, fieldsets style, as a summary draws them."""
        from generic.sites.serializers import flatten_fieldsets

        sections = []

        for index, (title, options) in enumerate(fieldsets):
            title = force_str(title or "")
            classes = tuple(options.get("classes", ()))

            sections.append(
                {
                    "name": slugify(title) or f"section-{index}",
                    "title": title,
                    "description": force_str(options.get("description", "")),
                    "collapsed": "collapse" in classes,
                    "fields": [
                        self.describe(request, row, name)
                        for name in flatten_fieldsets([(title, options)])
                    ],
                }
            )

        return sections

    def build_summary(self, request: Any, row: Any) -> dict[str, Any]:
        """What the row's page shows, shaped as a record's summary."""
        key = force_str(self.read(row, self.key))

        return {
            "object": {
                "pk": key,
                "label": self.get_object_label(row),
                "model": self.label_lower,
                "verboseName": self.get_label(),
                "icon": self.get_icon(),
            },
            "urls": {
                "summary": self.get_summary_api_url(key),
                "change": "",
                "delete": "",
                "list": self.get_list_url(),
                "actions": "",
            },
            "actions": [],
            "stats": [
                self.describe(request, row, name)
                for name in self.get_detail_stats(request)
            ],
            "sections": self.build_sections(
                request, row, self.get_detail_fieldsets(request)
            ),
            "related": [
                {
                    "name": relation.name,
                    "title": force_str(
                        relation.title or target.get_label_plural()
                    ),
                    "icon": relation.icon or target.get_icon(),
                    "description": force_str(relation.description),
                    "count": len(
                        self.get_related_rows(request, relation, row)
                    ),
                    "addUrl": "",
                }
                for relation, target in self.get_related_tables(request)
            ],
            "history": None,
            "topic": "",
        }


#: An address a value may be drawn as a link to.
URL_PATTERN = re.compile(r"^https?://\S+$")


def describe_row_value(
    site: Any,
    request: Any,
    field: Any,
    value: Any,
) -> dict[str, Any]:
    """A value of a row for its page, read as its column says: an API
    sends dates and numbers as text, the page shows them as such."""
    if isinstance(field, TagsColumn):
        items = field.to_representation(value) if value is not None else []

        if not items:
            return {"type": "tags", "empty": True}

        return {"type": "tags", "items": items, "more": 0}

    if isinstance(field, ChoiceColumn):
        if value is None or value == "":
            return {"type": "choice", "empty": True}

        return {
            "type": "choice",
            "value": force_str(value),
            "display": force_str(field.choices.get(value, value)),
        }

    if isinstance(field, BooleanColumn):
        return describe_value(site, request, as_bool(value), boolean=True)

    if isinstance(field, DateTimeColumn):
        return describe_value(site, request, as_datetime(value))

    if isinstance(field, DateColumn):
        return describe_value(site, request, as_date(value))

    if isinstance(field, (IntegerColumn, FloatColumn, DecimalColumn)):
        number = as_number(value)

        if number is None:
            return {"type": "number", "empty": True}

        places = getattr(field, "decimal_places", None)

        return {"type": "number", "display": format_number(number, places)}

    if isinstance(value, str) and URL_PATTERN.match(value):
        return {"type": "url", "display": value, "url": value}

    return describe_value(site, request, value)


__all__ = [
    "DataResource",
    "DataResourceViewSet",
    "RelatedRows",
    "RowLink",
    "column_for",
]

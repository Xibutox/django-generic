"""Tables of related records, on a record's summary page.

::

    class TeamResource(ModelResource):
        related_tables = (
            RelatedTable("tickets"),
            RelatedTable("agents", columns=("name", "email", "is_active")),
        )

    class CustomerResource(ModelResource):
        related_tables = (
            RelatedTable("tickets"),
            # Any path from the related model back to this one.
            RelatedTable(
                "time_entries",
                model=TimeEntry,
                lookup="ticket__customer",
                title=_("Time spent"),
            ),
        )

Each table is the related model's own table - its columns, filters,
search, exports, bulk actions and live updates - narrowed to the rows
belonging to the record. The rows come from the related resource's
endpoint with a ``_related`` parameter naming the relation; the
endpoint resolves that name through the declaration, so a client can
never filter on a path of its own choosing.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Sequence
from urllib.parse import urlencode

from django.contrib.admin.utils import lookup_spawns_duplicates
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.utils.encoding import force_str

#: Query parameter naming the relation a table is narrowed by:
#: ``<app>.<model>.<relation>:<pk of the record>``.
RELATED_PARAM = "_related"

#: Query parameter of an add page: where to go once the record is saved.
NEXT_PARAM = "_next"


@dataclasses.dataclass(frozen=True)
class RelatedTable:
    """Declare one table of related records."""

    #: A relation of the model - a reverse foreign key, or a
    #: many-to-many in either direction - by its accessor name. Any
    #: identifier when ``model`` and ``lookup`` are given.
    name: str
    model: Any = None
    #: ORM path from the related model back to the record.
    lookup: str | None = None
    title: Any = None
    icon: str | None = None
    description: Any = ""
    #: The columns shown at first; the others stay in the column picker.
    columns: Sequence[str] | None = None
    #: Leave out the column pointing back at the record, which would say
    #: the same thing on every row.
    hide_lookup_column: bool = True
    page_length: int | None = 10
    #: An "Add" button creating a related record with this one filled in.
    allow_add: bool = True
    #: Offer the related resource's ``editable_fields`` in this table.
    #: Off by default: a tab beside the record is usually read, and the
    #: page built for correcting rows is a different page.
    editable: bool = False
    #: Charts of the related resource drawn above the table, by name:
    #: narrowed to the record, and following the table's filters.
    charts: Sequence[str] = ()


@dataclasses.dataclass
class BoundRelatedTable:
    """A related table resolved against the resource it belongs to."""

    definition: RelatedTable
    parent: Any
    model: Any
    lookup: str
    #: The field of the related model an "Add" pre-fills, when the
    #: lookup is a single field pointing at the parent.
    prefill: str | None

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def key(self) -> str:
        """What the ``_related`` parameter names: the parent, then this."""
        return f"{self.parent.label_lower}.{self.name}"

    def get_resource(self) -> Any:
        return self.parent.site.get_resource(self.model)

    def get_title(self) -> str:
        if self.definition.title:
            return force_str(self.definition.title)

        resource = self.get_resource()

        if resource is not None:
            return resource.get_label_plural()

        return force_str(self.model._meta.verbose_name_plural).capitalize()

    def get_icon(self) -> str:
        if self.definition.icon:
            return self.definition.icon

        resource = self.get_resource()

        return resource.get_icon() if resource is not None else "table_rows"

    def is_visible(self, request: Any) -> bool:
        resource = self.get_resource()

        return resource is not None and resource.has_view_permission(request)

    def filter(self, queryset: Any, parent_pk: Any) -> Any:
        """The rows of ``queryset`` belonging to the record."""
        condition = {self.lookup: parent_pk}

        # Through a many-valued path a row could match twice.
        if lookup_spawns_duplicates(self.model._meta, self.lookup):
            matching = self.model._default_manager.filter(**condition)

            return queryset.filter(pk__in=matching.values("pk"))

        return queryset.filter(**condition)

    def count(self, request: Any, obj: Any) -> int:
        resource = self.get_resource()

        return self.filter(resource.get_queryset(request), obj.pk).count()

    def get_table_config(
        self,
        request: Any,
        obj: Any,
        editable: bool | None = None,
    ) -> dict[str, Any]:
        """The related resource's own table, narrowed to ``obj``.

        ``editable`` overrides the declaration, so the same relation
        can be read on the record's summary and corrected on a page
        built for it.
        """
        resource = self.get_resource()
        editable = self.definition.editable if editable is None else editable
        config = resource.get_table_config(request, editable=editable)
        columns = list(config["columns"])

        if self.definition.hide_lookup_column and self.prefill:
            columns = [
                column
                for column in columns
                if column.get("data") != self.prefill
            ]

        if self.definition.columns is not None:
            shown = set(self.definition.columns)
            columns = [
                {**column, "visible": column.get("data") in shown}
                for column in columns
            ]

        options = dict(config["options"])

        if editable:
            from generic.sites.grids import with_context

            # The cells and the new rows are written with the relation
            # named, so a new row belongs to the record at once.
            options = with_context(
                resource, request, options, self.context(obj.pk)
            )

        options.update(
            # Its own saved layout, apart from the main list's.
            stateKey=f"{options['stateKey']}.in.{self.key}",
            # Several tables share the page: none of them owns its address.
            syncUrl=False,
            extraParams={RELATED_PARAM: f"{self.key}:{obj.pk}"},
            exportName=(
                f"{resource.model_name}-{self.parent.model_name}-{obj.pk}"
            ),
        )

        if self.definition.page_length:
            options["pageLength"] = self.definition.page_length

        return {**config, "columns": columns, "options": options}

    def context(self, parent_pk: Any) -> Any:
        """What this table allows as a grid, for the record ``parent_pk``.

        A new row is added to the record: the field pointing at it is
        filled in, and not offered. Without such a field - a
        many-to-many, a longer path - there is nothing a new row could
        be attached by, so rows are not added here.
        """
        from generic.sites.editable import own_columns
        from generic.sites.grids import RowContext

        resource = self.get_resource()

        return RowContext(
            creatable=tuple(
                name for name in own_columns(resource) if name != self.prefill
            ),
            values={self.prefill: parent_pk} if self.prefill else {},
            allow_add=bool(self.definition.allow_add and self.prefill),
            narrow=lambda queryset: self.filter(queryset, parent_pk),
            query={RELATED_PARAM: f"{self.key}:{parent_pk}"},
        )

    def get_chart_config(
        self,
        request: Any,
        obj: Any,
        name: str,
        **overrides: Any,
    ) -> dict[str, Any] | None:
        """A chart of the related resource, narrowed to ``obj``."""
        resource = self.get_resource()

        if resource is None or not self.is_visible(request):
            return None

        return resource.get_chart_config(
            request,
            name,
            extraParams={RELATED_PARAM: f"{self.key}:{obj.pk}"},
            **overrides,
        )

    def get_chart_configs(self, request: Any, obj: Any) -> list[dict]:
        """The charts drawn above this table, following its filters."""
        configs = [
            self.get_chart_config(
                request,
                obj,
                name,
                table=f'table[data-related="{self.name}"]',
            )
            for name in self.definition.charts
        ]

        return [config for config in configs if config]

    def get_add_url(self, request: Any, obj: Any) -> str:
        """The related add page, with this record filled in."""
        resource = self.get_resource()

        if not (
            self.definition.allow_add
            and self.prefill
            and resource is not None
            and resource.has_add_permission(request)
        ):
            return ""

        url = resource.get_add_url()

        if not url:
            return ""

        back = self.parent.get_object_url(obj.pk)
        query = {self.prefill: obj.pk}

        if back:
            query[NEXT_PARAM] = f"{back}#related-{self.name}"

        return f"{url}?{urlencode(query)}"


def bind_related_table(definition: RelatedTable, parent: Any) -> Any:
    """Resolve ``definition`` against the resource declaring it."""
    owner = type(parent).__name__
    model = definition.model
    lookup = definition.lookup
    prefill = None

    if model is None:
        try:
            field = parent.model._meta.get_field(definition.name)
        except FieldDoesNotExist:
            raise ImproperlyConfigured(
                f"{owner}.related_tables names '{definition.name}', which "
                f"is not a relation of {parent.model.__name__}. Give "
                f"'model' and 'lookup' for any other path."
            ) from None

        if not (
            field.is_relation and (field.one_to_many or field.many_to_many)
        ):
            raise ImproperlyConfigured(
                f"{owner}.related_tables: '{definition.name}' holds a "
                f"single record, not a collection."
            )

        model = field.related_model

        # A reverse relation is created by Django; a many-to-many is
        # declared (and, having no column, is not "concrete" either).
        if not field.auto_created:
            # A many-to-many declared on the parent: the related model
            # reaches back through the reverse name.
            lookup = lookup or field.related_query_name()
        else:
            # A reverse relation: the key lives on the related model,
            # which is also the field an "Add" fills in.
            lookup = lookup or field.field.name
            prefill = field.field.name
    elif lookup is None:
        raise ImproperlyConfigured(
            f"{owner}.related_tables: '{definition.name}' gives a model "
            f"and so needs a 'lookup' back to {parent.model.__name__}."
        )
    elif "__" not in lookup:
        try:
            field = model._meta.get_field(lookup)
        except FieldDoesNotExist:
            field = None

        if (
            field is not None
            and field.concrete
            and field.is_relation
            and field.related_model is parent.model
        ):
            prefill = lookup

    return BoundRelatedTable(
        definition=definition,
        parent=parent,
        model=model,
        lookup=lookup,
        prefill=prefill,
    )

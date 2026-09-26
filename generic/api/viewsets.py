"""Ready made viewsets.

``DataTableViewSet``
    Read only list endpoint feeding a DataTable.

``AggregatedDataTableViewSet``
    Same, over a grouped and annotated queryset, where a row is not a
    model instance.

``ModelFormViewSet``
    Full CRUD driven by the form schema, with transactional inlines and
    a deletion preview.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from django.contrib.admin.utils import NestedObjects
from django.db import router, transaction
from django.db.models import QuerySet
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy as _
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from generic.api.exports import ExportMixin
from generic.api.facets import FacetMixin
from generic.api.filters import DATATABLE_FILTER_BACKENDS
from generic.api.inlines import (
    INLINE_PAYLOAD_KEY,
    InlineFormDefinition,
    InlineProcessor,
)
from generic.api.pagination import DataTablesPagination
from generic.api.renderers import DataTablesRenderer, GenericJSONRenderer
from generic.openapi import framework_schema


class DataTableViewSet(
    ExportMixin,
    FacetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Read only list endpoint feeding a DataTable.

    Filtering, searching, ordering and pagination are all resolved
    through the serializer's column declaration, so a subclass only has
    to describe *what* is selected.
    """

    #: drf-spectacular's inspector, taught these endpoints, when it is
    #: installed (generic.openapi); DRF's default otherwise.
    schema = framework_schema()

    http_method_names = ["get", "head", "options"]

    filter_backends = DATATABLE_FILTER_BACKENDS
    pagination_class = DataTablesPagination
    renderer_classes = (GenericJSONRenderer, DataTablesRenderer)
    permission_classes = (IsAuthenticated,)

    #: Report the unfiltered row count as ``recordsTotal``. Costs one
    #: extra COUNT per draw; switch it off on tables large enough for
    #: that to matter.
    table_total_count = True

    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        # Captured before the filter backends narrow the queryset, and
        # only for the table itself: an export has no use for it.
        if self.table_total_count and self.action == "list":
            self._table_total_count = queryset.count()

        return super().filter_queryset(queryset)

    @classmethod
    def get_datatable_columns(cls) -> list[dict[str, Any]]:
        """Column configuration for the template rendering the page."""
        return cls.serializer_class.get_datatable_columns()


class AggregatedDataTableViewSet(DataTableViewSet):
    """Table over a grouped, annotated queryset.

    A row here is a ``values()`` dictionary rather than a model
    instance, which is what lets one table span several models and
    aggregate across them. Subclasses describe the selection; the
    pipeline itself lives here::

        class ProjectsViewSet(AggregatedDataTableViewSet):
            serializer_class = ProjectsSerializer
            model = Projects
            base_exclusions = {"is_private": True}
            ordering = ("projet",)

            def get_values(self):
                return {"projet": F("name")}

            def get_aggregations(self):
                return {"temps_passe": Sum("tasks__time_spent")}
    """

    model: Any = None

    #: A row is a group, not a record: there are no values to count.
    facets_enabled = False

    #: Applied as ``exclude()`` before anything else, for rows this
    #: endpoint must never expose.
    base_exclusions: dict[str, Any] = {}

    #: Query parameter -> ORM lookup, applied before grouping.
    filter_parameters: dict[str, str] = {}

    #: One row per primary key unless a subclass groups differently.
    group_by_fields: tuple[str, ...] = ("pk",)

    ordering: tuple[str, ...] = ()

    def get_base_queryset(self) -> QuerySet:
        if self.model is None:
            raise NotImplementedError(
                f"{type(self).__name__} must define 'model' or override "
                f"get_base_queryset()."
            )

        return self.model.objects.exclude(**self.base_exclusions)

    def get_values(self) -> dict[str, Any]:
        """Public column name -> ORM expression."""
        return {}

    def get_aggregations(self) -> dict[str, Any]:
        """Public column name -> aggregate expression."""
        return {}

    def annotate_extra(self, queryset: QuerySet) -> QuerySet:
        """Annotations the values and aggregations rely on."""
        return queryset

    def apply_filters(
        self,
        queryset: QuerySet,
        request: Any,
    ) -> QuerySet:
        for parameter, lookup in self.filter_parameters.items():
            value = request.query_params.get(parameter)

            if value:
                queryset = queryset.filter(**{lookup: value})

        return queryset

    def get_queryset(self) -> QuerySet:
        queryset = self.get_base_queryset()
        queryset = self.apply_filters(queryset, self.request)
        queryset = self.annotate_extra(queryset)

        values = self.get_values()
        aggregations = self.get_aggregations()

        if self.group_by_fields:
            queryset = queryset.values(*self.group_by_fields).annotate(
                **values, **aggregations
            )
        else:
            queryset = queryset.values(**values)

            if aggregations:
                queryset = queryset.annotate(**aggregations)

        return queryset.order_by(*self.ordering)


def serialize_deletion_node(node: Any) -> Any:
    """Turn ``NestedObjects.nested()`` into JSON safe recursive data."""
    if isinstance(node, (list, tuple)):
        return [serialize_deletion_node(item) for item in node]

    meta = node._meta

    return {
        "model": meta.label_lower,
        "modelLabel": force_str(meta.verbose_name),
        "modelLabelPlural": force_str(meta.verbose_name_plural),
        "id": force_str(node.pk),
        "label": force_str(node),
    }


class InlineFormViewSetMixin:
    """Transactional tabular inlines on a ModelViewSet.

    The POST/PATCH payload may nest related rows::

        {
            ... parent fields ...,
            "_inlines": {
                "lines": [
                    {"id": 1, "label": "kept"},
                    {"id": 2, "_delete": true},
                    {"id": null, "label": "added"}
                ]
            }
        }

    Everything validates before anything is written, and the whole thing
    runs in one transaction.
    """

    inline_form_definitions: tuple[InlineFormDefinition, ...] = ()
    inline_payload_key = INLINE_PAYLOAD_KEY

    # -- configuration ------------------------------------------------

    def get_inline_form_definitions(
        self,
    ) -> tuple[InlineFormDefinition, ...]:
        return self.inline_form_definitions

    def get_inline_processor(self) -> InlineProcessor:
        return InlineProcessor(
            self.get_inline_form_definitions(),
            context=self.get_serializer_context(),
            payload_key=self.inline_payload_key,
        )

    # -- payload ------------------------------------------------------

    def split_parent_and_inline_data(
        self,
        data: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        parent_data = deepcopy(dict(data))
        inline_data = parent_data.pop(self.inline_payload_key, {})

        if inline_data in (None, ""):
            return parent_data, {}

        # A multipart request - a form carrying file uploads - can only
        # send the nested rows as a JSON string.
        if isinstance(inline_data, str):
            try:
                inline_data = json.loads(inline_data)
            except json.JSONDecodeError as error:
                raise ValidationError(
                    {self.inline_payload_key: [_("Invalid JSON payload.")]}
                ) from error

        if not isinstance(inline_data, dict):
            raise ValidationError(
                {self.inline_payload_key: [_("A JSON object is expected.")]}
            )

        return parent_data, inline_data

    def build_response_data(
        self,
        parent: Any,
        processor: InlineProcessor,
    ) -> dict[str, Any]:
        data = dict(self.get_serializer(parent).data)
        data[self.inline_payload_key] = processor.serialize(parent)

        return data

    # -- actions ------------------------------------------------------

    def retrieve(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        return Response(
            self.build_response_data(
                instance,
                self.get_inline_processor(),
            )
        )

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        parent_data, inline_data = self.split_parent_and_inline_data(
            request.data
        )

        serializer = self.get_serializer(data=parent_data)
        serializer.is_valid(raise_exception=True)

        processor = self.get_inline_processor()

        with transaction.atomic():
            # The parent is written first so the rows can be validated
            # against it: a constraint spanning the parent - a unique
            # position within a book, say - cannot be checked without
            # one. A rejected row raises out of the block, which rolls
            # the parent back with it.
            self.perform_create(serializer)
            parent = serializer.instance

            processor.apply(parent=parent, inline_data=inline_data)

        data = self.build_response_data(parent, processor)

        return Response(
            data,
            status=status.HTTP_201_CREATED,
            headers=self.get_success_headers(serializer.data),
        )

    def update(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        parent_data, inline_data = self.split_parent_and_inline_data(
            request.data
        )

        serializer = self.get_serializer(
            instance,
            data=parent_data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        processor = self.get_inline_processor()

        with transaction.atomic():
            self.perform_update(serializer)
            parent = serializer.instance

            processor.apply(parent=parent, inline_data=inline_data)

        return Response(self.build_response_data(parent, processor))

    def partial_update(
        self,
        request: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        kwargs["partial"] = True

        return self.update(request, *args, **kwargs)


class FormSchemaViewSetMixin(InlineFormViewSetMixin):
    """Expose the form schema and the deletion preview."""

    form_titles = {
        "create": _("Create a record"),
        "update": _("Edit the record"),
        "delete": _("Delete the record"),
    }
    form_descriptions = {
        "create": _("Fill in the information, then save."),
        "update": _("Change the information, then save."),
        "delete": _(
            "Review the consequences below before confirming the " "deletion."
        ),
    }
    form_submit_labels = {
        "create": _("Create"),
        "update": _("Save"),
        "delete": _("Confirm deletion"),
    }

    form_modes = ("create", "update", "delete")

    def get_form_schema_data(self, request: Any) -> dict[str, Any]:
        serializer_class = self.get_serializer_class()
        schema = serializer_class.get_form_schema(request=request)
        schema["inlines"] = self.get_inline_processor().get_schemas(
            request=request
        )

        return schema

    @action(detail=False, methods=["get"], url_path="form-schema")
    def form_schema(self, request: Any) -> Response:
        mode = request.query_params.get("mode", "update")

        if mode not in self.form_modes:
            mode = "update"

        schema = self.get_form_schema_data(request)
        schema.update(
            {
                "mode": mode,
                "title": str(self.form_titles[mode]),
                "description": str(self.form_descriptions[mode]),
                "submitLabel": str(self.form_submit_labels[mode]),
            }
        )

        return Response(schema)

    @action(detail=True, methods=["get"], url_path="deletion-preview")
    def deletion_preview(
        self,
        request: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        instance = self.get_object()
        database = router.db_for_write(type(instance), instance=instance)
        collector = NestedObjects(using=database, origin=instance)

        try:
            collector.collect([instance])
        except (ProtectedError, RestrictedError) as error:
            protected = list(
                getattr(error, "protected_objects", None)
                or getattr(error, "restricted_objects", None)
                or []
            )

            return Response(
                {
                    "canDelete": False,
                    "object": serialize_deletion_node(instance),
                    "nested": [],
                    "protected": [
                        serialize_deletion_node(item) for item in protected
                    ],
                }
            )

        protected = list(collector.protected)

        return Response(
            {
                "canDelete": not protected,
                "object": serialize_deletion_node(instance),
                "nested": serialize_deletion_node(collector.nested()),
                "protected": [
                    serialize_deletion_node(item) for item in protected
                ],
            }
        )


class ModelFormViewSet(
    FormSchemaViewSetMixin,
    viewsets.ModelViewSet,
):
    """CRUD endpoint driven by the form schema.

    Pairs with the frontend editor: the page fetches ``form-schema``,
    renders the form, and submits back here.
    """

    #: drf-spectacular's inspector, taught these endpoints, when it is
    #: installed (generic.openapi); DRF's default otherwise.
    schema = framework_schema()

    permission_classes = (IsAuthenticated,)

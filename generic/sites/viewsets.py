"""One DRF endpoint per resource.

Every generated screen talks to it, and so can anything else:

==========================  ======================================
``GET    api/<app>/<model>/``            rows, in the DataTables protocol
``POST   api/<app>/<model>/``            create, with ``_inlines``
                                        (JSON, or ``_payload`` + files)
``GET    api/<app>/<model>/<pk>/``       one record, with its inlines
``PATCH  api/<app>/<model>/<pk>/``       update, with ``_inlines``
``DELETE api/<app>/<model>/<pk>/``       delete, refused when protected
``GET    .../<pk>/summary/``             the record's summary, as JSON
``GET    .../<pk>/history/``             its versions, newest first
``GET    .../<pk>/files/<field>/``       one of its files, downloaded
``PATCH  .../<pk>/cells/``               cells edited in the table itself
``POST   api/<app>/<model>/rows/``       a row added in a grid
``GET    .../form-schema/``              the form, as JSON
``GET    .../<pk>/deletion-preview/``    what a delete would take with it
``GET    .../export/``, ``export-csv/``  every filtered row
``POST   .../actions/``                  run a bulk action
``GET    .../autocomplete/``             Select2 results
``GET    .../charts/<name>/``            one declared chart's data
``GET    .../trees/<name>/``             one level of a declared tree
==========================  ======================================

The table endpoints - and the charts - also take ``_related``, which
narrows the rows to one record's, for a table on that record's summary
page, and ``_grid``, which narrows them to a declared grid's. The grid
writes - ``cells`` and ``rows`` - take them too, and read from them
what the grid allows.

The resource decides everything: the queryset, both serializers, the
permissions, the actions.
"""

from __future__ import annotations

import json
import posixpath
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, HttpResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from generic.api.exports import ExportMixin
from generic.api.facets import FacetMixin
from generic.api.files import FILE_URL
from generic.api.filters import DATATABLE_FILTER_BACKENDS, apply_search
from generic.api.pagination import DataTablesPagination
from generic.api.renderers import DataTablesRenderer, GenericJSONRenderer
from generic.api.viewsets import FORM_PARSERS, FormSchemaViewSetMixin
from generic.conf import generic_settings
from generic.openapi import framework_schema
from generic.reports import Report
from generic.sites.grids import ARGUMENT_ERRORS, GRID_PARAM
from generic.sites.related import RELATED_PARAM
from generic.views.delete import collect_deletion_summary

#: Upper bound on the primary keys one bulk action request may name.
MAX_SELECTED = 5000

#: Actions reading the table: they get the table serializer, the
#: filter backends and the list queryset.
TABLE_ACTIONS = frozenset(
    {"list", "export", "export_csv", "run_action", "chart", "facets", "tree"}
)


#: What narrows a table: the filter tree (and its older form), the
#: search box.
TABLE_FILTER_PARAMS = (
    "filters",
    "advanced_filters",
    "search",
    "search[value]",
)


def is_local_path(url: str) -> bool:
    """``/documents/merge/``, not ``//elsewhere`` nor ``https://...``."""
    return url.startswith("/") and url_has_allowed_host_and_scheme(
        url, allowed_hosts=None
    )


class ResourcePermission(BasePermission):
    """Map each endpoint action onto the resource's permission methods."""

    def has_permission(self, request: Any, view: Any) -> bool:
        user = request.user

        if not (user and user.is_authenticated):
            return False

        resource = view.resource
        name = view.action

        if name in ("create", "rows"):
            return resource.has_add_permission(request)

        # Declared, and allowed to write what the declaration writes:
        # the import itself checks each row again.
        if name in ("import_rows", "import_schema", "import_template"):
            return resource.can_import(request)

        if name in ("update", "partial_update", "cells", "take_transition"):
            return resource.has_change_permission(request)

        if name == "destroy":
            return resource.has_delete_permission(request)

        if name == "form_schema":
            return resource.has_view_permission(request) or (
                resource.has_add_permission(request)
            )

        # Reading, and bulk actions, which check their own permission.
        return resource.has_view_permission(request)

    def has_object_permission(
        self,
        request: Any,
        view: Any,
        obj: Any,
    ) -> bool:
        resource = view.resource
        name = view.action

        if name in ("update", "partial_update", "cells"):
            return resource.has_change_permission(request, obj)

        if name == "destroy":
            return resource.has_delete_permission(request, obj)

        return resource.has_view_permission(request, obj)


class ResourceViewSet(
    ExportMixin,
    FacetMixin,
    FormSchemaViewSetMixin,
    viewsets.ModelViewSet,
):
    """The endpoint behind a registered resource.

    ``resource`` is filled in per model by
    :meth:`ModelResource.get_viewset_class`.
    """

    #: drf-spectacular's inspector, taught these endpoints, when it is
    #: installed (generic.openapi); DRF's default otherwise.
    schema = framework_schema()

    resource: Any = None

    filter_backends = DATATABLE_FILTER_BACKENDS
    pagination_class = DataTablesPagination
    renderer_classes = (GenericJSONRenderer, DataTablesRenderer)
    permission_classes = (ResourcePermission,)
    # A form with a new file sends its JSON as ``_payload`` beside one
    # part per file (generic.api.parsers); the import keeps its own.
    parser_classes = FORM_PARSERS
    lookup_value_regex = "[^/]+"

    @property
    def table_total_count(self) -> bool:  # type: ignore[override]
        return bool(self.resource.show_full_result_count)

    @property
    def export_file_name(self) -> str:  # type: ignore[override]
        return str(self.resource.model_name)

    # -- data -----------------------------------------------------------

    def get_queryset(self) -> Any:
        if self.action in TABLE_ACTIONS:
            return self.resource.get_list_queryset(self.request)

        return self.resource.get_queryset(self.request)

    def filter_queryset(self, queryset: Any) -> Any:
        # The table filters only ever apply to the table. Retrieving or
        # updating one record must not depend on a stray query string.
        if self.action not in TABLE_ACTIONS:
            return queryset

        # Before the count: a related table's total is the record's rows,
        # a grid's the rows it was declared over.
        queryset = self.filter_related(queryset)
        queryset = self.filter_grid(queryset)

        if self.action == "list" and self.table_total_count:
            self._table_total_count = queryset.count()

        return super().filter_queryset(queryset)

    def get_related(self) -> tuple[Any, Any] | None:
        """The related table ``_related`` names, and the record's key.

        The parameter names a relation declared on that record's
        resource - never an ORM path - and the record must be one the
        user may see.
        """
        raw = self.request.query_params.get(RELATED_PARAM)

        if not raw:
            return None

        key, _, parent_pk = raw.rpartition(":")
        related = self.resource.site.get_related_table(key)

        if related is None or related.model is not self.resource.model:
            raise NotFound(gettext("There is no such related table."))

        parent = related.parent

        if not parent.has_view_permission(self.request):
            raise PermissionDenied

        try:
            exists = (
                parent.get_queryset(self.request).filter(pk=parent_pk).exists()
            )
        except (TypeError, ValueError, DjangoValidationError):
            exists = False

        if not exists:
            raise NotFound

        return related, parent_pk

    def filter_related(self, queryset: Any) -> Any:
        """Narrow the rows to one record's, for its summary page."""
        found = self.get_related()

        if found is None:
            return queryset

        related, parent_pk = found

        return related.filter(queryset, parent_pk)

    def get_grid(self) -> tuple[Any, str] | None:
        """The grid ``_grid`` names, and its argument.

        A name the resource declares - never a path - and the argument
        as the browser sent it, which the grid's own scope checks.
        """
        raw = self.request.query_params.get(GRID_PARAM)

        if not raw:
            return None

        key, _, argument = raw.partition(":")
        grid = self.resource.site.get_grid(key)

        if grid is None or grid.resource is not self.resource:
            raise NotFound(gettext("There is no such grid."))

        return grid, argument

    def filter_grid(self, queryset: Any) -> Any:
        """Narrow the rows to a declared grid's."""
        found = self.get_grid()

        if found is None:
            return queryset

        grid, argument = found

        try:
            return grid.filter(self.request, queryset, argument)
        except ARGUMENT_ERRORS:
            # An argument the scope cannot read names nothing.
            raise NotFound

    def get_row_context(self) -> Any:
        """What the grid behind this request allows it to write."""
        from generic.sites.editable import default_context

        found = self.get_grid()

        if found is not None:
            grid, argument = found

            try:
                grid.check(self.request, argument)

                return grid.context(self.request, argument)
            except ARGUMENT_ERRORS:
                raise NotFound

        related = self.get_related()

        if related is not None:
            table, parent_pk = related

            return table.context(parent_pk)

        return default_context(self.resource)

    def get_serializer_context(self) -> dict[str, Any]:
        from generic.sites.files import file_url_resolver

        context = super().get_serializer_context()
        # A file reads as {name, url, size}, the url this endpoint's
        # own download - or the one of whichever record it belongs to.
        context[FILE_URL] = file_url_resolver(self.resource.site, self.request)

        return context

    def get_serializer_class(self) -> Any:
        if self.action in TABLE_ACTIONS:
            return self.resource.get_rows_serializer_class(self.request)

        return self.resource.get_form_serializer_class()

    def get_table_search_fields(self) -> list[str]:
        """The resource's own search fields, when it declares any."""
        fields = self.resource.get_search_fields(self.request)

        if fields:
            return list(fields)

        return self.resource.get_table_serializer_class().get_search_fields()

    def get_inline_form_definitions(self) -> Any:
        return self.resource.get_inline_definitions(self.request)

    # -- writes ----------------------------------------------------------

    def perform_create(self, serializer: Any) -> None:
        self.resource.save_model(self.request, serializer, change=False)

    def perform_update(self, serializer: Any) -> None:
        self.resource.save_model(self.request, serializer, change=True)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        summary = collect_deletion_summary(instance)

        # Refused with the reason rather than failing with a 500 on the
        # database's protected-foreign-key error.
        if not summary["can_delete"]:
            return Response(
                {
                    "detail": gettext(
                        "%(name)s cannot be deleted because other "
                        "records depend on it."
                    )
                    % {"name": instance},
                    "protected": summary["protected"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        self.resource.delete_model(request, instance)

        return Response(status=status.HTTP_204_NO_CONTENT)

    # -- summary -----------------------------------------------------------

    @action(
        detail=True,
        methods=["get"],
        url_path="summary",
        url_name="summary",
    )
    def summary(self, request: Any, pk: Any = None) -> Response:
        """What the record's summary page shows, as JSON."""
        from generic.sites.summary import build_summary

        record = self.get_object()

        if self.resource.access_log:
            from generic.access import record as record_access

            record_access(request, record, action="viewed")

        return Response(build_summary(self.resource, request, record))

    # -- files -------------------------------------------------------------

    @action(
        detail=True,
        methods=["get"],
        url_path=r"files/(?P<field>[A-Za-z0-9_]+)",
        url_name="file",
    )
    def download_file(
        self,
        request: Any,
        pk: Any = None,
        field: str = "",
    ) -> Any:
        """One of the record's files, for a reader who may see the record.

        Only a file field the resource shows this reader answers; an
        empty one, or one the storage no longer holds, is a 404.
        """
        from generic.sites.files import file_response, is_stored

        if field not in self.resource.get_file_fields(request):
            raise NotFound(gettext("There is no such file."))

        record = self.get_object()
        value = getattr(record, field)

        if not is_stored(value) or not self.resource.may_download(
            request, record, field
        ):
            raise NotFound(gettext("There is no such file."))

        name = self.resource.get_download_name(request, record, field)

        try:
            response = file_response(value, name)
        except OSError:
            # Gone between the check and the opening.
            raise NotFound(gettext("There is no such file."))

        if self.resource.access_log:
            from generic.access import record as record_access
            from generic.api.files import file_name

            record_access(
                request,
                record,
                action="downloaded",
                detail=name or posixpath.basename(file_name(value)),
            )

        return response

    def finalize_response(
        self,
        request: Any,
        response: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        response = super().finalize_response(
            request, response, *args, **kwargs
        )

        action_name = getattr(self, "action", None)

        # Refusals too: whatever this address answers, nothing in it
        # may run in the site's origin.
        if action_name == "download_file":
            from generic.sites.files import protect

            protect(response)

        # What a delete takes with it is moot when it goes to a trash:
        # the dialog says so instead.
        if (
            action_name == "deletion_preview"
            and self.resource.trash
            and isinstance(getattr(response, "data", None), dict)
        ):
            response.data["trash"] = True

        return response

    # -- cells edited in the table ------------------------------------------

    @action(
        detail=True,
        methods=["patch"],
        url_path="cells",
        url_name="cells",
    )
    def cells(self, request: Any, pk: Any = None) -> Response:
        """Write the cells a reader edited in the table itself.

        The body is keyed by public column name, so one row may carry
        fields of several models; the resource resolves each one. The
        answer is the row as the table would draw it now, because a
        change often moves more than the cell it was typed in.
        """
        resource = self.resource

        if not resource.editable_fields:
            raise NotFound(gettext("This table has no editable columns."))

        record = self.get_object()
        changes = request.data

        if not isinstance(changes, dict) or not changes:
            raise ValidationError(
                gettext("Send the columns to change, and their values.")
            )

        # A grid may write fewer columns than the resource offers. Its
        # scope is not checked: it says which rows are shown, and a row
        # corrected out of it - a ticket just closed - stays writable
        # for whoever may change it.
        found = self.get_grid()
        allowed = found[0].editable_names() if found else None

        if allowed is not None:
            refused = [name for name in changes if name not in allowed]

            if refused:
                raise ValidationError(
                    {
                        name: [gettext("This grid does not edit this column.")]
                        for name in refused
                    }
                )

        resource.save_editable(request, record, changes)

        # Read back through the list queryset: a computed column is an
        # annotation, and the row has just changed underneath it.
        row = resource.get_list_queryset(request).filter(pk=record.pk).first()

        if row is None:  # pragma: no cover - the row left its own table
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = resource.get_table_serializer_class()(
            row,
            context=self.get_serializer_context(),
        )

        return Response(serializer.data)

    @action(
        detail=False,
        methods=["post"],
        url_path="rows",
        url_name="rows",
    )
    def rows(self, request: Any) -> Response:
        """Create the record of a row added in a grid.

        The body is the row's cells, by public column name. Which
        columns a new row may write, and what it gets without asking -
        the record it belongs to - come from the grid named in the
        query string, never from the body. The answer is the new row,
        as the table draws it.
        """
        resource = self.resource
        context = self.get_row_context()
        values = request.data

        if not context.allow_add:
            raise PermissionDenied(
                gettext("Rows cannot be added to this table.")
            )

        # Empty is a row like another: the validation says, under each
        # cell, what it still needs.
        if not isinstance(values, dict):
            raise ValidationError(gettext("Send the new row's columns."))

        writable = {
            name
            for name in context.creatable
            if resource.can_edit_column(request, name, None)
        }
        refused = [name for name in values if name not in writable]

        if refused:
            raise ValidationError(
                {
                    name: [gettext("A new row cannot set this column.")]
                    for name in refused
                }
            )

        try:
            record = resource.create_editable(
                request,
                dict(values),
                dict(context.values),
            )
        except ValidationError as error:
            from generic.sites.editable import row_errors

            # Under the cell that shows each field - left empty, it was
            # not sent - and the rest for the whole row.
            raise ValidationError(
                row_errors(resource, error.detail, writable)
            ) from error
        row = resource.get_list_queryset(request).filter(pk=record.pk).first()
        data = (
            resource.get_table_serializer_class()(
                row,
                context=self.get_serializer_context(),
            ).data
            if row is not None
            else {}
        )

        return Response(data, status=status.HTTP_201_CREATED)

    # -- history -----------------------------------------------------------

    @action(
        detail=True,
        methods=["get"],
        url_path="history",
        url_name="history",
    )
    def history(self, request: Any, pk: Any = None) -> Response:
        """What happened to this record, newest first.

        Whoever may read the record may read its history: it says what
        its own fields were, and nothing else.
        """
        from generic.history.reading import build_history
        from generic.history.recording import is_recorded

        if not is_recorded(self.resource):
            raise NotFound(gettext("This model keeps no history."))

        record = self.get_object()

        return Response(
            build_history(
                self.resource,
                request,
                record,
                limit=request.query_params.get("limit"),
                offset=request.query_params.get("offset", 0),
            )
        )

    # -- charts ------------------------------------------------------------

    @action(
        detail=False,
        methods=["get"],
        url_path=r"charts/(?P<chart>[A-Za-z0-9_-]+)",
        url_name="chart",
    )
    def chart(self, request: Any, chart: str = "") -> Response:
        """One declared chart, over the rows the table would show.

        The table's own parameters apply - ``advanced_filters``,
        ``search``, ``_related`` - plus ``period`` for a date dimension.
        """
        definition = self.resource.get_chart(chart)

        if definition is None or not definition.is_visible(
            request, self.resource
        ):
            raise NotFound(gettext("There is no such chart."))

        period = request.query_params.get("period") or None

        if period is not None and period not in definition.get_periods():
            raise ValidationError(
                {"period": [gettext("This period is not offered.")]}
            )

        # Aggregated over the plain queryset, selected by key: the
        # table's annotations and joins would count rows twice.
        matching = self.filter_queryset(self.get_queryset())
        queryset = self.resource.get_queryset(request).filter(
            pk__in=matching.values("pk")
        )

        return Response(
            definition.get_payload(self.resource, request, queryset, period)
        )

    # -- trees -------------------------------------------------------------

    @action(
        detail=False,
        methods=["get"],
        url_path=r"trees/(?P<tree>[a-z0-9-]+)",
        url_name="tree",
    )
    def tree(self, request: Any, tree: str = "") -> Response:
        """One level of a declared tree, a page of it.

        ``node`` (none: the roots), ``root``, ``direction``, ``offset``,
        ``limit``, ``q``, ``path`` and ``find`` - see
        ``BoundTree.answer``. The tree resolves every record through the
        resources' querysets.

        The table's own parameters - ``filters``, ``search`` - search
        every level for the records the table would show.
        """
        bound = self.resource.get_tree(tree)

        if bound is None:
            raise NotFound(gettext("There is no such tree."))

        params = request.query_params
        matching = None

        if any(
            (params.get(name) or "").strip() for name in TABLE_FILTER_PARAMS
        ):
            matching = self.filter_queryset(self.get_queryset()).values("pk")

        return Response(bound.answer(request, params, matching))

    # -- bulk actions ------------------------------------------------------

    @action(
        detail=False,
        methods=["post"],
        url_path="actions",
        url_name="actions",
    )
    def run_action(self, request: Any) -> Response:
        """Run one bulk action.

        The selection is either explicit - ``{"ids": [...]}`` - or every
        row the table currently shows: ``{"all": true}``, with the
        table's own filter parameters in the query string.
        """
        name = request.data.get("action")
        entry = self.resource.get_actions(request).get(name)

        if entry is None:
            return Response(
                {"detail": gettext("This action is not available.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if request.data.get("all"):
            # Re-selected by primary key from the plain queryset: the
            # table's annotations and joins are there to display rows,
            # and an update() must not have to carry them.
            matching = self.filter_queryset(self.get_queryset())
            queryset = self.resource.get_queryset(request).filter(
                pk__in=matching.values("pk")
            )
        else:
            ids = request.data.get("ids")

            if not isinstance(ids, list) or len(ids) > MAX_SELECTED:
                return Response(
                    {"detail": gettext("Invalid selection.")},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            queryset = self.resource.get_queryset(request).filter(
                pk__in=[str(value) for value in ids]
            )

        count = queryset.count()

        if not count:
            return Response(
                {"detail": gettext("Nothing was selected.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = entry.function(request, queryset)

        if isinstance(result, Response):
            return result

        return Response(self.describe_result(result, count, entry))

    @staticmethod
    def describe_result(result: Any, count: int, entry: Any) -> dict:
        from generic.tasks.models import TaskRun
        from generic.tasks.operations import operation_payload

        # The work behind the action, with what it had to say: a report
        # tree, or a run that may still be going (generic.tasks).
        if isinstance(result, (Report, TaskRun)):
            return {**operation_payload(result), "count": count}

        if isinstance(result, dict) and isinstance(
            result.get("report"), Report
        ):
            payload = operation_payload(
                result["report"], result.get("message", "")
            )

            return {**payload, "count": count}

        if isinstance(result, dict):
            payload = {
                "message": str(result.get("message", "")),
                "level": result.get("level", "success"),
                "count": count,
            }
            redirect = str(result.get("redirect") or "")

            # A page of this site to open next - a form the selection
            # fills in, say. Never another site's.
            if redirect and not is_local_path(redirect):
                raise ValueError(
                    f"Action {entry.name!r} redirects to {redirect!r}: "
                    f"an action opens a page of this site only."
                )

            if redirect:
                payload["redirect"] = redirect

            return payload

        message = (
            str(result)
            if result
            else gettext("%(action)s: %(count)s row(s) processed.")
            % {"action": entry.description, "count": count}
        )

        return {"message": message, "level": "success", "count": count}

    # -- transitions -------------------------------------------------------

    @action(
        detail=True,
        methods=["get"],
        url_path="transitions",
        url_name="transitions",
    )
    def list_transitions(self, request: Any, pk: Any = None) -> Response:
        """What this reader may do to this record's state, now."""
        resource = self.resource

        if not resource.get_transitions():
            raise Http404

        obj = self.get_object()

        return Response(
            [
                info.describe(resource, obj)
                for info in resource.get_available_transitions(request, obj)
            ]
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"transitions/(?P<transition>[A-Za-z0-9_]+)",
        url_name="take-transition",
    )
    def take_transition(
        self,
        request: Any,
        pk: Any = None,
        transition: str = "",
    ) -> Response:
        """Run one: the body carries the fields it asks for, if any.

        Answers the record's summary, as its page reads it.
        """
        from generic.sites.summary import build_summary
        from generic.sites.transitions import TransitionRefused, take

        resource = self.resource
        # Found through the queryset first: a record out of reach is a
        # 404 like any other, before its state is looked at.
        obj = self.get_object()
        values = request.data if isinstance(request.data, dict) else {}

        try:
            obj = take(resource, request, obj.pk, transition, values)
        except TransitionRefused as refusal:
            return Response({"detail": refusal.message}, status=refusal.status)

        return Response(build_summary(resource, request, obj))

    # -- imports -----------------------------------------------------------

    def get_importer(self) -> Any:
        importer = self.resource.get_importer(self.request)

        if importer is None:
            raise Http404

        return importer

    @action(
        detail=False,
        methods=["get"],
        url_path="import/schema",
        url_name="import-schema",
    )
    def import_schema(self, request: Any) -> Response:
        """What a file may fill, and how - before any file is chosen."""
        return Response(self.get_importer().describe())

    @action(
        detail=False,
        methods=["get"],
        url_path="import/template",
        url_name="import-template",
    )
    def import_template(self, request: Any) -> Any:
        """An empty workbook with the right headers."""
        importer = self.get_importer()

        try:
            content = importer.template()
        except ImportError:
            return Response(
                {"detail": gettext("Excel files cannot be written here.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response = HttpResponse(
            content,
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{self.resource.model_name}-import.xlsx"'
        )

        return response

    @action(
        detail=False,
        methods=["post"],
        url_path="import",
        url_name="import-rows",
        parser_classes=(MultiPartParser, FormParser),
    )
    def import_rows(self, request: Any) -> Response:
        """Read a file: a preview, or - with ``commit`` - the import.

        Multipart: ``file``, ``mapping`` (JSON list, one column name or
        null per header of the file), ``commit`` (``true`` to write).
        """
        from generic.sites.imports import ImportRefused

        importer = self.get_importer()
        upload = request.FILES.get("file")

        if upload is None:
            return Response(
                {"detail": gettext("Choose a file to import.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_mapping = request.data.get("mapping")

        try:
            mapping = json.loads(raw_mapping) if raw_mapping else None
        except ValueError:
            return Response(
                {
                    "detail": gettext(
                        "The columns chosen do not match the file."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        commit = str(request.data.get("commit", "")).lower() in (
            "1",
            "true",
            "yes",
        )

        try:
            result = importer.run(upload, mapping, commit=commit)
        except ImportRefused as refusal:
            return Response(
                {"detail": refusal.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(result)

    # -- autocomplete ------------------------------------------------------

    @action(
        detail=False,
        methods=["get"],
        url_path="autocomplete",
        url_name="autocomplete",
    )
    def autocomplete(self, request: Any) -> Response:
        """Select2 results: ``?q=`` to search, ``?ids=1,2`` to label.

        The second form is how a form labels values it already holds
        without embedding the related table.
        """
        resource = self.resource
        queryset = resource.get_autocomplete_queryset(request)

        raw_ids = request.query_params.get("ids")

        if raw_ids is not None:
            values = [value for value in raw_ids.split(",") if value][:100]
            rows = list(queryset.filter(pk__in=values)) if values else []

            return Response(
                {
                    "results": [self.serialize_option(row) for row in rows],
                    "pagination": {"more": False},
                }
            )

        term = (
            request.query_params.get("q")
            or request.query_params.get("term")
            or ""
        ).strip()

        if len(term) < generic_settings.AUTOCOMPLETE_MIN_INPUT_LENGTH:
            return Response({"results": [], "pagination": {"more": False}})

        queryset = resource.rank_search_results(
            request,
            apply_search(queryset, resource.get_search_fields(request), term),
            term,
        )

        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1

        size = generic_settings.AUTOCOMPLETE_PAGE_SIZE
        offset = (page - 1) * size

        # One extra row tells Select2 whether to keep scrolling, without
        # paying for a COUNT.
        rows = list(queryset[offset : offset + size + 1])

        return Response(
            {
                "results": [self.serialize_option(row) for row in rows[:size]],
                "pagination": {"more": len(rows) > size},
            }
        )

    def serialize_option(self, row: Any) -> dict[str, Any]:
        return {"id": row.pk, "text": self.resource.get_object_label(row)}

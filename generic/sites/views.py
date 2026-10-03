"""Pages generated for the site and its resources.

Each page is a thin Django view: it checks the permission, names the
page and hands the browser a configuration. The rows, the form and every
write then go through the resource's DRF endpoint.
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_str
from django.utils.translation import gettext
from django.views.generic import TemplateView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from generic.openapi import framework_schema
from generic.views.delete import GenericDeleteView
from generic.views.mixins import POPUP_PARAM, PageMixin
from generic.views.toolbar import Breadcrumb, ToolbarItem

#: Query parameter carrying the id of a relation popup's request, so
#: the page that opened it knows which field to update.
RELATION_REQUEST_PARAM = "_relation_request"


class SiteViewMixin(PageMixin):
    """Pages belonging to a site: signed-in users only."""

    site: Any = None

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                self.site.get_login_url(),
            )

        if not self.has_permission():
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)

    def has_permission(self) -> bool:
        return True

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["generic_site"] = self.site

        return context


class SiteIndexView(SiteViewMixin, TemplateView):
    """The dashboard: every resource the user may reach."""

    template_name = "generic/site/index.html"

    def get_template_names(self) -> list[str]:
        return [self.site.index_template, self.template_name]

    def get_page_title(self) -> str:
        return self.page_title or gettext("Dashboard")

    def get_page_subtitle(self) -> str:
        return self.page_subtitle or self.site.get_title()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["app_list"] = self.site.get_app_list(self.request)
        context["shortcuts"] = self.site.get_shortcuts(self.request)
        context.update(self.site.get_index_context(self.request))

        return context


class SiteSearchView(APIView):
    """What the command palette shows, as JSON."""

    schema = framework_schema()

    site: Any = None
    permission_classes = (IsAuthenticated,)

    def get(self, request: Any) -> Response:
        term = (request.query_params.get("q") or "").strip()

        return Response({"groups": self.site.search(request, term)})


class GridView(SiteViewMixin, TemplateView):
    """A page showing one declared grid::

        path(
            "triage/",
            GridView.as_view(site=site, grid="example.ticket.triage"),
            name="triage",
        ),
        # A grid taking an argument reads it from the address.
        path(
            "teams/<str:argument>/triage/",
            GridView.as_view(site=site, grid="example.ticket.triage"),
        ),

    The page is the grid's: its title, its description, its rows. The
    template is ``generic/grid.html``, or ``generic/grid/<app>/<model>/
    <grid>.html`` for one grid of the project's.
    """

    template_name = "generic/grid.html"
    #: ``<app>.<model>.<grid>``, as the resource declares it.
    grid: str = ""

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        from django.core.exceptions import ImproperlyConfigured

        self.bound = self.site.get_grid(self.grid)

        if self.bound is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__}: no resource declares the grid "
                f"'{self.grid}'."
            )

        return super().dispatch(request, *args, **kwargs)

    def get_argument(self) -> str | None:
        """The grid's argument: the address's ``argument``, by default."""
        return self.kwargs.get("argument")

    def has_permission(self) -> bool:
        return self.bound.is_visible(self.request)

    def get_template_names(self) -> list[str]:
        resource = self.bound.resource

        return [
            f"generic/grid/{resource.app_label}/{resource.model_name}/"
            f"{self.bound.name}.html",
            self.template_name,
        ]

    def get_page_title(self) -> str:
        return self.page_title or self.bound.get_title()

    def get_page_subtitle(self) -> str:
        return self.page_subtitle or self.bound.get_description()

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        resource = self.bound.resource

        return [
            Breadcrumb(
                label=resource.get_label_plural(),
                url=resource.get_list_url(),
            ),
            Breadcrumb(label=self.get_page_title()),
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from django.http import Http404

        from generic.sites.grids import ARGUMENT_ERRORS

        context = super().get_context_data(**kwargs)
        argument = self.get_argument()

        # Refused here rather than by an empty table: an argument the
        # scope cannot read names nothing.
        try:
            self.bound.check(self.request, argument)
        except ARGUMENT_ERRORS:
            raise Http404

        context["grid"] = self.bound
        context["resource"] = self.bound.resource
        context["table_config"] = self.bound.get_table_config(
            self.request, argument
        )

        return context


# ---------------------------------------------------------------------
# Resource pages
# ---------------------------------------------------------------------


class ResourceViewMixin(SiteViewMixin):
    resource: Any = None

    def has_permission(self) -> bool:
        return self.resource.has_view_permission(self.request)

    def get_template_names(self) -> list[str]:
        resource = self.resource
        name = self.template_name.rsplit("/", 1)[-1]

        # The admin's override chain: per model, per app, then the
        # framework's own.
        return [
            f"generic/resource/{resource.app_label}/"
            f"{resource.model_name}/{name}",
            f"generic/resource/{resource.app_label}/{name}",
            self.template_name,
        ]

    def list_breadcrumb(self) -> Breadcrumb:
        resource = self.resource
        url = (
            resource.get_list_url()
            if resource.has_view_permission(self.request)
            else ""
        )

        return Breadcrumb(label=resource.get_label_plural(), url=url)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["resource"] = self.resource
        context["opts"] = self.resource.opts

        return context


class ResourceListView(ResourceViewMixin, TemplateView):
    template_name = "generic/resource/list.html"

    def get_page_title(self) -> str:
        return self.page_title or self.resource.get_label_plural()

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=self.get_page_title())]

    def get_toolbar_items(self) -> list[ToolbarItem]:
        resource = self.resource
        # The resource's own pages first: a map, a report of the lot.
        items = resource.get_page_buttons(self.request)

        if resource.can_import(self.request):
            items.append(
                ToolbarItem(
                    url=resource.get_import_url(),
                    label=gettext("Import"),
                    icon="upload_file",
                    variant="ghost",
                )
            )

        if not resource.has_add_permission(self.request):
            return items

        return items + [
            ToolbarItem(
                url=resource.get_add_url(),
                label=gettext("Add %(name)s") % {"name": resource.get_label()},
                icon="add",
                variant="primary",
            )
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from generic.sites.charts import chart_entries

        context = super().get_context_data(**kwargs)
        context["table_config"] = self.resource.get_table_config(self.request)
        context["charts"] = chart_entries(
            self.resource.get_list_chart_configs(self.request)
        )

        return context


class ResourceImportView(ResourceViewMixin, TemplateView):
    """A spreadsheet read into records: choose, match, check, import.

    The page is a frame; every step is the resource's endpoint, which
    checks the permission again and reads the file again on confirming.
    """

    template_name = "generic/resource/import.html"

    def has_permission(self) -> bool:
        return self.resource.can_import(self.request)

    def get_page_title(self) -> str:
        return self.page_title or gettext("Import %(name)s") % {
            "name": self.resource.get_label_plural().lower()
        }

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [self.list_breadcrumb(), Breadcrumb(label=gettext("Import"))]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        importer = self.resource.get_importer(self.request)
        context["import_config"] = {
            "urls": {
                **self.resource.get_import_api_urls(),
                "list": self.resource.get_list_url(),
            },
            "schema": importer.describe(),
        }

        return context


class ResourceFormView(ResourceViewMixin, TemplateView):
    """Add or change one record; view it when changing is not allowed."""

    template_name = "generic/resource/form.html"
    mode = "update"
    object: Any = None

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if request.user.is_authenticated and self.mode == "update":
            self.object = get_object_or_404(
                self.resource.get_queryset(request),
                pk=kwargs["pk"],
            )

        return super().dispatch(request, *args, **kwargs)

    def has_permission(self) -> bool:
        resource = self.resource

        if self.mode == "create":
            return resource.has_add_permission(self.request)

        return resource.has_view_permission(self.request, self.object)

    @property
    def can_change(self) -> bool:
        if self.mode == "create":
            return True

        return self.resource.has_change_permission(self.request, self.object)

    def get_page_title(self) -> str:
        if self.page_title:
            return self.page_title

        if self.mode == "create":
            return gettext("Add %(name)s") % {
                "name": self.resource.get_label().lower()
            }

        return self.resource.get_object_label(self.object)

    def get_summary_url(self) -> str:
        """The record's summary page, when records open on one."""
        if self.object is None or self.resource.object_page != "detail":
            return ""

        return self.resource.get_detail_url(self.object.pk)

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        summary = self.get_summary_url()

        # A change page sits under its record's summary.
        if summary:
            return [
                self.list_breadcrumb(),
                Breadcrumb(
                    label=self.resource.get_object_label(self.object),
                    url=summary,
                ),
                Breadcrumb(
                    label=(
                        gettext("Edit") if self.can_change else gettext("View")
                    )
                ),
            ]

        return [
            self.list_breadcrumb(),
            Breadcrumb(label=self.get_page_title()),
        ]

    def get_toolbar_items(self) -> list[ToolbarItem]:
        if self.object is None:
            return []

        items = []
        summary = self.get_summary_url()

        if summary:
            items.append(
                ToolbarItem(
                    url=summary,
                    label=gettext("Summary"),
                    icon="article",
                    variant="ghost",
                )
            )
        else:
            # No summary page to offer them: the record's own pages are
            # offered here instead.
            items.extend(
                self.resource.get_page_buttons(self.request, self.object)
            )

        url = self.resource.get_view_on_site_url(self.object)

        if url:
            items.append(
                ToolbarItem(
                    url=url,
                    label=gettext("View on site"),
                    icon="open_in_new",
                    variant="ghost",
                    target="_blank",
                )
            )

        return items

    def get_return_url(self) -> str:
        """Where "Save" and "Cancel" lead.

        Back where the user came from, when the page was opened with a
        ``_next`` pointing into this site - an "Add" button of a related
        table does that - and otherwise to the record's summary.
        """
        from django.utils.http import url_has_allowed_host_and_scheme

        from generic.sites.related import NEXT_PARAM

        target = self.request.GET.get(NEXT_PARAM, "")

        if target and url_has_allowed_host_and_scheme(
            target,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return target

        return self.get_summary_url()

    def get_initial(self) -> dict[str, Any]:
        """Values pre-filled from the query string, admin style.

        Only real model fields are taken, so an arbitrary parameter
        cannot reach the form. The resource's own ``get_initial`` comes
        first, and the query string wins over it.
        """
        initial: dict[str, Any] = dict(
            self.resource.get_initial(self.request) or {}
        )
        model = self.resource.model

        for name, values in self.request.GET.lists():
            try:
                field = model._meta.get_field(name)
            except Exception:
                continue

            if isinstance(field, models.ManyToManyField):
                initial[name] = [value for value in values if value]
            elif isinstance(field, models.JSONField):
                # Sent as text; the form's JSON widget wants the value.
                try:
                    initial[name] = json.loads(values[0])
                except ValueError:
                    continue
            else:
                initial[name] = values[0]

        return initial

    def get_form_config(self) -> dict[str, Any]:
        resource = self.resource
        request = self.request
        obj = self.object

        can_delete = obj is not None and resource.has_delete_permission(
            request,
            obj,
        )

        return {
            "mode": self.mode,
            "readOnly": not self.can_change,
            "schemaUrl": resource.get_form_schema_url(),
            "collectionUrl": resource.get_api_url(),
            "objectUrl": (
                resource.get_object_api_url(obj.pk) if obj is not None else ""
            ),
            "deletePreviewUrl": (
                resource.get_deletion_preview_url_template("{id}").replace(
                    "{id}", str(obj.pk)
                )
                if can_delete
                else ""
            ),
            "deleteUrl": (
                resource.get_object_api_url(obj.pk) if can_delete else ""
            ),
            "listUrl": (
                resource.get_list_url()
                if resource.has_view_permission(request)
                else self.site.get_home_url()
            ),
            "addUrl": (
                resource.get_add_url()
                if resource.has_add_permission(request)
                else ""
            ),
            # Empty for a record the reader may create but not change -
            # a message, a log entry: nothing to continue editing.
            "changeUrlTemplate": (
                resource.get_change_url_template("{id}")
                if resource.has_change_permission(request)
                else ""
            ),
            # Where "Save" and "Cancel" lead: back where the user came
            # from, or on to the record's own page.
            "returnUrl": self.get_return_url(),
            "objectUrlTemplate": (
                resource.get_detail_url_template("{id}")
                if resource.object_page == "detail"
                else ""
            ),
            "popup": self.is_popup(),
            "popupRequest": request.GET.get(RELATION_REQUEST_PARAM, ""),
            "initial": self.get_initial() if self.mode == "create" else {},
            "label": resource.get_label(),
            "objectLabel": force_str(obj) if obj is not None else "",
        }

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["object"] = self.object
        context["form_config"] = self.get_form_config()
        context["can_change"] = self.can_change

        return context


class ResourceDetailView(ResourceViewMixin, TemplateView):
    """A record's summary: its values, its figures, its related tables.

    Drawn from the JSON the resource's ``<pk>/summary/`` endpoint
    returns, embedded for the first paint and fetched again when the
    record changes. The related tables fetch their rows from their own
    endpoints.
    """

    template_name = "generic/resource/detail.html"
    object: Any = None

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if request.user.is_authenticated:
            self.object = get_object_or_404(
                self.resource.get_queryset(request),
                pk=kwargs["pk"],
            )

        return super().dispatch(request, *args, **kwargs)

    def has_permission(self) -> bool:
        return self.resource.has_view_permission(self.request, self.object)

    def get_page_title(self) -> str:
        return self.page_title or self.resource.get_object_label(self.object)

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [
            self.list_breadcrumb(),
            Breadcrumb(label=self.get_page_title()),
        ]

    def get_toolbar_items(self) -> list[ToolbarItem]:
        resource = self.resource
        request = self.request
        obj = self.object
        # The pages a project built around this record come first: they
        # are why somebody opened it, where Edit and Delete are not.
        items = [
            *resource.get_page_buttons(request, obj),
            *(resource.get_record_links(request, obj) or ()),
        ]

        if resource.access_log:
            from generic.access.resources import record_link

            accesses = record_link(request, resource, obj)

            if accesses is not None:
                items.append(accesses)

        url = resource.get_view_on_site_url(obj)

        if url:
            items.append(
                ToolbarItem(
                    url=url,
                    label=gettext("View on site"),
                    icon="open_in_new",
                    variant="ghost",
                    target="_blank",
                )
            )

        if resource.has_delete_permission(request, obj):
            items.append(
                ToolbarItem(
                    url=resource.get_delete_url(obj.pk),
                    label=gettext("Delete"),
                    icon="delete",
                    variant="danger-ghost",
                )
            )

        if resource.has_change_permission(request, obj):
            items.append(
                ToolbarItem(
                    url=resource.get_change_url(obj.pk),
                    label=gettext("Edit"),
                    icon="edit",
                    variant="primary",
                )
            )

        return items

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from generic.sites.charts import chart_entries
        from generic.sites.summary import build_summary

        context = super().get_context_data(**kwargs)
        resource = self.resource
        request = self.request
        obj = self.object

        context["object"] = obj
        context["summary"] = build_summary(resource, request, obj)
        context["charts"] = chart_entries(
            resource.get_detail_chart_configs(request, obj)
        )
        context["related_tables"] = [
            {
                "name": bound.name,
                "config_id": f"related-{bound.name}-config",
                "config": bound.get_table_config(request, obj),
                "charts": chart_entries(bound.get_chart_configs(request, obj)),
            }
            for bound in resource.get_related_tables(request)
            if bound.is_visible(request)
        ]
        return context


# ---------------------------------------------------------------------
# Rows that are not a model's
# ---------------------------------------------------------------------


class DataViewMixin(SiteViewMixin):
    """The pages of a ``DataResource``: drawn by the resource templates,
    which a project overrides per resource with
    ``generic/data/<name>/list.html`` or ``.../detail.html``."""

    resource: Any = None

    def has_permission(self) -> bool:
        return self.resource.has_view_permission(self.request)

    def get_template_names(self) -> list[str]:
        name = self.template_name.rsplit("/", 1)[-1]

        return [
            f"generic/data/{self.resource.name}/{name}",
            self.template_name,
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["resource"] = self.resource

        return context


class DataListView(DataViewMixin, TemplateView):
    template_name = "generic/resource/list.html"

    def get_page_title(self) -> str:
        return self.page_title or self.resource.get_label_plural()

    def get_page_subtitle(self) -> str:
        return self.page_subtitle or force_str(self.resource.description)

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=self.get_page_title())]

    def get_toolbar_items(self) -> list[ToolbarItem]:
        """The resource's own pages this reader may open."""
        return self.resource.get_page_buttons(self.request)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["table_config"] = self.resource.get_table_config(self.request)

        return context


class DataDetailView(DataViewMixin, TemplateView):
    """One row, laid out as a record's summary page."""

    template_name = "generic/resource/detail.html"
    row: Any = None

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        from django.http import Http404

        if (
            request.user.is_authenticated
            and self.resource.has_view_permission(request)
        ):
            self.row = self.resource.get_row(request, kwargs["key"])

            if self.row is None:
                raise Http404

        return super().dispatch(request, *args, **kwargs)

    def get_page_title(self) -> str:
        return self.page_title or self.resource.get_object_label(self.row)

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [
            Breadcrumb(
                label=self.resource.get_label_plural(),
                url=self.resource.get_list_url(),
            ),
            Breadcrumb(label=self.get_page_title()),
        ]

    def get_toolbar_items(self) -> list[ToolbarItem]:
        """The row's own pages this reader may open."""
        return self.resource.get_page_buttons(self.request, self.row)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["object"] = self.row
        context["summary"] = self.resource.build_summary(
            self.request, self.row
        )
        context["charts"] = []
        # A tab per related table, each started the first time it shows.
        context["related_tables"] = [
            {
                "name": relation.name,
                "config_id": f"related-{relation.name}-config",
                "config": self.resource.get_related_table_config(
                    self.request, relation, target, self.row
                ),
                "charts": [],
            }
            for relation, target in self.resource.get_related_tables(
                self.request
            )
        ]

        return context


class ResourceDeleteView(GenericDeleteView):
    """The confirmation page, for a link that must work without script.

    The change page and the table delete through a dialog and the API;
    this page is what a bookmark or an e-mailed link lands on.
    """

    resource: Any = None
    site: Any = None

    def get_queryset(self) -> Any:
        return self.resource.get_queryset(self.request)

    def get_permission_required(self) -> tuple[str, ...]:
        return ()

    def has_permission(self) -> bool:
        return self.resource.has_delete_permission(self.request)

    def get_login_url(self) -> str:
        return self.site.get_login_url()

    def get_list_url(self) -> str:
        return self.resource.get_list_url()

    def get_cancel_url(self) -> str:
        if self.object is not None:
            return self.resource.get_object_url(self.object.pk)

        return self.get_list_url() or "/"

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        resource = self.resource

        return [
            Breadcrumb(
                label=resource.get_label_plural(),
                url=resource.get_list_url(),
            ),
            Breadcrumb(
                label=force_str(self.object),
                url=resource.get_object_url(self.object.pk),
            ),
            Breadcrumb(label=gettext("Delete")),
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["generic_site"] = self.site
        context["resource"] = self.resource
        context["trash"] = self.resource.trash

        return context

    def form_valid(self, form: Any) -> HttpResponse:
        if not self.resource.trash:
            return super().form_valid(form)

        # Into the trash, through the resource like the API's delete.
        self.object = self.get_object()
        label = str(self.object)
        self.resource.delete_model(self.request, self.object)
        messages.success(
            self.request,
            gettext("%(name)s was moved to the trash.") % {"name": label},
        )

        return HttpResponseRedirect(self.get_success_url())


__all__ = [
    "DataDetailView",
    "DataListView",
    "POPUP_PARAM",
    "RELATION_REQUEST_PARAM",
    "ResourceDeleteView",
    "ResourceFormView",
    "ResourceListView",
    "SiteIndexView",
    "SiteSearchView",
]

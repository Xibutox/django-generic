"""The resource: everything the framework needs to know about a model.

The counterpart of a ``ModelAdmin``. Most attributes have the admin's
name and meaning, so a developer who knows one knows the other; what
differs is that every screen it produces reads and writes through the
REST API rather than a Django form.
"""

from __future__ import annotations

import dataclasses
import functools
from types import SimpleNamespace
from typing import Any, Callable, Sequence

from django.contrib.admin.utils import NestedObjects
from django.contrib.auth import get_permission_codename
from django.core.exceptions import ImproperlyConfigured
from django.db import router, transaction
from django.db.models import QuerySet
from django.urls import NoReverseMatch, reverse
from django.utils.encoding import force_str
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from generic.api.filters import apply_search, split_search_terms
from generic.conf import generic_settings
from generic.search.ranking import rank
from generic.sites.decorators import action
from generic.sites.pages import PagesMixin
from generic.sites.serializers import (
    ROW_KEY,
    build_form_serializer,
    build_table_serializer,
    default_form_fields,
    flatten_fieldsets,
    with_row_key,
)
from generic.views.datatable import filter_row_option

#: Placeholder reversed into URLs, then swapped for a client template
#: token. Must survive the ``<path:pk>`` converter.
PK_PLACEHOLDER = "__pk__"


@dataclasses.dataclass(frozen=True)
class ResourceAction:
    """A bulk action, resolved for one request."""

    name: str
    function: Callable[[Any, QuerySet], Any]
    description: str
    icon: str = ""
    confirm: str = ""
    variant: str = "default"

    def as_client(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.description,
            "icon": self.icon,
            "confirm": self.confirm,
            "variant": self.variant,
        }


class ModelResource(PagesMixin):
    """How one model appears in the application.

    ::

        @register(Ticket)
        class TicketResource(ModelResource):
            icon = "confirmation_number"
            list_display = ("reference", "title", "team", "status")
            search_fields = ("reference", "title")
            fieldsets = (
                (None, {"fields": ("reference", ("title", "team"))}),
                ("Planning", {"fields": ("due_on",),
                              "classes": ("collapse",)}),
            )
            inlines = (CommentInline,)
    """

    # -- identity and navigation ----------------------------------------

    #: Material Symbols name, shown in the sidebar and the palette.
    icon: str = "table_rows"
    label: Any = None
    label_plural: Any = None
    #: Sidebar group. Defaults to the app's verbose name.
    group: Any = None
    #: Position inside the group.
    order: int = 0
    show_in_navigation: bool = True
    description: Any = ""

    # -- listing --------------------------------------------------------

    #: Columns: field names, ``related__paths``, resource methods,
    #: model attributes, or ``"__str__"``.
    list_display: Sequence[Any] = ("__str__",)
    #: Columns linking to the change page. Defaults to the first.
    list_display_links: Sequence[Any] | None = None
    list_select_related: Sequence[str] = ()
    list_prefetch_related: Sequence[str] = ()
    list_per_page: int | None = None
    #: What the global search box, the autocomplete and the command
    #: palette match against.
    search_fields: Sequence[str] = ()
    #: Order the command palette's and the autocompletes' results by
    #: how closely they match, best first (PostgreSQL with
    #: ``generic.search``; elsewhere the usual order). Tables keep the
    #: order their reader chose.
    search_rank: bool = False
    ordering: Sequence[str] | None = None
    #: A hand-written table serializer, replacing the generated one.
    table_serializer: Any = None
    #: Client options merged over the defaults.
    table_options: dict[str, Any] = {}
    #: Fields drawn as coloured tags, in the table and on the summary
    #: page: ``{"tags": TagStyle(background="background")}``.
    tag_fields: dict[str, Any] = {}
    #: Named table layouts offered to every user:
    #: ``{"Planning": {"columns": [...], "order": [["due_on", "asc"]],
    #: "filters": {...}}}``.
    presets: dict[str, dict[str, Any]] = {}
    #: Columns that *may* be edited in a table, by name. Each must be
    #: in ``list_display``. A name may walk single-valued relations -
    #: ``"customer__name"`` - and then it is the related model's change
    #: permission that decides. What finally happens is
    #: ``save_editable``.
    #:
    #: This is the capability, not the decision: no table offers it
    #: until one asks. A related table asks with
    #: ``RelatedTable(editable=True)``, a page of its own by calling
    #: ``get_table_config(request, editable=True)``, and this
    #: resource's own list page with ``list_editable`` below.
    editable_fields: Sequence[str] = ()
    #: Whether this resource's **list page** offers that editing.
    #: False, because a list is usually read on the way to somewhere
    #: else, and a page built for correcting rows is a different page.
    list_editable: bool = False
    #: Grids over sets of this resource's rows chosen by the project:
    #: ``Grid("triage", scope=..., columns=..., editable=...)``, each
    #: shown by a ``GridView``. See ``generic.sites.grids``.
    grids: Sequence[Any] = ()
    #: Bulk actions: method names, or functions taking
    #: ``(resource, request, queryset)``.
    actions: Sequence[Any] = ("delete_selected",)
    #: State fields (django-fsm-2 ``FSMField``) whose ``@transition``
    #: methods become buttons on a record's page. The fields become read
    #: only in forms and grids. See ``generic.sites.transitions``.
    transitions: Sequence[str] = ()
    #: Whether each transition is also a bulk action of the list.
    transition_actions: bool = True
    show_export: bool = True
    #: Records loaded from a spreadsheet: ``Import(fields=..., key=...)``
    #: gives the list page an *Import* button and its page. None - the
    #: default - offers nothing and refuses the endpoint. See
    #: ``generic.sites.imports``.
    imports: Any = None
    #: The row of search fields under the column headers: ``"open"``
    #: from the start, ``"toggle"`` behind a toolbar button, ``False``
    #: not offered. Each user's own choice is remembered with the table.
    filter_row: str | bool = "open"
    #: Count the unfiltered rows on every draw. Switch off on very large
    #: tables.
    show_full_result_count: bool = True

    # -- forms ------------------------------------------------------------

    fields: Sequence[Any] | None = None
    exclude: Sequence[str] = ()
    fieldsets: Any = None
    readonly_fields: Sequence[str] = ()
    #: Presentation per field: width, placeholder, label...
    form_overrides: dict[str, dict[str, Any]] = {}
    #: Serializer options per field, as DRF's ``extra_kwargs``:
    #: ``{"password": {"write_only": True, "required": False}}``. This
    #: is the behaviour of the field - what may be written, what is
    #: sent back - where ``form_overrides`` is only how it is drawn.
    #: A field that must never be read back belongs here, because the
    #: record's own endpoint returns everything else.
    form_field_kwargs: dict[str, dict[str, Any]] = {}
    #: A hand-written form serializer, replacing the generated one.
    form_serializer: Any = None
    inlines: Sequence[type] = ()
    view_on_site: bool = True

    # -- the summary page ---------------------------------------------------

    #: Where a record opens from the table, the palette and a watch:
    #: its summary page ("detail") or its form ("change").
    object_page: str = "detail"
    #: Sections of the summary page, fieldsets style. Defaults to the
    #: form's fieldsets, read-only values included.
    detail_fieldsets: Any = None
    #: Figures shown as tiles above the sections: fields, resource
    #: methods or model attributes, labelled with @display.
    detail_stats: Sequence[str] = ()
    #: Tables of related records below the sections: RelatedTable(...).
    related_tables: Sequence[Any] = ()

    # -- charts ------------------------------------------------------------

    #: Charts of this resource's records: Chart(...). Each is served at
    #: api/<app>/<model>/charts/<name>/ with the table's filters.
    charts: Sequence[Any] = ()
    #: Charts drawn above the list, following its filters, by name.
    list_charts: Sequence[str] = ()
    #: Charts on the summary page: "<related table>.<chart of its
    #: resource>", narrowed to the record.
    detail_charts: Sequence[str] = ()

    # -- live updates ------------------------------------------------------

    #: Publish every change so open tables refresh themselves.
    realtime: bool = True

    #: Whether this list may be sent by e-mail on a schedule - offered
    #: to holders of ``generic.add_scheduledmailing`` (generic.mailings).
    mailing: bool = True

    #: Offer users the choice of being told when a record changes, or
    #: when any record of this model does. False for models whose
    #: changes are nobody's news - a log, a run, a schedule's counter.
    watchable: bool = True

    # -- history -----------------------------------------------------------

    #: Keep a version of every record on every change, read back by the
    #: History tab of its page. False for models written constantly by
    #: the application itself, whose history is noise.
    history: bool = True
    #: Fields left out of the recorded version, by name. A field nobody
    #: should read twice - a token, a secret - belongs here: the tab
    #: shows what was recorded, whatever the form shows.
    history_exclude: Sequence[str] = ()

    #: The DRF viewset class the endpoint is built from.
    viewset_class: Any = None

    def __init__(self, model: Any, site: Any) -> None:
        self.model = model
        self.site = site
        self.opts = model._meta
        self._table_serializer_class: Any = None
        self._form_serializer_class: Any = None
        self._inline_instances: list[Any] | None = None
        self._editable_columns: dict[str, Any] | None = None
        self._transitions: dict[str, Any] | None = None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} for {self.opts.label}>"

    # -- identity -----------------------------------------------------------

    @property
    def app_label(self) -> str:
        return self.opts.app_label

    @property
    def model_name(self) -> str:
        return self.opts.model_name

    @property
    def label_lower(self) -> str:
        return self.opts.label_lower

    @property
    def url_prefix(self) -> str:
        return f"{self.app_label}_{self.model_name}"

    @property
    def topic_name(self) -> str:
        """Event topic announcing changes to this model's rows."""
        return f"resource.{self.label_lower}"

    @property
    def state_key(self) -> str:
        """Identifies this table's saved layouts and state."""
        return f"{self.site.name}.{self.label_lower}"

    def get_label(self) -> str:
        return force_str(self.label or self.opts.verbose_name).capitalize()

    def get_label_plural(self) -> str:
        return force_str(
            self.label_plural or self.opts.verbose_name_plural
        ).capitalize()

    def get_group(self) -> str:
        if self.group is not None:
            return force_str(self.group)

        return force_str(self.opts.app_config.verbose_name)

    def get_icon(self) -> str:
        return self.icon

    # -- URLs -------------------------------------------------------------

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

    def _template(self, name: str, token: str) -> str:
        url = self._reverse(name, pk=PK_PLACEHOLDER)

        return url.replace(PK_PLACEHOLDER, token) if url else ""

    def get_list_url(self) -> str:
        return self._reverse(self.url_name("list"))

    def get_add_url(self) -> str:
        return self._reverse(self.url_name("add"))

    def get_change_url(self, pk: Any) -> str:
        return self._reverse(self.url_name("change"), pk=pk)

    def get_delete_url(self, pk: Any) -> str:
        return self._reverse(self.url_name("delete"), pk=pk)

    def get_change_url_template(self, token: str = "{id}") -> str:
        return self._template(self.url_name("change"), token)

    def get_delete_url_template(self, token: str = "{id}") -> str:
        return self._template(self.url_name("delete"), token)

    def get_detail_url(self, pk: Any) -> str:
        return self._reverse(self.url_name("detail"), pk=pk)

    def get_detail_url_template(self, token: str = "{id}") -> str:
        return self._template(self.url_name("detail"), token)

    def get_object_url(self, pk: Any) -> str:
        """The page a record opens on: its summary, or its form."""
        if self.object_page == "detail":
            return self.get_detail_url(pk) or self.get_change_url(pk)

        return self.get_change_url(pk)

    def get_object_url_template(self, token: str = "{id}") -> str:
        if self.object_page == "detail":
            return self.get_detail_url_template(token) or (
                self.get_change_url_template(token)
            )

        return self.get_change_url_template(token)

    def get_row_url_template(self) -> str:
        """The row's own page, with its key left for the client to fill."""
        return self.get_object_url_template("{" + ROW_KEY + "}")

    def get_summary_api_url(self, pk: Any) -> str:
        return self._reverse(self.api_url_name("summary"), pk=pk)

    def get_history_api_url(self, pk: Any) -> str:
        return self._reverse(self.api_url_name("history"), pk=pk)

    def get_cells_url_template(self) -> str:
        """Where a row's edited cells are written.

        Tokenised on the row's own key, like the row actions, so the
        browser fills it from the row it is editing.
        """
        return self._template(
            self.api_url_name("cells"),
            "{" + ROW_KEY + "}",
        )

    def get_rows_url(self) -> str:
        """Where a row added in a grid is sent."""
        return self._reverse(self.api_url_name("rows"))

    def get_chart_url(self, name: str) -> str:
        try:
            return reverse(self.api_url_name("chart"), kwargs={"chart": name})
        except NoReverseMatch:
            return ""

    def get_api_url(self) -> str:
        return self._reverse(self.api_url_name("list"))

    def get_object_api_url(self, pk: Any) -> str:
        return self._reverse(self.api_url_name("detail"), pk=pk)

    def get_object_api_url_template(self, token: str = "{id}") -> str:
        return self._template(self.api_url_name("detail"), token)

    def get_deletion_preview_url_template(self, token: str = "{id}") -> str:
        return self._template(self.api_url_name("deletion-preview"), token)

    def get_autocomplete_url(self) -> str:
        return self._reverse(self.api_url_name("autocomplete"))

    def get_form_schema_url(self) -> str:
        return self._reverse(self.api_url_name("form-schema"))

    def get_actions_url(self) -> str:
        return self._reverse(self.api_url_name("actions"))

    def get_mailing_url(self, request: Any) -> str:
        """The add form of a mailing of this list, or ``""``."""
        from generic.mailings.models import ScheduledMailing

        if not self.mailing or not generic_settings.SHOW_MAILINGS:
            return ""

        user = getattr(request, "user", None)

        if user is None or not user.has_perm("generic.add_scheduledmailing"):
            return ""

        resource = self.site.get_resource(ScheduledMailing)

        return resource.get_add_url() if resource is not None else ""

    def get_transitions_url(self, pk: Any) -> str:
        """Where a record's transitions are listed; ``<name>/`` runs one."""
        if not self.get_transitions():
            return ""

        return self._reverse(self.api_url_name("transitions"), pk=pk)

    def get_import_url(self) -> str:
        return self._reverse(self.url_name("import"))

    def get_import_api_urls(self) -> dict[str, str]:
        return {
            "run": self._reverse(self.api_url_name("import-rows")),
            "schema": self._reverse(self.api_url_name("import-schema")),
            "template": self._reverse(self.api_url_name("import-template")),
        }

    def get_view_on_site_url(self, obj: Any) -> str:
        if not self.view_on_site or not hasattr(obj, "get_absolute_url"):
            return ""

        try:
            return obj.get_absolute_url()
        except NoReverseMatch:
            return ""

    # -- permissions --------------------------------------------------------
    #
    # The model permissions, exactly as the admin checks them. Override
    # any of these for object-level rules.

    def get_permission_codename(self, action: str) -> str:
        codename = get_permission_codename(action, self.opts)

        return f"{self.app_label}.{codename}"

    def _has(self, request: Any, action: str) -> bool:
        user = getattr(request, "user", None)

        if user is None or not user.is_active:
            return False

        return bool(user.has_perm(self.get_permission_codename(action)))

    def has_view_permission(self, request: Any, obj: Any = None) -> bool:
        # Being allowed to change implies being allowed to look.
        return self._has(request, "view") or self._has(request, "change")

    def has_add_permission(self, request: Any) -> bool:
        return self._has(request, "add")

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return self._has(request, "change")

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return self._has(request, "delete")

    def has_module_permission(self, request: Any) -> bool:
        """Whether the resource appears in the navigation at all."""
        return self.has_view_permission(request) or (
            self.has_add_permission(request)
        )

    def has_action_permission(self, request: Any, permission: str) -> bool:
        checks = {
            "view": self.has_view_permission,
            "add": self.has_add_permission,
            "change": self.has_change_permission,
            "delete": self.has_delete_permission,
        }

        if permission in checks:
            return bool(checks[permission](request))

        user = getattr(request, "user", None)

        return bool(user and user.has_perm(permission))

    def get_permissions(self, request: Any, obj: Any = None) -> dict:
        return {
            "view": self.has_view_permission(request, obj),
            "add": self.has_add_permission(request),
            "change": self.has_change_permission(request, obj),
            "delete": self.has_delete_permission(request, obj),
        }

    def topic_permission(
        self,
        user: Any,
        topic: str,
        parameters: dict[str, str],
    ) -> bool:
        """Who may follow this model's change stream."""
        if not (user and getattr(user, "is_authenticated", False)):
            return False

        return self.has_view_permission(SimpleNamespace(user=user))

    # -- querysets ----------------------------------------------------------

    def get_ordering(self, request: Any) -> Sequence[str]:
        return tuple(self.ordering or ())

    def get_queryset(self, request: Any) -> QuerySet:
        queryset = self.model._default_manager.get_queryset()
        ordering = self.get_ordering(request)

        if ordering:
            queryset = queryset.order_by(*ordering)

        return queryset

    def get_list_queryset(self, request: Any) -> QuerySet:
        """What the table pages through: related rows loaded up front."""
        queryset = self.get_queryset(request)
        serializer = self.get_table_serializer_class()

        select = {
            *getattr(serializer, "generic_select_related", ()),
            *self.list_select_related,
        }
        prefetch = {
            *getattr(serializer, "generic_prefetch_related", ()),
            *self.list_prefetch_related,
        }

        if select:
            queryset = queryset.select_related(*sorted(select))

        if prefetch:
            queryset = queryset.prefetch_related(*sorted(prefetch))

        # Paging an unordered queryset can show a row twice and another
        # never.
        if not queryset.ordered:
            queryset = queryset.order_by("-pk")

        return queryset

    def get_autocomplete_queryset(self, request: Any) -> QuerySet:
        queryset = self.get_queryset(request)

        if not queryset.ordered:
            queryset = queryset.order_by("pk")

        return queryset

    def get_search_fields(self, request: Any = None) -> tuple[str, ...]:
        return tuple(self.search_fields)

    def get_search_results(
        self,
        request: Any,
        term: str,
        limit: int,
    ) -> list[Any]:
        queryset = apply_search(
            self.get_autocomplete_queryset(request),
            self.get_search_fields(request),
            term,
        )

        return list(self.rank_search_results(request, queryset, term)[:limit])

    def rank_search_results(
        self,
        request: Any,
        queryset: QuerySet,
        term: str,
    ) -> QuerySet:
        """Best match first, when ``search_rank`` asks for it."""
        if not self.search_rank:
            return queryset

        words = " ".join(
            text for text, negated in split_search_terms(term) if not negated
        )

        return rank(queryset, self.get_search_fields(request), words)

    def get_object_label(self, obj: Any) -> str:
        return force_str(obj)

    # -- pages of its own (generic.sites.pages) ------------------------

    def get_page_object(self, request: Any, value: Any) -> Any:
        """The record a page's address names, through ``get_queryset``:
        a reader never reaches a record the resource would not list."""
        from django.core.exceptions import ValidationError
        from django.http import Http404

        try:
            return self.get_queryset(request).get(pk=value)
        except (self.model.DoesNotExist, ValueError, ValidationError):
            raise Http404 from None

    def get_page_object_key(self, obj: Any) -> Any:
        return getattr(obj, "pk", obj)

    def get_record_links(self, request: Any, obj: Any) -> list[Any]:
        """Pages built around one record, offered on its summary.

        A project that makes a page of its own for a record - a page
        for correcting its rows, a report of it - returns a
        ``ToolbarItem`` for each, and they appear first in the record's
        toolbar::

            def get_record_links(self, request, obj):
                return [ToolbarItem(
                    url=reverse("app:ticket-work", args=[obj.pk]),
                    label=gettext("Work on the hours"),
                    icon="edit_note",
                )]

        Return nothing for a reader who could not open the page: a
        button that leads to a refusal is worse than no button.
        """
        return []

    def may_watch(self, user: Any, obj: Any = None) -> bool:
        """Whether this user may be told about ``obj``.

        Asked for every message a watch would send, after the model's
        view permission has already passed. Override it where rows are
        restricted per user: a signal has no request, so
        ``get_queryset`` cannot be replayed here, and a watch must
        never become a way to learn that a record exists.
        """
        return True

    def get_object_description(self, obj: Any) -> str:
        return ""

    # -- table ----------------------------------------------------------------

    def get_list_display(self) -> tuple[Any, ...]:
        return tuple(self.list_display) or ("__str__",)

    def get_tag_style(self, name: str) -> Any:
        """How the field ``name`` is drawn as tags, or ``None``."""
        return self.tag_fields.get(name)

    def get_table_serializer_class(self) -> Any:
        if self._table_serializer_class is None:
            if self.table_serializer is not None:
                self._table_serializer_class = with_row_key(
                    self.table_serializer
                )
            else:
                self._table_serializer_class = build_table_serializer(self)

        return self._table_serializer_class

    def get_page_size(self, request: Any) -> int:
        preferences = _preferences_for(request)

        if preferences is not None and preferences.table_page_size:
            return int(preferences.table_page_size)

        return self.list_per_page or generic_settings.TABLE_PAGE_SIZE

    def get_presets(self, request: Any) -> dict[str, dict[str, Any]]:
        return {
            force_str(name): dict(preset)
            for name, preset in self.presets.items()
        }

    def get_row_actions(self, request: Any) -> list[dict[str, Any]]:
        actions = []
        row = "{" + ROW_KEY + "}"
        can_change = self.has_change_permission(request)
        detail = (
            self.get_detail_url_template(row)
            if self.object_page == "detail"
            else ""
        )

        # The first action with a URL is also what a double-click opens.
        if detail:
            actions.append(
                {
                    "name": "open",
                    "label": gettext("Open"),
                    "icon": "article",
                    "url": detail,
                }
            )

        url = self.get_change_url_template(row)

        # With a summary page, a read-only form adds nothing to "Open".
        if url and (can_change or not detail):
            actions.append(
                {
                    "name": "change",
                    "label": (
                        gettext("Edit") if can_change else gettext("View")
                    ),
                    "icon": "edit" if can_change else "visibility",
                    "url": url,
                }
            )

        # The record's pages of the project's own, where asked for.
        actions.extend(self.get_page_row_actions(request, row))

        if self.has_delete_permission(request):
            token = "{" + ROW_KEY + "}"
            actions.append(
                {
                    "name": "delete",
                    "label": gettext("Delete"),
                    "icon": "delete",
                    "variant": "danger",
                    "apiUrl": self.get_object_api_url_template(token),
                    "previewUrl": self.get_deletion_preview_url_template(
                        token
                    ),
                }
            )

        return actions

    def get_table_options(self, request: Any) -> dict[str, Any]:
        preferences = _preferences_for(request)
        remember = (
            preferences.remember_table_state
            if preferences is not None
            else True
        )

        options: dict[str, Any] = {
            "pageLength": self.get_page_size(request),
            "lengthMenu": [10, 15, 25, 50, 100],
            "stateKey": self.state_key,
            "stateSave": remember,
            "columnSelector": True,
            "filters": True,
            "filterRow": filter_row_option(self),
            "excel": self.show_export,
            "csv": self.show_export,
            "copy": True,
            "print": True,
            "rowKey": ROW_KEY,
            "rowActions": self.get_row_actions(request),
            "bulkActions": [
                entry.as_client()
                for entry in self.get_actions(request).values()
            ],
            "bulkActionsUrl": self.get_actions_url(),
            "presets": self.get_presets(request),
            "savedViewsUrl": self._reverse("generic:saved-view-list"),
            # Where "Send by e-mail on a schedule" leads, for who may.
            "mailingUrl": self.get_mailing_url(request),
            "realtimeTopic": self.topic_name if self.realtime else "",
            "label": self.get_label(),
            "labelPlural": self.get_label_plural(),
            "exportName": self.model_name,
            # The address carries the filters: a filtered list can be
            # bookmarked and shared.
            "syncUrl": True,
        }

        options.update(self.table_options)

        return options

    def get_editable_options(self, request: Any) -> dict[str, Any]:
        """What a table needs to let this reader edit its cells.

        Empty unless the resource declares editable fields and this
        reader may write at least one of them: a cell nobody describes
        is drawn as text. The endpoint checks again, so this is the
        interface rather than the rule.
        """
        if not self.editable_fields:
            return {}

        from generic.sites.editable import schemas

        described = schemas(self, request)

        if not described:
            return {}

        return {
            "editable": described,
            "editableUrl": self.get_cells_url_template(),
        }

    def get_table_config(
        self,
        request: Any,
        editable: bool | None = None,
    ) -> dict[str, Any]:
        """This resource's table, for whoever is drawing one.

        ``editable`` is the table's decision, not the resource's: a
        list page reads, a page built for correcting rows writes, and
        the same resource serves both. ``None`` leaves it to
        ``list_editable``, which is what the resource's own list page
        passes.
        """
        serializer = self.get_table_serializer_class()
        declared = getattr(serializer, "_declared_fields", {})
        tag_links = getattr(serializer, "generic_tag_links", {})
        columns = [
            dict(column) for column in serializer.get_datatable_columns()
        ]

        for column in columns:
            name = column.get("data")
            key = f"_fk_{name}"

            # Each tag of a relation links to its own record's page.
            if name in tag_links and not column.get("tagUrl"):
                url = self.get_related_url_template(
                    request, tag_links[name], "{id}"
                )

                if url:
                    column["tagUrl"] = url

                continue

            # A foreign key cell links to the related record's page,
            # when this user may open it.
            if key not in declared or column.get("linkUrl"):
                continue

            url = self.get_related_url_template(request, name, "{" + key + "}")

            if url:
                column.update(type="link", linkUrl=url)

        options = self.get_table_options(request)
        config = {
            "url": self.get_api_url(),
            "columns": columns,
            "options": options,
        }

        if not (self.list_editable if editable is None else editable):
            return config

        from generic.sites.editable import (
            add_options,
            as_grid,
            default_context,
        )

        # A table asked to be editable is a grid: nothing in it leads
        # elsewhere, whether or not this reader may write a cell.
        options.update(self.get_editable_options(request))
        # Over the resource's own rows, a new row writes its own
        # columns. A related table or a declared grid replaces this
        # with what its context allows.
        added = add_options(self, request, default_context(self))

        if added:
            options["gridAdd"] = added

        return as_grid(config)

    def get_related_url_template(
        self,
        request: Any,
        path: str,
        token: str,
    ) -> str:
        """The page of the record at the end of ``path``, as a template."""
        from django.contrib.admin.utils import get_fields_from_path

        try:
            field = get_fields_from_path(self.model, path)[-1]
        except Exception:
            return ""

        if not field.is_relation:
            return ""

        related = self.site.get_resource(field.related_model)

        if related is None or not related.has_view_permission(request):
            return ""

        return related.get_object_url_template(token)

    # -- summary page ---------------------------------------------------------

    def get_detail_fieldsets(self, request: Any = None) -> Any:
        """The sections of the summary page, fieldsets style."""
        if self.detail_fieldsets:
            return self.detail_fieldsets

        fieldsets = self.get_fieldsets(request)

        if fieldsets:
            return fieldsets

        names = list(self.get_fields(request))
        names += [
            name
            for name in self.get_readonly_fields(request)
            if name not in names
        ]

        return ((None, {"fields": names}),)

    def get_detail_stats(self, request: Any = None) -> tuple[str, ...]:
        return tuple(self.detail_stats)

    def get_related_tables(self, request: Any = None) -> list[Any]:
        """The related tables, resolved once against this resource."""
        bound = self.__dict__.get("_bound_related_tables")

        if bound is None:
            from generic.sites.related import bind_related_table

            bound = [
                bind_related_table(definition, self)
                for definition in self.related_tables
            ]
            self.__dict__["_bound_related_tables"] = bound

        return list(bound)

    def get_bound_related_table(self, name: str) -> Any:
        for bound in self.get_related_tables():
            if bound.name == name:
                return bound

        return None

    def get_grids(self) -> list[Any]:
        """The declared grids, resolved once against this resource."""
        bound = self.__dict__.get("_bound_grids")

        if bound is None:
            from generic.sites.grids import bind_grid

            bound = [bind_grid(definition, self) for definition in self.grids]
            self.__dict__["_bound_grids"] = bound

        return list(bound)

    def get_bound_grid(self, name: str) -> Any:
        for bound in self.get_grids():
            if bound.name == name:
                return bound

        return None

    # -- charts -----------------------------------------------------------

    def get_charts(self, request: Any = None) -> list[Any]:
        return list(self.charts)

    def get_chart(self, name: str) -> Any:
        for chart in self.get_charts():
            if chart.name == name:
                return chart

        return None

    def get_chart_config(
        self,
        request: Any,
        name: str,
        **overrides: Any,
    ) -> dict[str, Any] | None:
        """What a page needs to draw one chart, or None when hidden."""
        chart = self.get_chart(name)

        if chart is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__} has no chart named '{name}'."
            )

        if not chart.is_visible(request, self):
            return None

        return chart.get_config(self, request, **overrides)

    def get_list_chart_configs(self, request: Any) -> list[dict[str, Any]]:
        """The charts above the list; they follow its filters."""
        configs = [
            self.get_chart_config(request, name, table="#datatable")
            for name in self.list_charts
        ]

        return [config for config in configs if config]

    def get_detail_chart_configs(
        self,
        request: Any,
        obj: Any,
    ) -> list[dict[str, Any]]:
        """The charts of a summary page, narrowed to ``obj``."""
        configs = []

        for reference in self.detail_charts:
            table_name, _, chart_name = reference.partition(".")
            bound = self.get_bound_related_table(table_name)

            if bound is None or not chart_name:
                raise ImproperlyConfigured(
                    f"{type(self).__name__}.detail_charts names "
                    f"'{reference}': give '<related table>.<chart>'."
                )

            config = bound.get_chart_config(request, obj, chart_name)

            if config:
                configs.append(config)

        return configs

    # -- forms ------------------------------------------------------------

    def get_fieldsets(self, request: Any = None) -> Any:
        if self.fieldsets:
            return self.fieldsets

        # Admin style: a tuple inside ``fields`` shares one row, which
        # only a fieldset can say.
        if self.fields is not None and any(
            isinstance(entry, (list, tuple)) for entry in self.fields
        ):
            return ((None, {"fields": tuple(self.fields)}),)

        return self.fieldsets

    def get_fields(self, request: Any = None) -> list[str]:
        fieldsets = self.get_fieldsets(request)

        if fieldsets:
            return flatten_fieldsets(fieldsets)

        if self.fields is not None:
            return list(self.fields)

        return default_form_fields(self.model, exclude=self.exclude)

    def get_readonly_fields(self, request: Any = None) -> tuple[str, ...]:
        from generic.sites.transitions import state_fields

        declared = tuple(self.readonly_fields)
        fields = set(self.get_fields(request))

        # A state moves through its transitions, never through a form.
        return declared + tuple(
            name
            for name in state_fields(self)
            if name not in declared and name in fields
        )

    def get_form_serializer_class(self) -> Any:
        if self.form_serializer is not None:
            return self.form_serializer

        if self._form_serializer_class is None:
            self._form_serializer_class = build_form_serializer(
                self.model,
                fields=self.get_fields(),
                readonly_fields=self.get_readonly_fields(),
                fieldsets=self.get_fieldsets(),
                overrides=self.form_overrides,
                extra_kwargs=self.form_field_kwargs,
                source=self,
            )

        return self._form_serializer_class

    def get_inline_instances(self) -> list[Any]:
        if self._inline_instances is None:
            self._inline_instances = [
                inline_class(self.model, self.site)
                for inline_class in self.inlines
            ]

        return self._inline_instances

    def get_inline_definitions(
        self,
        request: Any,
        obj: Any = None,
    ) -> tuple[Any, ...]:
        return tuple(
            inline.get_definition(request, obj)
            for inline in self.get_inline_instances()
            if inline.is_visible(request, obj)
        )

    # -- actions ------------------------------------------------------------

    def _describe(self, text: Any) -> str:
        text = force_str(text)

        if "%(" not in text:
            return text

        return text % {
            "verbose_name": self.opts.verbose_name,
            "verbose_name_plural": self.opts.verbose_name_plural,
        }

    def get_actions(self, request: Any) -> dict[str, ResourceAction]:
        """The bulk actions this user may run, by name."""
        actions: dict[str, ResourceAction] = {}

        for entry in self.actions:
            if isinstance(entry, str):
                function = getattr(self, entry, None)

                if function is None:
                    raise ImproperlyConfigured(
                        f"{type(self).__name__}.actions names '{entry}', "
                        f"which is not a method of the resource."
                    )

                name = entry
                call = function
            else:
                function = entry
                name = entry.__name__
                call = functools.partial(entry, self)

            permissions = getattr(function, "allowed_permissions", ("change",))

            if not all(
                self.has_action_permission(request, permission)
                for permission in permissions
            ):
                continue

            description = getattr(function, "short_description", None)
            confirm = getattr(function, "confirmation", None)

            actions[name] = ResourceAction(
                name=name,
                function=call,
                description=self._describe(
                    description or name.replace("_", " ").capitalize()
                ),
                icon=getattr(function, "icon", "") or "",
                confirm=self._describe(confirm) if confirm else "",
                variant=getattr(function, "variant", "default") or "default",
            )

        if self.transition_actions:
            actions.update(self.get_transition_actions(request))

        return actions

    # -- transitions ----------------------------------------------------------

    def get_transitions(self) -> dict[str, Any]:
        """The model's transitions this resource offers, by name.

        Read once per process, and checked: a bad declaration raises
        ``ImproperlyConfigured`` when the resource is registered.
        """
        if self._transitions is None:
            from generic.sites.transitions import read_transitions

            self._transitions = read_transitions(self)

        return self._transitions

    def get_available_transitions(self, request: Any, obj: Any) -> list[Any]:
        """The transitions ``request``'s user may take on ``obj`` now."""
        from generic.sites.transitions import available

        return available(self, request, obj)

    def get_transition_actions(self, request: Any) -> dict[str, Any]:
        """One bulk action per transition asking for nothing."""
        from generic.sites.transitions import (
            action_name,
            bulk_action,
            may_offer,
        )

        actions = {}

        for info in self.get_transitions().values():
            if info.fields or not may_offer(self, request, info):
                continue

            actions[action_name(info)] = ResourceAction(
                name=action_name(info),
                function=bulk_action(self, info),
                description=force_str(info.label),
                icon=info.icon,
                confirm=force_str(info.confirm) if info.confirm else "",
                variant=info.variant,
            )

        return actions

    @action(
        description=_("Delete selected %(verbose_name_plural)s"),
        permissions=("delete",),
        confirm=_(
            "Delete the selected %(verbose_name_plural)s? This cannot be "
            "undone."
        ),
        icon="delete",
        variant="danger",
    )
    def delete_selected(self, request: Any, queryset: QuerySet) -> dict:
        """The admin's built-in action, with the same safety net.

        Nothing is deleted when any row is protected by a relation, and
        the answer names what stands in the way.
        """
        collector = NestedObjects(using=router.db_for_write(self.model))
        collector.collect(list(queryset))

        if collector.protected:
            names = sorted({force_str(item) for item in collector.protected})

            return {
                "level": "error",
                "message": gettext(
                    "Nothing was deleted: other records depend on the "
                    "selection (%(names)s)."
                )
                % {"names": ", ".join(names[:5])},
            }

        count = 0

        with transaction.atomic():
            for instance in queryset:
                self.delete_model(request, instance)
                count += 1

        return {
            "level": "success",
            "message": ngettext(
                "%(count)s %(name)s deleted.",
                "%(count)s %(name_plural)s deleted.",
                count,
            )
            % {
                "count": count,
                "name": self.opts.verbose_name,
                "name_plural": self.opts.verbose_name_plural,
            },
        }

    # -- hooks --------------------------------------------------------------

    def save_model(
        self,
        request: Any,
        serializer: Any,
        change: bool,
    ) -> Any:
        """Write a validated serializer. Override to stamp the author."""
        return serializer.save()

    # -- editing in the table ---------------------------------------------

    def get_editable_columns(self) -> dict[str, Any]:
        """The editable columns, resolved against their models.

        Built once per process, like the serializers: these are
        declarations, so a typo is an error at start-up.
        """
        if self._editable_columns is None:
            from generic.sites.editable import columns_of

            self._editable_columns = columns_of(self)

        return self._editable_columns

    def can_edit_column(
        self,
        request: Any,
        column: str,
        obj: Any = None,
    ) -> bool:
        """Whether this column may be edited at all, before permissions.

        Override for a rule of the application's own - a field that
        freezes once the record is closed, a column only a supervisor
        touches. The model's change permission is checked as well, and
        separately.
        """
        return True

    def save_editable(
        self,
        request: Any,
        obj: Any,
        changes: dict[str, Any],
    ) -> None:
        """Write the cells of one row. The reprogrammable step.

        ``changes`` is keyed by public column name, so a row may carry
        fields of several models at once. The default resolves each one
        against its record, validates it with the same serializer the
        form uses, and saves - all of it in one transaction.

        Override to raise a workflow, write somewhere else, or refuse::

            def save_editable(self, request, obj, changes):
                if "status" in changes and obj.is_locked:
                    raise ValidationError({"status": "This is closed."})

                super().save_editable(request, obj, changes)
                notify_the_desk(obj)
        """
        from generic.sites.editable import write

        write(self, request, obj, changes)

    def create_editable(
        self,
        request: Any,
        values: dict[str, Any],
        fixed: dict[str, Any],
    ) -> Any:
        """Create the record of a row added in a grid, and return it.

        ``values`` are the row's cells, by column name - only columns
        the grid lets a new row write ever reach here. ``fixed`` is what
        the grid imposes, by field name: the ticket a timesheet row
        belongs to, what a declared grid's ``add_values`` returns.

        The default validates with the form serializer and saves through
        ``save_model``, as the add page does. Override to number the
        record, fill in the author, or create something else entirely::

            def create_editable(self, request, values, fixed):
                fixed = {**fixed, "author": request.user.pk}

                return super().create_editable(request, values, fixed)
        """
        from generic.sites.editable import create

        return create(self, request, values, fixed)

    def delete_model(self, request: Any, obj: Any) -> None:
        obj.delete()

    # -- imports ------------------------------------------------------------

    def get_importer(self, request: Any) -> Any:
        """The import of this resource for ``request``, or None."""
        from generic.sites.imports import Importer, declaration_of

        if declaration_of(self) is None:
            return None

        return Importer(self, request)

    def can_import(self, request: Any) -> bool:
        """Whether ``request``'s user may import into this resource."""
        importer = self.get_importer(request)

        return importer is not None and importer.is_allowed()

    def clean_import_row(
        self,
        request: Any,
        values: dict[str, Any],
        row_number: int,
    ) -> dict[str, Any]:
        """One row's values, converted, before the form serializer sees
        them. Return them, changed or not; raise ``ValidationError`` to
        refuse the row with a message::

            def clean_import_row(self, request, values, row_number):
                values["reference"] = values["reference"].upper()

                return values
        """
        return values

    def save_import_row(
        self,
        request: Any,
        serializer: Any,
        instance: Any,
    ) -> Any:
        """Write one imported row. ``instance`` is None for a new one.

        The default is the form's own step, ``save_model``, so a
        resource stamping its author on save stamps imported rows too.
        """
        return self.save_model(
            request, serializer, change=instance is not None
        )

    def get_viewset_class(self) -> Any:
        from generic.sites.viewsets import ResourceViewSet

        base = self.viewset_class or ResourceViewSet

        return type(
            f"{self.model.__name__}ResourceViewSet",
            (base,),
            {"resource": self, "__module__": base.__module__},
        )


def _preferences_for(request: Any) -> Any:
    """The requesting user's saved preferences, cached on the request."""
    if request is None:
        return None

    cached = getattr(request, "_generic_preferences", None)

    if cached is not None:
        return cached

    user = getattr(request, "user", None)

    if user is None or not user.is_authenticated:
        return None

    from generic.accounts.models import UserPreferences

    preferences = UserPreferences.for_user(user)
    request._generic_preferences = preferences

    return preferences

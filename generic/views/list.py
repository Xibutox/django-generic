"""Listing view."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from django.contrib import messages
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.views.generic.list import ListView

from generic.views.mixins import AccessMixin, ModelPageMixin
from generic.views.tables import ObjectColumn, ObjectTable
from generic.views.toolbar import Breadcrumb, ToolbarItem

#: Query parameter carrying the ordering, as in ``?o=-title``.
ORDER_PARAM = "o"

#: Query parameter carrying the search term.
SEARCH_PARAM = "q"


class BulkActionMixin:
    """Run an action over the selected rows.

    Declared like the admin's, but as plain methods so they can be
    tested directly::

        bulk_actions = (("archive", _("Archive selected")),)

        def bulk_action_archive(self, request, queryset):
            queryset.update(archived=True)
    """

    bulk_actions: Sequence[tuple[str, Any]] = ()

    #: Form field holding the primary keys to act on.
    selection_param = "selected"
    action_param = "action"
    select_all_param = "select_across"

    def get_bulk_actions(self) -> Sequence[tuple[str, Any]]:
        return self.bulk_actions

    def get_bulk_action_queryset(self) -> QuerySet:
        """Rows a bulk action may touch.

        Deliberately the *filtered* queryset: "select all" must mean
        everything the user is currently looking at, never the whole
        table.
        """
        return self.get_queryset()

    def get_selected_queryset(self, request: HttpRequest) -> QuerySet:
        queryset = self.get_bulk_action_queryset()

        if request.POST.get(self.select_all_param) == "1":
            return queryset

        selected = request.POST.getlist(self.selection_param)

        return queryset.filter(pk__in=selected)

    def post(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        action = request.POST.get(self.action_param, "")
        known = {name for name, _label in self.get_bulk_actions()}

        if action not in known:
            messages.warning(request, _("Unknown action."))
            return self.redirect_after_action()

        handler = getattr(self, f"bulk_action_{action}", None)

        if handler is None:
            messages.warning(
                request,
                _("This action is not available here."),
            )
            return self.redirect_after_action()

        queryset = self.get_selected_queryset(request)

        if not queryset.exists():
            messages.warning(request, _("Nothing was selected."))
            return self.redirect_after_action()

        response = handler(request, queryset)

        if response is not None:
            return response

        return self.redirect_after_action()

    def redirect_after_action(self) -> HttpResponse:
        return HttpResponseRedirect(self.request.get_full_path())


class GenericListView(
    BulkActionMixin,
    AccessMixin,
    ModelPageMixin,
    ListView,
):
    """A paginated, searchable, sortable listing.

    Minimal configuration::

        class BookListView(GenericListView):
            model = Book
            list_display = ("title", "author", "pages")
            search_fields = ("title", "author__name")
    """

    template_name = "generic/list.html"
    page_action = "list"
    permission_action = "view"
    paginate_by = 25
    context_object_name = "objects"

    #: Columns, admin style.
    list_display: Sequence[str] = ()
    #: Columns that link to the detail page. Defaults to the first.
    list_display_links: Sequence[str] | None = None
    #: ORM paths the search box spans.
    search_fields: Sequence[str] = ()
    #: Public name -> ORM path. A name absent from this cannot be
    #: ordered on, whatever the query string asks for.
    ordering_fields: dict[str, str] | None = None
    #: Default ordering when the request asks for none.
    ordering: Sequence[str] = ()

    search_placeholder: str = ""

    #: Route names used to build the toolbar and row links.
    detail_url_name: str = ""
    create_url_name: str = ""

    # -- queryset -----------------------------------------------------

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        queryset = self.apply_search(queryset)
        queryset = self.apply_ordering(queryset)

        return queryset

    def get_search_term(self) -> str:
        return (self.request.GET.get(SEARCH_PARAM) or "").strip()

    def apply_search(self, queryset: QuerySet) -> QuerySet:
        term = self.get_search_term()

        if not term or not self.search_fields:
            return queryset

        condition = Q()

        for field in self.search_fields:
            condition |= Q(**{f"{field}__icontains": term})

        return queryset.filter(condition)

    def get_ordering_fields(self) -> dict[str, str]:
        if self.ordering_fields is not None:
            return self.ordering_fields

        # Without an explicit whitelist, the displayed columns that are
        # real model fields are orderable.
        model = self.get_model()

        if model is None:
            return {}

        allowed = {}

        for name in self.list_display:
            try:
                model._meta.get_field(name)
            except Exception:
                continue

            allowed[name] = name

        return allowed

    def get_requested_ordering(self) -> list[str]:
        raw = self.request.GET.get(ORDER_PARAM)

        if not raw:
            return []

        allowed = self.get_ordering_fields()
        ordering = []

        for item in raw.split(","):
            item = item.strip()

            if not item:
                continue

            descending = item.startswith("-")
            field = allowed.get(item.lstrip("-"))

            # An unknown column is ignored rather than rejected: a
            # stale bookmark should still render the page.
            if field is None:
                continue

            ordering.append(f"-{field}" if descending else field)

        return ordering

    def apply_ordering(self, queryset: QuerySet) -> QuerySet:
        ordering = self.get_requested_ordering() or list(self.ordering)

        if ordering:
            return queryset.order_by(*ordering)

        return queryset

    # -- table --------------------------------------------------------

    def get_list_display(self) -> Sequence[str]:
        if self.list_display:
            return self.list_display

        return ("__str__",)

    def get_list_display_links(self) -> Sequence[str]:
        if self.list_display_links is not None:
            return self.list_display_links

        display = self.get_list_display()

        return display[:1]

    def get_object_url(self, instance: Any) -> str:
        if self.detail_url_name:
            try:
                return reverse(
                    self.detail_url_name,
                    kwargs={"pk": instance.pk},
                )
            except NoReverseMatch:
                return ""

        getter = getattr(instance, "get_absolute_url", None)

        return getter() if callable(getter) else ""

    def get_url_for(self) -> Callable[[Any], str] | None:
        if not self.get_list_display_links():
            return None

        return self.get_object_url

    def build_columns(self) -> list[ObjectColumn]:
        model = self.get_model()
        links = set(self.get_list_display_links())
        allowed = self.get_ordering_fields()

        return [
            ObjectColumn(
                name,
                view=self,
                model=model,
                ordering_field=allowed.get(name),
                is_link=name in links,
            )
            for name in self.get_list_display()
        ]

    def build_table(self, objects: Sequence[Any]) -> ObjectTable:
        return ObjectTable(
            self.build_columns(),
            objects,
            url_for=self.get_url_for(),
        )

    # -- chrome -------------------------------------------------------

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        if self.breadcrumbs:
            return list(self.breadcrumbs)

        return [Breadcrumb(label=self.get_page_title())]

    def get_toolbar_items(self) -> list[ToolbarItem]:
        if self.toolbar_items:
            return list(self.toolbar_items)

        if not self.create_url_name:
            return []

        meta = self.model_meta

        try:
            url = reverse(self.create_url_name)
        except NoReverseMatch:
            return []

        return [
            ToolbarItem(
                url=url,
                label=gettext("Add %(name)s") % {"name": meta.verbose_name},
                icon="add",
                variant="primary",
                permission=(f"{meta.app_label}.add_{meta.model_name}"),
            )
        ]

    def get_ordering_state(self) -> dict[str, str]:
        """Current direction per public column name.

        Drives the header arrows and the link each header points at.
        """
        raw = self.request.GET.get(ORDER_PARAM) or ""
        state = {}

        for item in raw.split(","):
            item = item.strip()

            if not item:
                continue

            state[item.lstrip("-")] = "desc" if item.startswith("-") else "asc"

        return state

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        objects = context[self.context_object_name]

        context.update(
            {
                "table": self.build_table(objects),
                "search_param": SEARCH_PARAM,
                "search_term": self.get_search_term(),
                "search_placeholder": self.search_placeholder,
                "is_searchable": bool(self.search_fields),
                "order_param": ORDER_PARAM,
                "ordering_state": self.get_ordering_state(),
                "bulk_actions": self.get_bulk_actions(),
                "selection_param": self.selection_param,
                "action_param": self.action_param,
                "select_all_param": self.select_all_param,
                "total_count": self.get_queryset().count(),
            }
        )

        return context

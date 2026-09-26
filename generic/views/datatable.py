"""Page hosting an interactive table fed by the REST API.

Where :class:`~generic.views.GenericListView` renders rows server-side,
this renders an empty table and hands the browser a configuration: the
endpoint to call and the columns to build. The columns come from the
same serializer declaration the API filters against, so the header, the
filter controls and the server agree by construction.

::

    class BookTablePage(DataTableView):
        model = Book
        viewset = BookTableViewSet
        api_url_name = "book-list"
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext
from django.views.generic.base import TemplateView

from generic.conf import generic_settings
from generic.views.mixins import AccessMixin, ModelPageMixin
from generic.views.toolbar import Breadcrumb, ToolbarItem

#: What ``filter_row`` accepts besides ``False``: the row of search
#: fields under the headers shown from the start, or behind a toolbar
#: button.
FILTER_ROW_MODES = ("open", "toggle")


def filter_row_option(owner: Any) -> str | bool:
    """The ``filter_row`` an owner declares, checked.

    A typo would otherwise reach the browser, which quietly falls back to
    the button and cannot say which class declared it.
    """
    value = owner.filter_row

    if value is not False and value not in FILTER_ROW_MODES:
        raise ImproperlyConfigured(
            f"{type(owner).__name__}.filter_row must be 'toggle', 'open' "
            f"or False, not {value!r}."
        )

    return value


class DataTableView(AccessMixin, ModelPageMixin, TemplateView):
    """Render a DataTables page bound to a ``DataTableViewSet``."""

    template_name = "generic/datatable.html"
    page_action = "list"
    permission_action = "view"

    #: The viewset whose serializer declares the columns.
    viewset: Any = None
    #: Route name of that viewset's list endpoint.
    api_url_name: str = ""
    #: Literal endpoint, when the route is not reversible.
    api_url: str = ""

    create_url_name: str = ""

    #: Whether the export buttons are offered.
    show_export: bool = True

    #: The row of search fields under the column headers: ``"open"``
    #: from the start, ``"toggle"`` behind a toolbar button, ``False``
    #: not offered.
    filter_row: str | bool = "open"

    #: Extra client options, merged over the defaults.
    table_options: dict[str, Any] = {}

    # -- configuration ------------------------------------------------

    def get_viewset(self) -> Any:
        if self.viewset is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__} must define 'viewset', the "
                f"DataTableViewSet whose columns drive the table."
            )

        return self.viewset

    def get_columns(self) -> list[dict[str, Any]]:
        return self.get_viewset().get_datatable_columns()

    def get_api_url(self) -> str:
        if self.api_url:
            return self.api_url

        if not self.api_url_name:
            raise ImproperlyConfigured(
                f"{type(self).__name__} must define 'api_url_name' or "
                f"'api_url' so the table knows what to call."
            )

        try:
            return reverse(self.api_url_name)
        except NoReverseMatch as error:
            raise ImproperlyConfigured(
                f"{type(self).__name__} could not reverse "
                f"'{self.api_url_name}'."
            ) from error

    def get_state_key(self) -> str:
        """Identifies the saved column and filter state.

        Derived from the view class, so two tables on the same site do
        not overwrite each other's saved layout.
        """
        return f"{type(self).__module__}.{type(self).__name__}"

    def get_table_options(self) -> dict[str, Any]:
        options = {
            "pageLength": generic_settings.TABLE_PAGE_SIZE,
            "stateKey": self.get_state_key(),
            "columnSelector": True,
            "filters": True,
            "filterRow": filter_row_option(self),
            "excel": self.show_export,
            "syncUrl": True,
        }
        options.update(self.table_options)

        return options

    def get_table_config(self) -> dict[str, Any]:
        return {
            "url": self.get_api_url(),
            "columns": self.get_columns(),
            "options": self.get_table_options(),
        }

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

        try:
            url = reverse(self.create_url_name)
        except NoReverseMatch:
            return []

        meta = self.model_meta
        label = (
            gettext("Add %(name)s") % {"name": meta.verbose_name}
            if meta is not None
            else gettext("Add")
        )
        permission = (
            f"{meta.app_label}.add_{meta.model_name}"
            if meta is not None
            else True
        )

        return [
            ToolbarItem(
                url=url,
                label=label,
                icon="add",
                variant="primary",
                permission=permission,
            )
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["table_config"] = self.get_table_config()

        return context

"""Generic class-based views with an admin-like interface.

Five views cover the usual CRUD surface, all sharing one page layout,
one stylesheet and one vocabulary of context variables::

    from generic.views import (
        GenericCreateView, GenericDeleteView, GenericDetailView,
        GenericListView, GenericUpdateView,
    )
"""

from generic.views.datatable import DataTableView
from generic.views.delete import (
    GenericDeleteView,
    collect_deletion_summary,
)
from generic.views.detail import GenericDetailView
from generic.views.edit import (
    GenericCreateView,
    GenericEditMixin,
    GenericUpdateView,
)
from generic.views.list import (
    ORDER_PARAM,
    SEARCH_PARAM,
    BulkActionMixin,
    GenericListView,
)
from generic.views.mixins import (
    POPUP_PARAM,
    AccessMixin,
    FieldsetMixin,
    ModelPageMixin,
    PageMixin,
    PopupMixin,
)
from generic.views.tables import ObjectColumn, ObjectRow, ObjectTable
from generic.views.toolbar import (
    Breadcrumb,
    ToolbarItem,
    toolbar_item_for_route,
)

__all__ = [
    "ORDER_PARAM",
    "POPUP_PARAM",
    "SEARCH_PARAM",
    "AccessMixin",
    "Breadcrumb",
    "BulkActionMixin",
    "DataTableView",
    "FieldsetMixin",
    "GenericCreateView",
    "GenericDeleteView",
    "GenericDetailView",
    "GenericEditMixin",
    "GenericListView",
    "GenericUpdateView",
    "ModelPageMixin",
    "ObjectColumn",
    "ObjectRow",
    "ObjectTable",
    "PageMixin",
    "PopupMixin",
    "ToolbarItem",
    "collect_deletion_summary",
    "toolbar_item_for_route",
]

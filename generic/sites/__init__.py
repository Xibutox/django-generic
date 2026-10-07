"""Declare a model once; get its screens and its API.

The admin's idea - register a model with a class describing it - applied
to an application for the people who use it, and built on the REST API::

    # myapp/resources.py
    from generic.sites import ModelResource, TabularInline, register

    class CommentInline(TabularInline):
        model = Comment
        fields = ("author", "body")

    @register(Ticket)
    class TicketResource(ModelResource):
        icon = "confirmation_number"
        list_display = ("reference", "title", "team", "status")
        search_fields = ("reference", "title")
        inlines = (CommentInline,)

    # urls.py
    from generic.sites import site

    urlpatterns = [path("", site.urls)]

That registration yields a list page backed by DataTables, add and
change pages rendered from the form schema, a delete page, and one DRF
endpoint serving the rows, the form, the exports, the bulk actions and
the autocomplete - plus a sidebar entry and command palette results.
``resources.py`` modules are imported automatically at start-up.

Or declare only the related rows, and let the model say the rest::

    auto(Supplier, related=("equipment",))

(``generic.sites.auto``: the columns, the search, the tags, the form and
the related tables and form tabs are worked out from the model.)

Rows that are not a model's - an external API's answer - get a list and
a page per row from a ``DataResource`` (``generic.sites.data``)::

    @register_data
    class ServiceResource(DataResource):
        columns = {"name": str, "uptime": float}

        def get_rows(self, request):
            return statuspage.services()

Records holding records - a category inside a category, the parts of
an assembly - unfold as a tree, a level at a time
(``generic.sites.trees``)::

    trees = (Tree("bom", through=BomLine, parent="parent", child="child"),)

Any resource may have pages of its own - a map, a timeline, a gallery,
a report - declared on it, with any content (``generic.sites.pages``)::

    @page(title=_("Map"), icon="map", template="myapp/customer_map.html")
    def map(self, request):
        return {"customers": self.get_queryset(request)}

Key figures and record cards on the dashboard
(``generic.sites.dashboard``), and records on a calendar by a date
field (``generic.sites.calendars``)::

    kpis = (Kpi("open", title=_("Open"), filters={...}, danger=50),)
    cards = (Cards("urgent", filters={...}, fields=("due_on",)),)
    calendars = (Calendar("due", date="due_on", color="priority"),)
"""

from generic.api.tags import TagStyle
from generic.sites.auto import AutoResource, auto
from generic.sites.calendars import Calendar
from generic.sites.charts import Chart, chart_payload
from generic.sites.dashboard import Cards, Kpi
from generic.sites.data import DataResource, RelatedRows, RowLink
from generic.sites.decorators import action, display
from generic.sites.grids import Grid
from generic.sites.imports import Import
from generic.sites.inlines import InlineResource, StackedInline, TabularInline
from generic.sites.pages import ResourcePage, ResourcePageView, page
from generic.sites.related import RelatedTable
from generic.sites.resources import ModelResource, ResourceAction
from generic.sites.shortcuts import Shortcut
from generic.sites.site import (
    AlreadyRegistered,
    GenericSite,
    register,
    register_data,
    site,
)
from generic.sites.sso import SsoProvider
from generic.sites.trees import Tree

__all__ = [
    "AlreadyRegistered",
    "AutoResource",
    "Calendar",
    "Cards",
    "Chart",
    "DataResource",
    "GenericSite",
    "Grid",
    "Import",
    "InlineResource",
    "Kpi",
    "ModelResource",
    "RelatedRows",
    "RelatedTable",
    "ResourceAction",
    "ResourcePage",
    "ResourcePageView",
    "RowLink",
    "Shortcut",
    "SsoProvider",
    "StackedInline",
    "TabularInline",
    "TagStyle",
    "Tree",
    "action",
    "auto",
    "chart_payload",
    "display",
    "page",
    "register",
    "register_data",
    "site",
]

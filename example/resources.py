"""The example's resources: every model, declared once.

This file is all it takes to get, for each model, a list page backed by
DataTables, a summary page with figures and related tables, add and
change pages drawn from the form schema, a delete page, one REST
endpoint behind them, a sidebar entry and command palette results. It
is imported at start-up, the way ``admin.py`` is.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db.models import Avg, Count, Q, QuerySet, Sum
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext, pgettext_lazy

from example import external
from example.models import (
    Agent,
    Article,
    ArticleFamily,
    BomLine,
    Customer,
    Equipment,
    Supplier,
    Tag,
    Team,
    Ticket,
    TicketComment,
    TimeEntry,
)
from example.pages import (
    TicketTimelineView,
    customer_map,
    customers_geojson,
)
from example.tasks import check_tickets, review_customers
from generic.api import (
    BooleanColumn,
    CharColumn,
    DateColumn,
    DateTimeColumn,
    FloatColumn,
    IntegerColumn,
    TagsColumn,
)
from generic.sites import (
    Chart,
    DataResource,
    Grid,
    Import,
    ModelResource,
    RelatedRows,
    RelatedTable,
    ResourcePage,
    RowLink,
    StackedInline,
    TabularInline,
    TagStyle,
    Tree,
    action,
    auto,
    display,
    page,
    register,
    register_data,
    site,
)
from generic.sites.realtime import announce
from generic.views.toolbar import ToolbarItem, toolbar_item_for_route

#: Tickets someone still has to act on.
OPEN_STATUSES = (Ticket.Status.OPEN, Ticket.Status.PENDING)


def next_reference() -> str:
    """The reference after the highest one: SD-1240 after SD-1239."""
    numbers = [
        int(reference.rsplit("-", 1)[-1])
        for reference in Ticket.objects.filter(
            reference__regex=r"^SD-\d+$"
        ).values_list("reference", flat=True)
    ]

    return f"SD-{max(numbers, default=999) + 1}"


#: Tags read their colours from the Tag record itself.
TAG_STYLE = TagStyle(color="color", background="background")

#: A choice has no record to hold colours: they are given by value. One
#: colour tints the tag; a background draws it exactly.
STATUS_STYLE = TagStyle(
    colors={
        Ticket.Status.OPEN: "#2563eb",
        Ticket.Status.PENDING: "#d97706",
        Ticket.Status.RESOLVED: "#16a34a",
        Ticket.Status.CLOSED: "#64748b",
    }
)
PRIORITY_STYLE = TagStyle(
    colors={
        Ticket.Priority.LOW: "#64748b",
        Ticket.Priority.NORMAL: "#0284c7",
        Ticket.Priority.HIGH: "#ea580c",
        Ticket.Priority.URGENT: {"background": "#dc2626", "color": "#ffffff"},
    }
)


def total_hours(queryset: QuerySet) -> Decimal:
    total = queryset.aggregate(total=Sum("hours"))["total"] or Decimal("0")

    # Some databases drop the trailing zeros of a sum: 1.5, not 1.50.
    return total.quantize(Decimal("0.01"))


def effort_by_team(
    chart: Chart,
    request: Any,
    queryset: QuerySet,
    period: str,
) -> dict[str, Any]:
    """Estimated against logged hours, per team: a chart computed by hand.

    Two sums over two different relations cannot share one query - the
    joins would multiply each other - which is what ``data`` is for.
    ``queryset`` holds the tickets the request's filters allow.
    """
    estimated = dict(
        queryset.order_by()
        .values_list("team")
        .annotate(total=Sum("estimated_hours"))
    )
    logged = dict(
        TimeEntry.objects.filter(ticket__in=queryset)
        .order_by()
        .values_list("ticket__team")
        .annotate(total=Sum("hours"))
    )
    teams = Team.objects.filter(pk__in={*estimated, *logged}).order_by("name")

    return {
        "categories": [team.name for team in teams],
        # With the dimension and its keys, a click can filter a table.
        "dimension": {"name": "team", "kind": "relation"},
        "keys": [team.pk for team in teams],
        "series": [
            {
                "name": gettext("Estimated"),
                "data": [estimated.get(team.pk) or 0 for team in teams],
            },
            {
                "name": gettext("Logged"),
                # A line over the bars, the way a capacity line is drawn.
                "type": "line",
                "data": [logged.get(team.pk) or 0 for team in teams],
            },
        ],
        "value": {
            "label": gettext("Hours"),
            "format": "decimal",
            "unit": "h",
            "decimals": 1,
        },
    }


# ---------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------


class CommentInline(TabularInline):
    """Comments, edited as table rows on the ticket form."""

    model = TicketComment
    fields = ("author", "body", "position")
    extra = 1
    max_num = 20
    form_overrides = {"body": {"rows": 2}}


@register(Ticket)
class TicketResource(ModelResource):
    icon = "confirmation_number"
    group = _("Support")
    order = 0
    description = _("Every request the desk is working on.")

    list_display = (
        "reference",
        "title",
        "customer",
        "team",
        "assignee",
        "tags",
        "priority",
        "status",
        "is_billable",
        "estimated_hours",
        "due_on",
        "opened_at",
        "comment_count",
    )
    search_fields = ("reference", "title", "description")
    ordering = ("-opened_at", "-pk")

    # What *may* be corrected in a table. The ticket list stays
    # read-only; the Triage grid below is where they are written.
    # Not the status: it moves through its transitions (below).
    editable_fields = ("team", "assignee", "priority", "due_on")

    # A set of tickets of the project's choosing, corrected many at
    # once: the open ones, to assign and prioritise in one sitting. It
    # is shown by a GridView (example/urls.py) at /demo/triage/, and at
    # /demo/teams/<pk>/triage/ for one team - the argument.
    grids = (
        Grid(
            "triage",
            title=_("Triage"),
            description=_(
                "Every open ticket: assign it, set its priority and its "
                "due date, and log a new one without leaving the list."
            ),
            icon="assignment_ind",
            columns=(
                "reference",
                "title",
                "customer",
                "team",
                "assignee",
                "priority",
                "status",
                "due_on",
            ),
            scope="triage_rows",
            # A new ticket needs a reference and a title, which the
            # grid never changes afterwards.
            add_fields=("reference", "title", "customer"),
            add_values="new_triage_ticket",
            page_length=25,
        ),
    )

    # Drawn as coloured tags, in the table and on the summary page. The
    # columns keep their filters: tags, a Select2 fed by the tag
    # autocomplete; status and priority, their choices.
    tag_fields = {
        "tags": TAG_STYLE,
        "status": STATUS_STYLE,
        "priority": PRIORITY_STYLE,
    }

    # Layouts offered to everyone in the Views menu. Each user can save
    # their own beside them.
    presets = {
        _("Open work"): {
            "columns": [
                "reference",
                "title",
                "customer",
                "team",
                "assignee",
                "priority",
                "status",
                "due_on",
            ],
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "any_of",
                        "value": ["open", "pending"],
                    }
                ],
            },
            "order": [["due_on", "asc"]],
        },
        # A group inside the filters: still open, and either pressing or
        # waiting for a month.
        _("Needs attention"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "any_of",
                        "value": ["open", "pending"],
                    },
                    {
                        "match": "any",
                        "conditions": [
                            {
                                "column": "priority",
                                "operator": "any_of",
                                "value": ["urgent", "high"],
                            },
                            {
                                "column": "opened_at",
                                "operator": "older_than_days",
                                "value": 30,
                            },
                        ],
                    },
                ],
            },
            "order": [["opened_at", "asc"]],
        },
        # The older flat form still works: one condition per column.
        _("Billing"): {
            "columns": [
                "reference",
                "title",
                "customer",
                "is_billable",
                "estimated_hours",
                "status",
            ],
            "filters": {"is_billable": {"operator": "exact", "value": "true"}},
        },
    }

    # "check" is an operation (example/tasks.py): its answer is a report
    # tree, drawn by the table and the ticket's page.
    actions = ("check", "mark_billable", "delete_selected")
    # The ticket's life: wait, resume, resolve, close, reopen - declared
    # on the model with django-fsm-2, offered here as buttons on its
    # page and as bulk actions on the list.
    transitions = ("status",)

    # A spreadsheet of tickets read back: new references are created,
    # known ones updated. An export of this list imports as it is -
    # headers, labels, dates - and changes nothing.
    imports = Import(
        fields=(
            "reference",
            "title",
            "customer",
            "team",
            "assignee",
            "tags",
            "priority",
            "is_billable",
            "estimated_hours",
            "due_on",
            "description",
        ),
        key="reference",
        description=_(
            "One row per ticket. A known reference updates that ticket, "
            "and an empty cell keeps its value; a new one creates it. "
            "Customers, teams and agents are named as the list shows them."
        ),
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "reference",
                    ("title", "team"),
                    "customer",
                    "description",
                    # A file: chosen here, sent with the rest of the
                    # form, downloaded from the ticket's page.
                    "attachment",
                )
            },
        ),
        (
            _("Assignment"),
            {
                "fields": (
                    ("assignee", "priority"),
                    ("status", "due_on"),
                    "tags",
                ),
                "description": _("Who is on it, and by when."),
            },
        ),
        (
            _("Billing and outcome"),
            {
                "fields": (
                    ("is_billable", "estimated_hours"),
                    "satisfaction",
                    "resolution",
                ),
                # Starts folded, unless one of its fields has an error.
                "classes": ("collapse",),
            },
        ),
        (
            _("History"),
            {
                "fields": (("opened_at", "age"),),
                # A tab of its own rather than a card below the others.
                "classes": ("tab",),
            },
        ),
    )
    # A stored value shown but not edited, and one computed below.
    readonly_fields = ("opened_at", "age")
    inlines = (CommentInline,)

    # -- summary page --------------------------------------------------

    detail_stats = ("hours_logged", "comment_total", "age")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "customer",
                    "team",
                    "assignee",
                    "status",
                    "priority",
                    "due_on",
                    "tags",
                    "opened_at",
                )
            },
        ),
        (_("Description"), {"fields": ("description", "attachment")}),
        (
            _("Billing and outcome"),
            {
                "fields": (
                    "is_billable",
                    "estimated_hours",
                    "satisfaction",
                    "resolution",
                )
            },
        ),
    )
    related_tables = (
        RelatedTable(
            "time_entries",
            description=_("Time the agents logged on this ticket."),
        ),
        RelatedTable("comments"),
    )
    # A page of each ticket of the project's own: /example/ticket/<pk>/
    # timeline/, a button on the ticket's page and an entry of each row's
    # menu. Written as a view of its own (example/pages.py), which is
    # the way for a page with more to say than a method returns.
    pages = (
        ResourcePage(
            "timeline",
            view=TicketTimelineView,
            detail=True,
            title=_("Timeline"),
            icon="timeline",
            row_menu=True,
        ),
    )

    # -- charts --------------------------------------------------------
    #
    # Computed by the database, served at api/example/ticket/charts/<name>/
    # with the table's filters. Status, priority and tags take their
    # colours from tag_fields above.

    charts = (
        Chart(
            "by_status",
            title=_("Tickets by status"),
            icon="donut_large",
            type="donut",
            group_by="status",
        ),
        Chart(
            "opened",
            title=_("Tickets opened"),
            icon="calendar_month",
            group_by="opened_at",
            split_by="priority",
            stacked=True,
            period="week",
            periods=("day", "week", "month", "quarter"),
        ),
        Chart(
            "by_tag",
            title=_("Tickets by tag"),
            icon="sell",
            group_by="tags",
            horizontal=True,
        ),
        Chart(
            "by_team",
            title=_("Tickets by team and priority"),
            icon="grid_view",
            type="heatmap",
            group_by="team",
            split_by="priority",
        ),
        Chart(
            "by_customer",
            title=_("Tickets by status and customer"),
            icon="grid_view",
            type="heatmap",
            group_by="status",
            split_by="customer",
            height="22rem",
        ),
        Chart(
            "effort",
            title=_("Estimated and logged hours"),
            icon="schedule",
            data=effort_by_team,
        ),
    )
    # Above the list: they follow its filters, and a click filters it.
    list_charts = ("by_status", "opened")

    def get_record_links(self, request: Any, ticket: Ticket) -> list[Any]:
        """Where somebody reading a ticket usually goes next.

        More than a header holds on purpose: with Watch, View on site,
        Delete and Edit, that is ten buttons, and the ones that do not
        fit fold into the toolbar's "More" menu. Each link is offered
        only to whoever may open what it leads to.
        """
        links = []
        entries = self.site.get_resource(TimeEntry)

        # The page built for correcting this ticket's hours asks for
        # both the ticket's and the entries' view permission.
        if entries and entries.has_view_permission(request):
            links.append(
                ToolbarItem(
                    url=reverse("example:ticket-work", args=[ticket.pk]),
                    label=gettext("Work on the hours"),
                    icon="edit_note",
                    variant="ghost",
                )
            )

        # The records the ticket points at, by name: "Ville de
        # Grenoble" says more than "Customer", and the icon says which.
        for record, icon in (
            (ticket.customer, "storefront"),
            (ticket.team, "groups"),
            (ticket.assignee, "person"),
        ):
            resource = record and self.site.get_resource(type(record))

            if resource and resource.has_view_permission(request, record):
                links.append(
                    ToolbarItem(
                        url=resource.get_detail_url(record.pk),
                        label=str(record),
                        icon=icon,
                        variant="ghost",
                        title=str(resource.get_label()),
                    )
                )

        # Only when the wiki is installed: None otherwise.
        wiki = toolbar_item_for_route(
            "generic_wiki:index",
            gettext("Knowledge base"),
            icon="menu_book",
            variant="ghost",
        )

        if wiki:
            links.append(wiki)

        # Somewhere else entirely, each in a tab of its own.
        links += [
            ToolbarItem(
                url=f"https://portal.example.com/tickets/{ticket.reference}/",
                label=gettext("Customer portal"),
                icon="public",
                variant="ghost",
                target="_blank",
            ),
            ToolbarItem(
                url="https://status.example.com/",
                label=gettext("Service status"),
                icon="monitor_heart",
                variant="ghost",
                target="_blank",
            ),
        ]

        return links

    # -- the Triage grid --------------------------------------------------

    def triage_rows(
        self,
        request: Any,
        queryset: QuerySet,
        team: str | None,
    ) -> QuerySet:
        """Still to be worked on; one team's when the address names one.

        The argument comes from the browser: ``int()`` refuses anything
        but a number, and the endpoint answers that with a 404.
        """
        rows = queryset.filter(status__in=OPEN_STATUSES)

        if team:
            rows = rows.filter(team=int(team))

        return rows

    def new_triage_ticket(self, request: Any, team: str | None) -> dict:
        """Where a ticket logged from the grid starts.

        The reference and the team are where their controls start: the
        reader may change them. A status the grid does not show would be
        set whatever the reader did.
        """
        values = {"reference": next_reference(), "status": Ticket.Status.OPEN}

        if team:
            values["team"] = Team.objects.get(pk=int(team))

        return values

    def get_list_queryset(self, request: Any) -> QuerySet:
        # Annotated so the column can be ordered and filtered by the
        # database rather than counted row by row.
        return (
            super()
            .get_list_queryset(request)
            .annotate(comment_count=Count("comments"))
        )

    @display(description=_("Comments"), ordering="comment_count")
    def comment_count(self, ticket: Ticket) -> int:
        return getattr(ticket, "comment_count", 0)

    @display(description=_("Comments"))
    def comment_total(self, ticket: Ticket) -> int:
        return ticket.comments.count()

    @display(description=_("Hours logged"))
    def hours_logged(self, ticket: Ticket) -> Decimal:
        return total_hours(ticket.time_entries.all())

    @display(description=_("Age"))
    def age(self, ticket: Ticket) -> str:
        return ngettext(
            "%(days)s day",
            "%(days)s days",
            ticket.age_in_days,
        ) % {"days": ticket.age_in_days}

    @action(description=_("Check"), icon="fact_check")
    def check(self, request: Any, queryset: QuerySet) -> Any:
        # Done in the request: the answer carries the whole report.
        return check_tickets.start(
            request, ids=list(queryset.values_list("pk", flat=True))
        )

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        # A ticket's page offers what applies to it: nothing to mark
        # on one that is billable already.
        if name == "mark_billable":
            return not obj.is_billable

        return super().has_record_action(request, obj, name)

    @action(description=_("Mark as billable"), icon="payments")
    def mark_billable(self, request: Any, queryset: QuerySet) -> str:
        updated = queryset.update(is_billable=True)
        announce(self, "bulk")

        return ngettext(
            "%(count)s ticket marked billable.",
            "%(count)s tickets marked billable.",
            updated,
        ) % {"count": updated}


@register(TicketComment)
class TicketCommentResource(ModelResource):
    """Edited inline on the ticket form; listed on its summary page."""

    icon = "chat"
    show_in_navigation = False

    list_display = ("position", "author", "body", "created_at")
    search_fields = ("author", "body")
    ordering = ("ticket", "position")
    fields = ("ticket", "author", "body", "position")


@register(TimeEntry)
class TimeEntryResource(ModelResource):
    icon = "schedule"
    group = _("Support")
    order = 2
    description = _("Time the agents spent on the tickets.")

    list_display = (
        "spent_on",
        "ticket",
        "ticket__status",
        "agent",
        "hours",
        "is_billable",
        "note",
    )
    search_fields = ("note", "ticket__reference", "agent__name")
    ordering = ("-spent_on", "-pk")
    fields = ("ticket", "agent", ("spent_on", "hours"), "is_billable", "note")
    actions = ("mark_billable", "delete_selected")

    # What *may* be corrected in a table. Declaring it turns nothing
    # on: this list page stays read-only, and the two places that do
    # offer it ask for it - the customer's "Time spent" tab, and the
    # page built for working one ticket (example/views.py).
    #
    # The last column is not this model's at all: it closes the
    # *ticket* from here, and asks for the ticket's change permission
    # rather than this one's.
    editable_fields = (
        "spent_on",
        "hours",
        "is_billable",
        "note",
        "agent",
        "ticket__status",
    )

    charts = (
        Chart(
            "hours_by_month",
            title=_("Hours logged"),
            icon="schedule",
            group_by="spent_on",
            split_by="is_billable",
            stacked=True,
            value=Sum("hours"),
            value_label=_("Hours"),
            unit="h",
            decimals=1,
            period="month",
            periods=("week", "month", "quarter"),
        ),
        Chart(
            "hours_by_agent",
            title=_("Hours by agent"),
            icon="support_agent",
            group_by="agent",
            value=Sum("hours"),
            value_label=_("Hours"),
            unit="h",
            decimals=1,
            horizontal=True,
            # The eight largest; the rest as "Other".
            limit=8,
        ),
    )
    list_charts = ("hours_by_month", "hours_by_agent")

    @action(description=_("Mark as billable"), icon="payments")
    def mark_billable(self, request: Any, queryset: QuerySet) -> str:
        updated = queryset.update(is_billable=True)
        announce(self, "bulk")

        return ngettext(
            "%(count)s entry marked billable.",
            "%(count)s entries marked billable.",
            updated,
        ) % {"count": updated}


# ---------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------


@register(Customer)
class CustomerResource(ModelResource):
    """The record with the most related records: the summary's case."""

    icon = "domain"
    group = _("Support")
    order = 1
    description = _("The companies the desk works for.")
    # Who opened which customer: History > Access log, and a link on
    # each customer's page (docs/trash.md).
    access_log = True

    list_display = (
        "name",
        "code",
        "segment",
        "city",
        "account_manager",
        "is_active",
        "ticket_count",
        "open_ticket_count",
    )
    search_fields = ("name", "code", "city")
    # "review" runs in the background (example/tasks.py): the table is
    # answered at once and told when the report is ready.
    actions = ("review", "delete_selected")
    # Customers kept in a spreadsheet elsewhere: matched on their code.
    imports = Import(
        fields=("code", "name", "segment", "city", "website", "is_active"),
        key="code",
    )
    ordering = ("name",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("name", "code"),
                    ("segment", "city"),
                    ("account_manager", "customer_since"),
                    "website",
                    "is_active",
                )
            },
        ),
        (_("Notes"), {"fields": ("notes",), "classes": ("collapse",)}),
    )

    detail_stats = (
        "open_tickets",
        "recent_tickets",
        "hours_logged",
        "average_satisfaction",
    )
    related_tables = (
        RelatedTable(
            "tickets",
            description=_("Every ticket raised for this customer."),
            # Charts of the ticket resource, narrowed to this customer
            # and following the tab's filters.
            charts=("by_status", "by_tag"),
        ),
        # Not a relation of Customer: a path back from the related model.
        RelatedTable(
            "time_spent",
            model=TimeEntry,
            lookup="ticket__customer",
            title=_("Time spent"),
            description=_("Time logged on this customer's tickets."),
            charts=("hours_by_agent",),
            # This tab is where the desk corrects a customer's hours,
            # so it asks for the editing the entries allow.
            editable=True,
        ),
        RelatedTable(
            "conversation",
            model=TicketComment,
            lookup="ticket__customer",
            title=_("Conversation"),
            description=_("Every comment written on their tickets."),
        ),
        # Four paths that each cross a many-valued relation: a team is
        # reached through the tickets, so the same team would arrive
        # once per ticket. The framework sees that and returns it once.
        RelatedTable(
            "teams",
            model=Team,
            lookup="tickets__customer",
            title=_("Teams involved"),
            description=_("Who has worked for this customer."),
            allow_add=False,
        ),
        RelatedTable(
            "agents",
            model=Agent,
            lookup="tickets__customer",
            title=_("Agents involved"),
            description=_("The people whose name is on their tickets."),
            columns=("name", "team", "email", "is_active"),
            allow_add=False,
        ),
        RelatedTable(
            "subjects",
            model=Tag,
            lookup="tickets__customer",
            title=_("Subjects"),
            description=_("The tags their tickets carry."),
            allow_add=False,
        ),
    )
    # Above the sections: "<related table>.<chart>".
    detail_charts = ("time_spent.hours_by_month", "tickets.opened")

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                ticket_count=Count("tickets", distinct=True),
                open_ticket_count=Count(
                    "tickets",
                    filter=Q(tickets__status__in=OPEN_STATUSES),
                    distinct=True,
                ),
            )
        )

    @action(description=_("Review"), icon="manage_search")
    def review(self, request: Any, queryset: QuerySet) -> Any:
        return review_customers.start(
            request, ids=list(queryset.values_list("pk", flat=True))
        )

    @display(description=_("Tickets"), ordering="ticket_count")
    def ticket_count(self, customer: Customer) -> int:
        return getattr(customer, "ticket_count", 0)

    # The same word as the ticket state, and the same context: the
    # framework's own "Open" is the row action, a different word.
    @display(
        description=pgettext_lazy("ticket status", "Open"),
        ordering="open_ticket_count",
    )
    def open_ticket_count(self, customer: Customer) -> int:
        return getattr(customer, "open_ticket_count", 0)

    @display(description=_("Open tickets"))
    def open_tickets(self, customer: Customer) -> int:
        return customer.tickets.filter(status__in=OPEN_STATUSES).count()

    @display(description=_("Opened in 30 days"))
    def recent_tickets(self, customer: Customer) -> int:
        since = timezone.now() - datetime.timedelta(days=30)

        return customer.tickets.filter(opened_at__gte=since).count()

    @display(description=_("Hours logged"))
    def hours_logged(self, customer: Customer) -> Decimal:
        return total_hours(TimeEntry.objects.filter(ticket__customer=customer))

    @display(description=_("Satisfaction"))
    def average_satisfaction(self, customer: Customer) -> Any:
        value = customer.tickets.aggregate(value=Avg("satisfaction"))["value"]

        return round(value, 1) if value is not None else None

    # -- Pages of its own ----------------------------------------------
    #
    # Beside the list, the forms and the summary: a page of the
    # resource, /example/customer/map/, a button on the list and an
    # entry of the navigation. The method says what the page needs; its
    # template draws it - an SVG map, then the customers' own table.

    @page(
        title=_("Customer map"),
        icon="map",
        navigation=True,
        template="example/pages/customer_map.html",
    )
    def map(self, request: Any) -> dict[str, Any]:
        # The list's own rows, counts included, as this reader may see
        # them: nobody learns of a customer here they could not list.
        customers = self.get_list_queryset(request)

        return {
            "map": customer_map(self, customers),
            "table": self.get_page_table_config(request, "map"),
        }

    # The same customers for another tool. A page may answer anything: a
    # response goes through as it is - still at the resource's address,
    # still behind its permission. No button: the map links to it.
    @page(title=_("GeoJSON"), button=False)
    def geojson(self, request: Any) -> JsonResponse:
        customers = self.get_list_queryset(request)

        return JsonResponse(customers_geojson(self, request, customers))


# ---------------------------------------------------------------------
# Organisation
# ---------------------------------------------------------------------


class AgentInline(StackedInline):
    """Agents, edited as cards on the team form."""

    model = Agent
    fields = ("name", "email", "is_active", "hired_on", "capacity_hours")
    extra = 0


@register(Team)
class TeamResource(ModelResource):
    icon = "groups"
    group = _("Organisation")
    order = 0

    list_display = ("name", "code", "is_active", "agent_count", "ticket_count")
    search_fields = ("name", "code")
    ordering = ("name",)
    fields = ("name", "code", "is_active")
    inlines = (AgentInline,)

    detail_stats = ("open_tickets", "agent_total", "hours_logged")
    related_tables = (
        RelatedTable("tickets", charts=("by_status",)),
        RelatedTable(
            "agents",
            columns=("name", "email", "is_active", "capacity_hours"),
        ),
    )

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                agent_count=Count("agents", distinct=True),
                ticket_count=Count("tickets", distinct=True),
            )
        )

    @display(description=_("Agents"), ordering="agent_count")
    def agent_count(self, team: Team) -> int:
        return getattr(team, "agent_count", 0)

    @display(description=_("Tickets"), ordering="ticket_count")
    def ticket_count(self, team: Team) -> int:
        return getattr(team, "ticket_count", 0)

    @display(description=_("Open tickets"))
    def open_tickets(self, team: Team) -> int:
        return team.tickets.filter(status__in=OPEN_STATUSES).count()

    @display(description=_("Agents"))
    def agent_total(self, team: Team) -> int:
        return team.agents.count()

    @display(description=_("Hours logged"))
    def hours_logged(self, team: Team) -> Decimal:
        return total_hours(TimeEntry.objects.filter(ticket__team=team))


@register(Agent)
class AgentResource(ModelResource):
    icon = "support_agent"
    group = _("Organisation")
    order = 1

    list_display = (
        "name",
        "email",
        "team",
        "is_active",
        "hired_on",
        "capacity_hours",
    )
    search_fields = ("name", "email")
    ordering = ("name",)

    detail_stats = ("open_assigned", "hours_this_month", "capacity_hours")
    related_tables = (
        RelatedTable("tickets", title=_("Assigned tickets")),
        RelatedTable("time_entries", title=_("Time logged")),
        RelatedTable("accounts", title=_("Accounts managed")),
    )

    @display(description=_("Open tickets"))
    def open_assigned(self, agent: Agent) -> int:
        return agent.tickets.filter(status__in=OPEN_STATUSES).count()

    @display(description=_("Hours in 30 days"))
    def hours_this_month(self, agent: Agent) -> Decimal:
        since = timezone.localdate() - datetime.timedelta(days=30)

        return total_hours(agent.time_entries.filter(spent_on__gte=since))


@register(Tag)
class TagResource(ModelResource):
    icon = "sell"
    group = _("Organisation")
    order = 2

    list_display = ("name", "preview", "color", "background", "ticket_count")
    search_fields = ("name",)
    ordering = ("name",)
    # A dozen labels, read at a glance: the search box is enough, and the
    # row of fields stays behind its button.
    filter_row = "toggle"
    fields = ("name", ("color", "background"))
    form_overrides = {
        "color": {"widget": "color"},
        "background": {"widget": "color"},
    }
    detail_stats = ("preview", "open_tickets")
    detail_fieldsets = ((None, {"fields": ("name", "color", "background")}),)

    # A many-to-many seen from the other side.
    related_tables = (RelatedTable("tickets"),)

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(ticket_count=Count("tickets"))
        )

    # A computed column drawn as a tag: the method returns the record,
    # the style reads its colours.
    @display(description=_("Tag"), tags=TAG_STYLE)
    def preview(self, tag: Tag) -> Tag:
        return tag

    @display(description=_("Tickets"), ordering="ticket_count")
    def ticket_count(self, tag: Tag) -> int:
        return getattr(tag, "ticket_count", 0)

    @display(description=_("Open tickets"))
    def open_tickets(self, tag: Tag) -> int:
        return tag.tickets.filter(status__in=OPEN_STATUSES).count()


# ---------------------------------------------------------------------
# Equipment: the minimal declaration
# ---------------------------------------------------------------------
#
# Everything above is declared by hand, column by column. These two
# lines are all the equipment has: the list, the summary, the forms,
# the delete page, the endpoint, the search, the tags of the kind and
# the state, the history - worked out from example/models.py.
#
# The related rows are the one thing named: a supplier's equipment, as
# a table on its page and a tab on its form; a piece of equipment's
# maintenance visits, the same. Maintenance is declared nowhere: it is
# given pages of its own, out of the navigation, reached from the
# equipment it belongs to.

EQUIPMENT = _("Equipment")

auto(Supplier, related=("equipment",), group=EQUIPMENT)
auto(Equipment, related=("maintenances",), group=EQUIPMENT)


# ---------------------------------------------------------------------
# Manufacturing: records holding records, as trees
# ---------------------------------------------------------------------
#
# A bill of materials is a tree of articles through a link model: an
# assembly holds components, each in its own quantity, and a component
# - a screw - goes into many assemblies. Declared once on the article,
# it is a tab on every article's page (and its *Where used*), and a
# page of the whole tree from the products nothing holds. Levels load
# as they are unfolded, a page at a time: the control cabinet's
# thousand-odd parts open as fast as the bicycle's handful.
#
# Families are the other shape: a model pointing at its parent.

MANUFACTURING = _("Manufacturing")


@register(Article)
class ArticleResource(ModelResource):
    icon = "precision_manufacturing"
    group = MANUFACTURING
    order = 0
    description = _("What is made, bought or assembled, and of what.")

    list_display = (
        "reference",
        "name",
        "kind",
        "unit",
        "unit_cost",
        "family",
        "component_count",
    )
    search_fields = ("reference", "name")
    ordering = ("reference",)
    tag_fields = {
        "kind": TagStyle(
            colors={
                "product": "#7c3aed",
                "assembly": "#2563eb",
                "part": "#0f766e",
                "material": "#b45309",
            }
        )
    }
    fields = (("reference", "name"), ("kind", "unit"), ("unit_cost", "family"))
    detail_stats = ("component_count", "used_in_count")
    trees = (
        Tree(
            "bom",
            through=BomLine,
            parent="parent",
            child="child",
            title=_("Bill of materials"),
            description=_(
                "What the article is made of, level by level: unfold a "
                "component to see its own."
            ),
            columns=("kind", "unit", "unit_cost"),
            link_columns=("position", "quantity"),
            ordering=("position", "child__reference"),
            where_used=True,
            # Every level as one table: an exploded BOM, with the
            # quantity of each component for one article.
            flat=True,
            flat_title=_("Exploded BOM"),
            quantity="quantity",
        ),
    )

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(components=Count("bom_lines"))
        )

    @display(description=_("Components"), ordering="components")
    def component_count(self, article: Article) -> int:
        components = getattr(article, "components", None)

        return article.bom_lines.count() if components is None else components

    @display(description=_("Used in"))
    def used_in_count(self, article: Article) -> int:
        return article.used_in_lines.count()


@register(BomLine)
class BomLineResource(ModelResource):
    icon = "account_tree"
    group = MANUFACTURING
    # Reached from an article: its tree's links, and their Add.
    show_in_navigation = False

    list_display = ("parent", "position", "child", "quantity", "note")
    search_fields = ("parent__reference", "child__reference", "child__name")
    fields = (("parent", "child"), ("position", "quantity"), "note")


@register(ArticleFamily)
class ArticleFamilyResource(ModelResource):
    icon = "category"
    group = MANUFACTURING
    order = 1

    list_display = ("name", "parent", "article_count")
    search_fields = ("name",)
    related_tables = (RelatedTable("articles"),)
    trees = (
        Tree(
            "families",
            parent="parent",
            title=_("Family tree"),
            columns=("article_count",),
            where_used=True,
            where_used_title=_("Belongs to"),
        ),
    )

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(article_total=Count("articles"))
        )

    @display(description=_("Articles"), ordering="article_total")
    def article_count(self, family: ArticleFamily) -> int:
        total = getattr(family, "article_total", None)

        return family.articles.count() if total is None else total


# ---------------------------------------------------------------------
# External services: rows that are not a model's
# ---------------------------------------------------------------------
#
# Nothing here is in the database: the rows are what a status API
# answers (example/external.py), a list of dicts. A DataResource gives
# them a list page - filters, search, sorting, exports - and a page per
# service, read only: there is nothing to add, change or delete.

SERVICE_STATUSES = {
    "operational": _("Operational"),
    "degraded": _("Degraded performance"),
    "partial_outage": _("Partial outage"),
    "major_outage": _("Major outage"),
    "maintenance": _("Maintenance"),
}

SERVICE_CATEGORIES = {
    "email": _("E-mail"),
    "payments": _("Payments"),
    "telephony": _("Telephony"),
    "code": _("Code"),
    "hosting": _("Hosting"),
    "monitoring": _("Monitoring"),
    "chat": _("Chat"),
    "finance": _("Accounting"),
    "documents": _("Documents"),
    "maps": _("Maps"),
    "identity": _("Identity"),
}

SERVICE_REGIONS = {
    "eu-west": _("Western Europe"),
    "eu-central": _("Central Europe"),
    "us-east": _("Eastern US"),
    "us-west": _("Western US"),
    "ap-south": _("South Asia"),
}


@register_data
class ServiceResource(DataResource):
    name = "services"
    label = _("external service")
    label_plural = _("external services")
    icon = "cloud"
    group = _("Support")
    order = 6
    description = _(
        "The services the desk relies on, as their status API reports " "them."
    )
    # Whoever works the tickets needs to know what is down.
    permission = "example.view_ticket"

    key = "id"
    ordering = ("name",)
    columns = {
        "name": CharColumn(title=_("Service")),
        "provider": CharColumn(title=_("Provider")),
        "category": TagsColumn(
            title=_("Category"),
            choices=SERVICE_CATEGORIES,
            filter_type="multiselect",
        ),
        "status": TagsColumn(
            title=_("Status"),
            choices=SERVICE_STATUSES,
            tag_style=TagStyle(
                colors={
                    "operational": "#16a34a",
                    "degraded": "#d97706",
                    "partial_outage": "#ea580c",
                    "major_outage": {
                        "background": "#dc2626",
                        "color": "#ffffff",
                    },
                    "maintenance": "#2563eb",
                }
            ),
            filter_type="multiselect",
        ),
        "uptime_90d": FloatColumn(title=_("Uptime, 90 days (%)")),
        "response_ms": IntegerColumn(title=_("Response (ms)")),
        "regions": TagsColumn(
            title=_("Regions"),
            choices=SERVICE_REGIONS,
            filter_type="multiselect",
            filter_many=True,
            orderable=False,
        ),
        "critical": BooleanColumn(title=_("Critical for the desk")),
        "last_incident": DateColumn(title=_("Last incident")),
        "checked_at": DateTimeColumn(title=_("Checked")),
        # On the service's page, and searched; hidden in the table until
        # someone asks for them.
        "description": CharColumn(title=_("Description"), visible=False),
        "status_page": CharColumn(title=_("Status page"), visible=False),
    }
    detail_stats = ("status", "uptime_90d", "response_ms")
    # A tab of the service's page: the incidents whose "service" holds
    # this service's id, as the incidents' own table - each one opening
    # on its page. An API answering /services/<id>/incidents would be
    # asked instead with rows=lambda request, service:
    # external.incidents_of(service["id"]).
    related_tables = (
        RelatedRows("incidents", resource="incidents", field="service"),
    )
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "provider",
                    "category",
                    "description",
                    "status_page",
                )
            },
        ),
        (
            _("Health"),
            {"fields": ("last_incident", "checked_at", "critical")},
        ),
        (_("Coverage"), {"fields": ("regions",)}),
    )

    def get_rows(self, request: Any) -> list[dict[str, Any]]:
        return external.services()

    # A page of each service of the project's own: data/services/<id>/
    # runbook/, a button on the service's page. The runbook is a long
    # text the list does not carry - the API answers it on its own, and
    # it is asked for here, when the page opens. What the page shows is
    # its template's: the runbook as prose, and what is going wrong now.
    @page(
        title=_("Runbook"),
        detail=True,
        icon="menu_book",
        template="example/pages/service_runbook.html",
    )
    def runbook(self, request: Any, service: dict[str, Any]) -> dict:
        return {
            "runbook": external.runbook_of(service["id"])["runbook"],
            "ongoing": [
                incident
                for incident in external.incidents_of(service["id"])
                if incident["status"] != "resolved"
            ],
            "status": SERVICE_STATUSES.get(service["status"], ""),
        }


INCIDENT_SEVERITIES = {
    "minor": _("Minor"),
    "major": _("Major"),
    "critical": _("Critical"),
}

INCIDENT_STATUSES = {
    "investigating": _("Investigating"),
    "identified": _("Identified"),
    # Watched after a fix; not the category of a service.
    "monitoring": pgettext_lazy("incident status", "Monitoring"),
    "resolved": _("Resolved"),
}


@register_data
class IncidentResource(DataResource):
    """The same API's incidents: reached from their service's page, and
    leading back to it."""

    name = "incidents"
    label = _("incident")
    label_plural = _("incidents")
    icon = "report"
    group = _("Support")
    # Found from the service they belong to, as a maintenance visit is
    # from its equipment; data/incidents/ still lists them all.
    show_in_navigation = False
    permission = "example.view_ticket"

    key = "id"
    ordering = ("-started_at",)
    # The service's name, leading to the service whose id is in
    # "service" - in the table and on the incident's page.
    links = {"service_name": RowLink("services", key="service")}
    columns = {
        "title": CharColumn(title=_("Incident")),
        "service_name": CharColumn(title=_("Service")),
        "severity": TagsColumn(
            title=_("Severity"),
            choices=INCIDENT_SEVERITIES,
            tag_style=TagStyle(
                colors={
                    "minor": "#d97706",
                    "major": "#ea580c",
                    "critical": {"background": "#dc2626", "color": "#ffffff"},
                }
            ),
            filter_type="multiselect",
        ),
        "status": TagsColumn(
            title=_("Status"),
            choices=INCIDENT_STATUSES,
            tag_style=TagStyle(
                colors={
                    "investigating": "#dc2626",
                    "identified": "#ea580c",
                    "monitoring": "#2563eb",
                    "resolved": "#16a34a",
                }
            ),
            filter_type="multiselect",
        ),
        "started_at": DateTimeColumn(title=_("Started")),
        "resolved_at": DateTimeColumn(title=_("Resolved")),
        "duration_minutes": IntegerColumn(title=_("Duration (min)")),
        "summary": CharColumn(title=_("Summary"), visible=False),
    }
    detail_stats = ("status", "severity", "duration_minutes")
    detail_fieldsets = (
        (None, {"fields": ("title", "service_name", "summary")}),
        (_("Timeline"), {"fields": ("started_at", "resolved_at")}),
    )

    def get_rows(self, request: Any) -> list[dict[str, Any]]:
        return external.incidents()


# ---------------------------------------------------------------------
# Pages that are not resources
# ---------------------------------------------------------------------
#
# The classic, server-rendered views are kept for comparison, and the
# live updates page; they join the navigation as plain links.

CLASSIC = _("Classic views")

site.add_link(
    _("Feature guide"),
    route="example:home",
    icon="menu_book",
    group=CLASSIC,
    order=0,
)
site.add_link(
    _("Ticket list"),
    route="example:ticket-list",
    icon="list_alt",
    group=CLASSIC,
    order=1,
)
site.add_link(
    _("Ticket table"),
    route="example:ticket-table",
    icon="table",
    group=CLASSIC,
    order=2,
)
site.add_link(
    _("New ticket (Django form)"),
    route="example:ticket-create",
    icon="edit_note",
    group=CLASSIC,
    order=3,
)
site.add_link(
    _("Permission-gated list"),
    route="example:ticket-list-protected",
    icon="lock",
    group=CLASSIC,
    order=4,
)
site.add_link(
    _("Triage"),
    route="example:triage",
    icon="assignment_ind",
    group=_("Support"),
    order=5,
    permission="example.view_ticket",
)
site.add_link(
    _("Live updates"),
    route="example:events",
    icon="bolt",
    group=_("Real time"),
    order=0,
)
site.add_link(
    _("Notifications"),
    route="site:notifications",
    icon="notifications",
    group=_("Real time"),
    order=1,
)

# -- The dashboard's hub ------------------------------------------------
#
# Where a desk agent goes first. Three kinds on purpose: a list the
# shortcut filters for you, a page of this project's own, and an
# address that is not this application at all.


def open_ticket_count(request: Any) -> int:
    """The figure on the card. One query, only for who can see it."""
    return Ticket.objects.filter(status__in=OPEN_STATUSES).count()


site.add_shortcut(
    _("Open tickets"),
    # A filter tree in the address: the list opens already narrowed.
    url=(
        "/example/ticket/?filters="
        '{"match":"all","conditions":[{"column":"status",'
        '"operator":"any_of","value":["open","pending"]}]}'
    ),
    icon="confirmation_number",
    description=_("Everything the desk has not answered yet."),
    count=open_ticket_count,
    permission="example.view_ticket",
    order=0,
)
site.add_shortcut(
    _("Log a ticket"),
    route="site:example_ticket_add",
    icon="add_circle",
    description=_("A customer is on the telephone right now."),
    permission="example.add_ticket",
    order=1,
)
site.add_shortcut(
    _("Time this week"),
    route="site:example_timeentry_list",
    icon="schedule",
    description=_("What the desk has spent its hours on."),
    permission="example.view_timeentry",
    order=2,
)
site.add_shortcut(
    _("The handbook"),
    route="generic_wiki:index",
    icon="menu_book",
    description=_("How the desk works, written down."),
    order=3,
)
site.add_shortcut(
    _("Django documentation"),
    url="https://docs.djangoproject.com/",
    icon="school",
    description=_("The framework underneath all of this."),
    group=_("Elsewhere"),
    order=0,
)
site.add_shortcut(
    _("Write to the desk"),
    url="mailto:support@example.test",
    icon="mail",
    description=_("An address a shortcut may point at, like any link."),
    group=_("Elsewhere"),
    order=1,
)

# -- Signing in ---------------------------------------------------------
#
# A declared provider, so the sign-in page can be seen doing what it
# does: the button first, the password form folded underneath. It
# points at a page of this example rather than at an identity provider
# - the framework speaks no protocol, and a demo that signed people in
# without one would be teaching the wrong thing.

site.add_sso_provider(
    _("Continue with Example SSO"),
    route="example:sso",
    icon="corporate_fare",
    description=_(
        "What a project wires to its own OIDC or SAML library. Here it "
        "explains itself instead."
    ),
)

site.index_template = "example/dashboard.html"


@site.index_context
def desk_shortcuts(request: Any) -> dict[str, Any]:
    """Records the dashboard links to directly, for the tour."""
    return {
        "first_ticket": Ticket.objects.order_by("pk").first(),
        "busy_team": (
            Team.objects.annotate(total=Count("tickets"))
            .filter(total__gt=0)
            .order_by("pk")
            .first()
        ),
        "busy_customer": (
            Customer.objects.annotate(total=Count("tickets"))
            .order_by("-total", "pk")
            .first()
        ),
    }

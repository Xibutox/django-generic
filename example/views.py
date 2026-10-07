"""Every generic view, wired to the support desk models.

Each class below is deliberately short: what it demonstrates is how
little a working screen costs.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, QuerySet
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from example.api import AgentTableViewSet, TicketTableViewSet
from example.models import Agent, Team, Ticket, TimeEntry
from generic.events.models import Notification, NotificationLevel
from generic.sites import site
from generic.sites.views import GridView, SiteViewMixin
from generic.views import (
    DataTableView,
    GenericCreateView,
    GenericDeleteView,
    GenericDetailView,
    GenericListView,
    GenericUpdateView,
    PageMixin,
)
from generic.views.toolbar import Breadcrumb


class ExampleHomeView(PageMixin, TemplateView):
    """Index of everything the example demonstrates.

    Inherits ``PageMixin`` rather than being a bare ``TemplateView``:
    that is what supplies the title, the breadcrumbs, the sidebar and
    the toolbar to ``generic/base.html``. A custom page joins the same
    layout by mixing it in.
    """

    template_name = "example/home.html"
    page_title = _("Support desk example")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        # Linked to directly so the reader can reach a detail, edit and
        # delete page without hunting for an id first.
        context["first_ticket"] = Ticket.objects.order_by("pk").first()

        # A team that still has tickets, so its delete page is the
        # protected case rather than the ordinary one.
        context["busy_team"] = (
            Team.objects.annotate(total=Count("tickets"))
            .filter(total__gt=0)
            .order_by("pk")
            .first()
        )

        return context


# ---------------------------------------------------------------------
# Tickets: the full CRUD set
# ---------------------------------------------------------------------


class TicketListView(GenericListView):
    """Server-rendered listing: no JavaScript needed."""

    model = Ticket
    require_permission = False
    paginate_by = 10

    list_display = (
        "reference",
        "title",
        "team",
        "assignee",
        "priority",
        "status",
        "is_billable",
        "due_on",
        "comment_count",
    )
    search_fields = ("reference", "title", "team__name", "assignee__name")
    ordering_fields = {
        "reference": "reference",
        "title": "title",
        "team": "team__name",
        "assignee": "assignee__name",
        "priority": "priority",
        "status": "status",
        "is_billable": "is_billable",
        "due_on": "due_on",
        "comment_count": "comment_count",
    }
    # Same reason as TeamListView: the comment count annotation groups
    # the query.
    ordering = ("-opened_at", "-pk")
    search_placeholder = _("Reference, subject, team or assignee")

    detail_url_name = "example:ticket-detail"
    create_url_name = "example:ticket-create"

    bulk_actions = (
        ("close", _("Mark as closed")),
        ("mark_billable", _("Mark as billable")),
    )

    def get_queryset(self) -> QuerySet:
        return (
            super()
            .get_queryset()
            .select_related("team", "assignee")
            .annotate(comment_count=Count("comments"))
        )

    # -- computed columns ---------------------------------------------

    def team(self, ticket: Ticket) -> str:
        return ticket.team.name

    team.short_description = _("Team")

    def assignee(self, ticket: Ticket) -> str:
        return ticket.assignee.name if ticket.assignee else ""

    assignee.short_description = _("Assignee")

    def comment_count(self, ticket: Ticket) -> int:
        return ticket.comment_count

    comment_count.short_description = _("Comments")

    # -- bulk actions --------------------------------------------------

    def bulk_action_close(self, request: Any, queryset: QuerySet) -> None:
        updated = queryset.update(status=Ticket.Status.CLOSED)
        messages.success(
            request,
            _("%(count)s ticket(s) closed.") % {"count": updated},
        )

    def bulk_action_mark_billable(
        self,
        request: Any,
        queryset: QuerySet,
    ) -> None:
        updated = queryset.update(is_billable=True)
        messages.success(
            request,
            _("%(count)s ticket(s) marked billable.") % {"count": updated},
        )


class TicketDetailView(GenericDetailView):
    model = Ticket
    require_permission = False
    display_fields = (
        "reference",
        "title",
        "description",
        "team",
        "assignee",
        "tags",
        "priority",
        "status",
        "is_billable",
        "estimated_hours",
        "satisfaction",
        "opened_at",
        "due_on",
        "comment_count",
    )
    list_url_name = "example:ticket-list"
    update_url_name = "example:ticket-update"
    delete_url_name = "example:ticket-delete"

    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related("team", "assignee")

    def comment_count(self, ticket: Ticket) -> int:
        return ticket.comments.count()

    comment_count.short_description = _("Comments")


TICKET_FIELDS = (
    "reference",
    "title",
    "description",
    "team",
    "assignee",
    "tags",
    "priority",
    "status",
    "is_billable",
    "estimated_hours",
    "satisfaction",
    "due_on",
)

TICKET_FIELDSETS = (
    (
        None,
        {"fields": ("reference", ("title", "team"), "description")},
    ),
    (
        "Assignment",
        {
            "fields": (("assignee", "priority"), ("status", "due_on"), "tags"),
            "description": "Who is on it, and by when.",
        },
    ),
    (
        "Billing and outcome",
        {
            "fields": (("is_billable", "estimated_hours"), "satisfaction"),
            # Starts closed, unless one of its fields has an error.
            "classes": ("collapse",),
        },
    ),
)


class TicketCreateView(GenericCreateView):
    model = Ticket
    require_permission = False
    fields = TICKET_FIELDS
    fieldsets = TICKET_FIELDSETS
    list_url_name = "example:ticket-list"
    detail_url_name = "example:ticket-detail"


class TicketUpdateView(GenericUpdateView):
    model = Ticket
    require_permission = False
    fields = TICKET_FIELDS
    fieldsets = TICKET_FIELDSETS
    readonly_fields = ("opened_display", "age_display")
    list_url_name = "example:ticket-list"
    detail_url_name = "example:ticket-detail"
    delete_url_name = "example:ticket-delete"

    def get_fieldsets(self, form: Any) -> Any:
        # A read-only section appended to the shared layout, to show a
        # value computed on the view rather than stored on the model.
        return TICKET_FIELDSETS + (
            (
                "History",
                {"fields": (("opened_display", "age_display"),)},
            ),
        )

    def opened_display(self, ticket: Ticket) -> Any:
        return ticket.opened_at

    opened_display.short_description = _("Opened at")

    def age_display(self, ticket: Ticket) -> str:
        return _("%(days)s day(s)") % {"days": ticket.age_in_days}

    age_display.short_description = _("Age")


class TicketDeleteView(GenericDeleteView):
    """Deleting a ticket cascades to its comments; the page says so."""

    model = Ticket
    require_permission = False
    list_url_name = "example:ticket-list"
    detail_url_name = "example:ticket-detail"


# ---------------------------------------------------------------------
# Teams and agents
# ---------------------------------------------------------------------


class TeamListView(GenericListView):
    model = Team
    require_permission = False
    list_display = ("name", "code", "is_active", "ticket_count")
    search_fields = ("name", "code")
    # Stated explicitly: annotating groups the query, which drops the
    # model's implicit Meta ordering and leaves pagination unstable.
    ordering = ("name",)
    detail_url_name = "example:team-detail"
    create_url_name = "example:team-create"

    def get_queryset(self) -> QuerySet:
        return super().get_queryset().annotate(ticket_count=Count("tickets"))

    def ticket_count(self, team: Team) -> int:
        return team.ticket_count

    ticket_count.short_description = _("Tickets")


class TeamDetailView(GenericDetailView):
    model = Team
    require_permission = False
    display_fields = ("name", "code", "is_active")
    list_url_name = "example:team-list"
    update_url_name = "example:team-update"
    delete_url_name = "example:team-delete"


class TeamCreateView(GenericCreateView):
    model = Team
    require_permission = False
    fields = ("name", "code", "is_active")
    list_url_name = "example:team-list"
    detail_url_name = "example:team-detail"


class TeamUpdateView(GenericUpdateView):
    model = Team
    require_permission = False
    fields = ("name", "code", "is_active")
    list_url_name = "example:team-list"
    detail_url_name = "example:team-detail"
    delete_url_name = "example:team-delete"


class TeamDeleteView(GenericDeleteView):
    """A team with tickets is protected; the page explains why."""

    model = Team
    require_permission = False
    list_url_name = "example:team-list"
    detail_url_name = "example:team-detail"


class AgentListView(GenericListView):
    model = Agent
    require_permission = False
    list_display = ("name", "email", "team", "is_active", "capacity_hours")
    search_fields = ("name", "email", "team__name")
    detail_url_name = "example:agent-detail"

    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related("team")

    def team(self, agent: Agent) -> str:
        return agent.team.name

    team.short_description = _("Team")


class AgentDetailView(GenericDetailView):
    model = Agent
    require_permission = False
    display_fields = (
        "name",
        "email",
        "team",
        "is_active",
        "hired_on",
        "capacity_hours",
    )
    list_url_name = "example:agent-list"


# ---------------------------------------------------------------------
# Interactive tables
# ---------------------------------------------------------------------


class TicketTablePage(DataTableView):
    """The DataTables page: every column type, filters and exports."""

    model = Ticket
    require_permission = False
    viewset = TicketTableViewSet
    api_url_name = "example_api:ticket-list"
    create_url_name = "example:ticket-create"
    template_name = "example/datatable.html"
    page_title = _("Tickets (interactive table)")

    # The Views menu, as on a resource's list: these layouts for
    # everyone, and each user's own saved beside them. A preset may
    # filter and sort on a computed column - here the comment count,
    # an annotation of the viewset.
    presets = {
        _("Most discussed"): {
            "columns": [
                "reference",
                "title",
                "team",
                "status",
                "comment_count",
            ],
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "comment_count",
                        "operator": "gte",
                        "value": 3,
                    }
                ],
            },
            "order": [["comment_count", "desc"]],
        },
        _("Billable, still open"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {"column": "is_billable", "operator": "is_true"},
                    {
                        "column": "status",
                        "operator": "any_of",
                        "value": ["open", "pending"],
                    },
                ],
            },
            "order": [["due_on", "asc"]],
        },
    }


class AgentTablePage(DataTableView):
    model = Agent
    require_permission = False
    viewset = AgentTableViewSet
    api_url_name = "example_api:agent-list"
    template_name = "example/datatable.html"
    page_title = _("Agents (interactive table)")


# ---------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------


class ProtectedTicketListView(TicketListView):
    """The same listing, but gated on ``example.view_ticket``.

    Signing in as ``viewer`` shows the page; ``guest`` gets a 403.
    """

    require_permission = True
    page_title = _("Tickets (permission required)")
    create_url_name = ""
    detail_url_name = "example:ticket-detail"


# ---------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------


class TicketWorkView(SiteViewMixin, TemplateView):
    """One ticket's hours, on a page built for correcting them.

    The shape a table meant for editing usually takes: not a list page
    that everybody reads, but a page about one record, showing the rows
    that belong to it, with several of their fields writable.

    Nothing is hand-written but this class. The table is the time
    entry resource's own - its columns, filters, search and exports -
    narrowed by a relation the ticket already declares, and asked for
    with ``editable=True``.
    """

    template_name = "example/ticket_work.html"
    page_subtitle = _("Correct the hours without leaving the page")

    #: The relation, as the parent resource declares it.
    RELATION = "example.ticket.time_entries"

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if request.user.is_authenticated:
            resource = site.get_resource(Ticket)
            self.ticket = get_object_or_404(
                resource.get_queryset(request),
                pk=kwargs["pk"],
            )

        return super().dispatch(request, *args, **kwargs)

    def has_permission(self) -> bool:
        """Both models: the page is a ticket's, its table the entries'."""
        entries = site.get_resource(TimeEntry)
        tickets = site.get_resource(Ticket)

        return bool(
            entries
            and entries.has_view_permission(self.request)
            and tickets
            and tickets.has_view_permission(self.request)
        )

    def get_page_title(self) -> str:
        return str(self.ticket)

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        resource = site.get_resource(Ticket)

        return [
            Breadcrumb(
                label=resource.get_label_plural(),
                url=resource.get_list_url(),
            ),
            Breadcrumb(
                label=str(self.ticket),
                url=resource.get_object_url(self.ticket.pk),
            ),
            Breadcrumb(label=gettext("Hours")),
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        bound = site.get_related_table(self.RELATION)

        context["ticket"] = self.ticket
        context["table_config"] = bound.get_table_config(
            self.request,
            self.ticket,
            # The tab on the ticket's summary reads; this page writes.
            editable=True,
        )

        return context


class TriageView(GridView):
    """Every open ticket, corrected many at once: a declared grid.

    Where the page above is about one record's rows, this one is about
    a set the project chose - ``TicketResource.grids`` says which rows,
    which columns and what a new ticket starts from. The view only adds
    the teams, to narrow the grid to one: the address's ``argument``,
    which the grid's scope reads.
    """

    grid = "example.ticket.triage"

    def get_page_title(self) -> str:
        title = super().get_page_title()
        team = self.get_team()

        return f"{title} - {team}" if team else title

    def get_team(self) -> Team | None:
        argument = self.get_argument()

        if not argument or not argument.isdigit():
            return None

        return Team.objects.filter(pk=int(argument)).first()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["teams"] = Team.objects.order_by("name")
        context["team"] = self.get_team()

        return context


class SsoDemoView(TemplateView):
    """Where the sign-in page's provider button leads, in this demo.

    A real one would go to the identity provider and come back with
    somebody signed in. This example declares no provider library and
    signs nobody in: it exists so the mechanism on the sign-in page -
    the button first, the password form folded underneath - can be
    seen and clicked without pretending to be an authentication.
    """

    template_name = "example/sso.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        # Whatever the sign-in page was going to open afterwards, so
        # the page can show that it travelled with the link.
        context["destination"] = self.request.GET.get("next", "")
        context["login_url"] = reverse("site:login")

        return context


class EventsDemoView(LoginRequiredMixin, PageMixin, TemplateView):
    """What the connection behind every page carries, in plain words.

    Nothing on it is addressed to a person - people are told things by
    notification. It is what keeps open pages up to date, and this page
    shows each frame as it arrives, with what it made happen.

    Requires a signed-in user: the consumer refuses an anonymous
    connection with close code 4001.
    """

    template_name = "example/events.html"
    page_title = _("Live updates")
    page_subtitle = _("What keeps open pages up to date")

    #: What each kind of frame does, as the log explains it. Prefixes
    #: end with a dot; the longest one that matches wins.
    MEANINGS = {
        "connection.ready": _(
            "The page connected, and the bell learned how many "
            "notifications are unread."
        ),
        "notification.created": _(
            "A notification was stored for you: the bell counts it and "
            "a toast shows it, on every page you have open."
        ),
        "notification.": _(
            "Your notifications changed: the bell follows, in every window."
        ),
        "resource.changed": _(
            "Records changed: every table, summary page and chart "
            "showing them refreshes."
        ),
        "maintenance.": _(
            "A planned restart: the banner at the top of every page "
            "follows."
        ),
        "subscription.accepted": _("This page now listens to the channel."),
        "subscription.denied": _(
            "The channel refused this page: it is not yours to listen to."
        ),
        "subscription.": _("This page stopped listening to the channel."),
        "team.queue": _(
            "A ticket of the team changed: the queue count below follows. "
            "Only the team's agents hear it."
        ),
        "": _("An event of the project's own, for its own pages."),
    }

    #: What the socket calls itself, in words a reader understands. The
    #: template looked these up already; nothing was sending them, so
    #: the badge showed the socket's own vocabulary untranslated.
    STATE_LABELS = {
        "idle": _("starting"),
        "connecting": _("connecting"),
        "open": _("connected"),
        "reconnecting": _("reconnecting"),
        "offline": _("offline"),
        "signed-out": _("signed out"),
    }

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["unread"] = (
            Notification.objects.for_user(self.request.user).unread().count()
            if self.request.user.is_authenticated
            else 0
        )
        context["state_labels"] = {
            state: str(label) for state, label in self.STATE_LABELS.items()
        }
        context["meanings"] = {
            prefix: str(meaning) for prefix, meaning in self.MEANINGS.items()
        }
        context["tickets_url"] = reverse("site:example_ticket_list")
        context["write_url"] = self.get_write_url()
        context.update(self.get_queue())

        return context

    def get_queue(self) -> dict[str, Any]:
        """The team whose queue the page follows: the reader's own, if
        they are one of its agents, else the first one."""
        from example.events import TEAM_QUEUE, queue_size

        user = self.request.user
        own = Agent.objects.filter(email__iexact=user.email).exclude(email="")
        team = (
            Team.objects.filter(pk__in=own.values("team_id")).first()
            or Team.objects.order_by("name").first()
        )

        if team is None:
            return {"queue_team": None}

        return {
            "queue_team": team,
            "queue_size": queue_size(team.pk),
            "queue_topic": TEAM_QUEUE.format(team_id=team.pk),
            # The team's own page: its tickets, to change one of them.
            "queue_url": site.get_resource(Team).get_detail_url(team.pk),
        }

    def get_write_url(self) -> str:
        """The Messages form, for whoever may send one."""
        from generic.events.models import Message

        resource = site.get_resource(Message)

        if resource is None or not resource.has_add_permission(self.request):
            return ""

        return resource.get_add_url()

    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        """Send yourself a notification."""
        if request.POST.get("action") == "notify":
            # Stored, so it survives a reload; the post_save signal
            # publishes it to this user's own stream.
            Notification.objects.create(
                user=request.user,
                title=_("A ticket needs your attention"),
                body=_("Sent from the live updates page."),
                level=NotificationLevel.WARNING,
                url="/tickets/",
            )

        return self.get(request, *args, **kwargs)

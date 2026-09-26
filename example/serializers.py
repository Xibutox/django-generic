"""Serializers: one declaration drives the table, one drives the form."""

from __future__ import annotations

from example.models import Agent, Team, Ticket, TicketComment
from generic.api import (
    BooleanColumn,
    CharColumn,
    ChoiceColumn,
    DataTableModelSerializer,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    FloatColumn,
    FormModelSerializer,
    IntegerColumn,
    MethodColumn,
)


class TicketTableSerializer(DataTableModelSerializer):
    """Every column type the framework supports, in one table."""

    reference = CharColumn(
        title="Reference",
        display_type="link",
        # Interpolated from the row, so each cell links to its own
        # ticket without a second query.
        link_url="/tickets/{id}/",
    )

    title = CharColumn(title="Subject")

    team = CharColumn(
        source="team.name",
        title="Team",
        read_only=True,
        filter_field="team__name",
        order_field="team__name",
    )

    assignee = CharColumn(
        source="assignee.name",
        title="Assignee",
        read_only=True,
        allow_null=True,
        # A multiselect fed by an autocomplete route: the list of
        # agents is too long to ship with the page.
        filter_type="multiselect",
        filter_field="assignee_id",
        order_field="assignee__name",
        value_type="integer",
        autocomplete_route="example_api:agent-autocomplete",
        placeholder="Pick agents",
        minimum_input_length=0,
    )

    # A fixed list: the choices travel with the column, so no
    # autocomplete route is needed.
    priority = ChoiceColumn(choices=Ticket.Priority.choices, title="Priority")
    status = ChoiceColumn(choices=Ticket.Status.choices, title="Status")

    is_billable = BooleanColumn(title="Billable")
    estimated_hours = DecimalColumn(
        max_digits=6,
        decimal_places=2,
        title="Estimate",
    )
    satisfaction = FloatColumn(title="Score", allow_null=True)
    # DRF serializes a timestamp as ISO 8601, which is right for an API
    # and unreadable in a cell. The column takes any strftime format.
    opened_at = DateTimeColumn(
        title="Opened",
        read_only=True,
        format="%Y-%m-%d %H:%M",
    )
    due_on = DateColumn(title="Due", allow_null=True)

    comment_count = IntegerColumn(
        title="Comments",
        read_only=True,
        # Filtering and ordering point at the annotation the viewset
        # adds, not at a stored column.
        filter_field="comment_count",
        order_field="comment_count",
    )

    age = MethodColumn(title="Age (days)")

    class Meta:
        model = Ticket
        fields = (
            "id",
            "reference",
            "title",
            "team",
            "assignee",
            "priority",
            "status",
            "is_billable",
            "estimated_hours",
            "satisfaction",
            "opened_at",
            "due_on",
            "comment_count",
            "age",
        )

    def get_age(self, ticket: Ticket) -> int:
        return ticket.age_in_days


class AgentTableSerializer(DataTableModelSerializer):
    """A second, smaller table, to show two on one site."""

    name = CharColumn(title="Agent")
    email = CharColumn(title="Email", allow_blank=True)
    team = CharColumn(
        source="team.name",
        title="Team",
        read_only=True,
        filter_field="team__name",
        order_field="team__name",
    )
    is_active = BooleanColumn(title="Active")
    hired_on = DateColumn(title="Hired", allow_null=True)
    capacity_hours = DecimalColumn(
        max_digits=5,
        decimal_places=2,
        title="Capacity",
    )

    class Meta:
        model = Agent
        fields = (
            "id",
            "name",
            "email",
            "team",
            "is_active",
            "hired_on",
            "capacity_hours",
        )


# -- Forms -------------------------------------------------------------


class TicketCommentFormSerializer(FormModelSerializer):
    """The inline collection on the ticket form."""

    class Meta:
        model = TicketComment
        fields = ("id", "ticket", "author", "body", "position")

    form_overrides = {
        "author": {"position": 0, "width": 3},
        "body": {"position": 1, "width": 7, "multiline": True},
        "position": {"position": 2, "width": 2, "label": "Order"},
    }


class TicketFormSerializer(FormModelSerializer):
    """The REST-rendered ticket form, laid out in sections."""

    class Meta:
        model = Ticket
        fields = (
            "id",
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

    form_sections = (
        {
            "name": "general",
            "title": "General",
            "description": "What the ticket is about.",
            "position": 0,
        },
        {
            "name": "assignment",
            "title": "Assignment",
            "description": "Who is on it.",
            "position": 1,
        },
        {
            "name": "billing",
            "title": "Billing and outcome",
            "description": "",
            "position": 2,
        },
    )

    form_overrides = {
        "reference": {"position": 0, "width": 4},
        "title": {"position": 1, "width": 8, "placeholder": "Short subject"},
        "description": {"position": 2, "multiline": True, "rows": 5},
        "team": {"section": "assignment", "position": 0, "width": 6},
        "assignee": {"section": "assignment", "position": 1, "width": 6},
        "tags": {"section": "assignment", "position": 2},
        "priority": {"section": "assignment", "position": 3, "width": 6},
        "status": {"section": "assignment", "position": 4, "width": 6},
        "is_billable": {"section": "billing", "position": 0},
        "estimated_hours": {"section": "billing", "position": 1, "width": 4},
        "satisfaction": {"section": "billing", "position": 2, "width": 4},
        "due_on": {"section": "billing", "position": 3, "width": 4},
    }


class TeamFormSerializer(FormModelSerializer):
    class Meta:
        model = Team
        fields = ("id", "name", "code", "is_active")

"""REST layer of the example: tables, forms and autocomplete."""

from __future__ import annotations

from django.db.models import Count, QuerySet
from rest_framework.permissions import IsAuthenticated

from example.models import Agent, Team, Ticket
from example.serializers import (
    AgentTableSerializer,
    TeamFormSerializer,
    TicketCommentFormSerializer,
    TicketFormSerializer,
    TicketTableSerializer,
)
from generic.api import (
    AutocompleteView,
    DataTableViewSet,
    InlineFormDefinition,
    ModelFormViewSet,
)


class TicketTableViewSet(DataTableViewSet):
    """Feeds the interactive ticket table, and its exports."""

    serializer_class = TicketTableSerializer
    export_file_name = "tickets"

    def get_queryset(self) -> QuerySet:
        return (
            Ticket.objects.select_related("team", "assignee")
            # Annotated so the column can be filtered and ordered on
            # the server rather than counted per row in the template.
            .annotate(comment_count=Count("comments"))
        )


class AgentTableViewSet(DataTableViewSet):
    serializer_class = AgentTableSerializer
    export_file_name = "agents"

    def get_queryset(self) -> QuerySet:
        return Agent.objects.select_related("team")


class TicketFormViewSet(ModelFormViewSet):
    """Schema-driven CRUD, with the comments edited alongside."""

    serializer_class = TicketFormSerializer
    queryset = Ticket.objects.all()

    inline_form_definitions = (
        InlineFormDefinition(
            name="comments",
            serializer_class=TicketCommentFormSerializer,
            related_name="comments",
            parent_field="ticket",
            title="Comments",
            description="Added to the ticket in the same save.",
            max_rows=20,
            add_label="Add a comment",
        ),
    )


class TeamFormViewSet(ModelFormViewSet):
    serializer_class = TeamFormSerializer
    queryset = Team.objects.all()


class AgentAutocomplete(AutocompleteView):
    """Feeds the assignee column filter.

    ``search_fields`` is a fixed whitelist: the client only ever sends
    a term, never a field to search in.
    """

    permission_classes = (IsAuthenticated,)
    queryset = Agent.objects.filter(is_active=True)
    search_fields = ("name", "email")
    label_field = "name"

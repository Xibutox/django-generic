"""REST routes, mounted as their own namespace beside the pages.

Kept separate from ``example/urls.py`` so the namespace is
``example_api:…`` rather than nested inside ``example:``, which is what
``autocomplete_route`` and ``api_url_name`` reverse against.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from example.api import (
    AgentAutocomplete,
    AgentTableViewSet,
    TeamFormViewSet,
    TicketFormViewSet,
    TicketTableViewSet,
)

app_name = "example_api"

router = DefaultRouter()
router.register("tickets", TicketTableViewSet, basename="ticket")
router.register("agents", AgentTableViewSet, basename="agent")
router.register("ticket-forms", TicketFormViewSet, basename="ticket-form")
router.register("team-forms", TeamFormViewSet, basename="team-form")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "agent-autocomplete/",
        AgentAutocomplete.as_view(),
        name="agent-autocomplete",
    ),
]

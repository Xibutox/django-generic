"""Page routes.

The REST endpoints live in ``example/api_urls.py`` under their own
``example_api`` namespace.
"""

from django.urls import path

from example import views
from generic.sites import site

app_name = "example"

urlpatterns = [
    path("", views.ExampleHomeView.as_view(), name="home"),
    # -- tickets ------------------------------------------------------
    path("tickets/", views.TicketListView.as_view(), name="ticket-list"),
    path(
        "tickets/table/",
        views.TicketTablePage.as_view(),
        name="ticket-table",
    ),
    path(
        "tickets/protected/",
        views.ProtectedTicketListView.as_view(),
        name="ticket-list-protected",
    ),
    path(
        "tickets/add/",
        views.TicketCreateView.as_view(),
        name="ticket-create",
    ),
    path(
        "tickets/<int:pk>/",
        views.TicketDetailView.as_view(),
        name="ticket-detail",
    ),
    path(
        "tickets/<int:pk>/change/",
        views.TicketUpdateView.as_view(),
        name="ticket-update",
    ),
    path(
        "tickets/<int:pk>/delete/",
        views.TicketDeleteView.as_view(),
        name="ticket-delete",
    ),
    # -- teams ---------------------------------------------------------
    path("teams/", views.TeamListView.as_view(), name="team-list"),
    path("teams/add/", views.TeamCreateView.as_view(), name="team-create"),
    path(
        "teams/<int:pk>/",
        views.TeamDetailView.as_view(),
        name="team-detail",
    ),
    path(
        "teams/<int:pk>/change/",
        views.TeamUpdateView.as_view(),
        name="team-update",
    ),
    path(
        "teams/<int:pk>/delete/",
        views.TeamDeleteView.as_view(),
        name="team-delete",
    ),
    # -- agents ---------------------------------------------------------
    path("agents/", views.AgentListView.as_view(), name="agent-list"),
    path(
        "agents/table/",
        views.AgentTablePage.as_view(),
        name="agent-table",
    ),
    path(
        "agents/<int:pk>/",
        views.AgentDetailView.as_view(),
        name="agent-detail",
    ),
    # -- events ----------------------------------------------------------
    path("events/", views.EventsDemoView.as_view(), name="events"),
    # A page about one record whose table is meant to be written in.
    path(
        "tickets/<int:pk>/work/",
        views.TicketWorkView.as_view(site=site),
        name="ticket-work",
    ),
    # A declared grid: every open ticket, then one team's - the grid's
    # argument, read from the address.
    path("triage/", views.TriageView.as_view(site=site), name="triage"),
    path(
        "teams/<str:argument>/triage/",
        views.TriageView.as_view(site=site),
        name="team-triage",
    ),
    # Where the sign-in page's provider button leads, in this demo.
    path("sso/", views.SsoDemoView.as_view(), name="sso"),
]

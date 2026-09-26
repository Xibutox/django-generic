"""The example project must keep working.

It is a deliverable, not scaffolding: a reader copies from it. These
tests are deliberately broad rather than deep - the framework's own
behaviour is covered elsewhere, and what matters here is that every
page and endpoint the example advertises still answers.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from example.models import Agent, Tag, Team, Ticket, TicketComment

pytestmark = pytest.mark.django_db


@pytest.fixture
def desk(db) -> dict:
    """A miniature version of what seed_example builds."""
    team = Team.objects.create(name="Front office", code="FO")
    empty_team = Team.objects.create(name="Spare", code="SP")

    agent = Agent.objects.create(
        name="Camille Rousseau",
        email="camille@example.test",
        team=team,
        capacity_hours=Decimal("35.00"),
    )
    tag = Tag.objects.create(name="regression")

    ticket = Ticket.objects.create(
        reference="SD-1000",
        title="Login fails after password reset",
        team=team,
        assignee=agent,
        priority=Ticket.Priority.HIGH,
        status=Ticket.Status.OPEN,
        is_billable=True,
        estimated_hours=Decimal("2.00"),
        due_on=datetime.date(2026, 6, 1),
    )
    ticket.tags.add(tag)

    TicketComment.objects.create(
        ticket=ticket,
        author="Camille Rousseau",
        body="Reproduced on staging.",
        position=1,
    )

    return {
        "team": team,
        "empty_team": empty_team,
        "agent": agent,
        "ticket": ticket,
    }


def example_urls(desk: dict) -> list[str]:
    ticket = desk["ticket"].pk
    team = desk["team"].pk
    agent = desk["agent"].pk

    return [
        "/example/",
        "/example/tickets/",
        "/example/tickets/table/",
        "/example/tickets/add/",
        f"/example/tickets/{ticket}/",
        f"/example/tickets/{ticket}/change/",
        f"/example/tickets/{ticket}/delete/",
        "/example/teams/",
        "/example/teams/add/",
        f"/example/teams/{team}/",
        f"/example/teams/{team}/change/",
        f"/example/teams/{team}/delete/",
        "/example/agents/",
        "/example/agents/table/",
        f"/example/agents/{agent}/",
        "/example/events/",
        "/example/api/tickets/",
        "/example/api/tickets/?format=datatables",
        "/example/api/agents/",
        "/example/api/ticket-forms/form-schema/",
        f"/example/api/ticket-forms/{ticket}/",
        f"/example/api/ticket-forms/{ticket}/deletion-preview/",
        "/example/api/agent-autocomplete/",
        "/example/api/tickets/export-csv/",
    ]


class TestEveryPageAnswers:
    def test_all_urls_render(self, auth_client, desk):
        failures = []

        for url in example_urls(desk):
            response = auth_client.get(url)

            if response.status_code >= 400:
                failures.append((url, response.status_code))

        assert failures == []


class TestTicketTable:
    URL = "/example/api/tickets/"

    def test_every_declared_column_is_advertised(self, auth_client, desk):
        from example.api import TicketTableViewSet

        names = {
            column["data"]
            for column in TicketTableViewSet.get_datatable_columns()
        }

        # The point of the example is that one table shows them all.
        assert names >= {
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
        }

    def test_the_choice_columns_carry_their_choices(
        self,
        auth_client,
        desk,
    ):
        from example.api import TicketTableViewSet

        columns = {
            column["data"]: column
            for column in TicketTableViewSet.get_datatable_columns()
        }

        assert columns["priority"]["choices"]
        assert columns["status"]["choices"]

    def test_the_assignee_column_resolves_its_autocomplete_route(
        self,
        auth_client,
        desk,
    ):
        from example.api import TicketTableViewSet

        columns = {
            column["data"]: column
            for column in TicketTableViewSet.get_datatable_columns()
        }

        assert columns["assignee"]["autocompleteUrl"].endswith(
            "/agent-autocomplete/"
        )

    def test_the_annotated_column_can_be_ordered(
        self,
        auth_client,
        desk,
    ):
        response = auth_client.get(
            self.URL,
            {"ordering": "-comment_count"},
        )

        assert response.status_code == 200

    def test_an_undeclared_column_cannot_be_filtered(
        self,
        auth_client,
        desk,
    ):
        response = auth_client.get(
            self.URL,
            {
                "advanced_filters": (
                    '{"description": {"operator": "contains", '
                    '"value": "x"}}'
                )
            },
        )

        assert response.status_code == 400


class TestDeleteRules:
    def test_a_team_with_tickets_is_protected(self, auth_client, desk):
        url = f"/example/teams/{desk['team'].pk}/delete/"
        response = auth_client.get(url)

        assert response.context["deletion"]["can_delete"] is False

        # And posting anyway changes nothing.
        auth_client.post(url)
        assert Team.objects.filter(pk=desk["team"].pk).exists()

    def test_an_unused_team_can_be_deleted(self, auth_client, desk):
        url = f"/example/teams/{desk['empty_team'].pk}/delete/"

        assert auth_client.get(url).context["deletion"]["can_delete"]

        auth_client.post(url)

        assert not Team.objects.filter(pk=desk["empty_team"].pk).exists()

    def test_deleting_a_ticket_previews_its_comments(
        self,
        auth_client,
        desk,
    ):
        response = auth_client.get(
            f"/example/tickets/{desk['ticket'].pk}/delete/"
        )

        assert "Reproduced on staging." in response.content.decode()


class TestInlineComments:
    URL = "/example/api/ticket-forms/"

    def test_the_schema_describes_the_inline(self, auth_client, desk):
        response = auth_client.get(f"{self.URL}form-schema/")
        inlines = response.data["inlines"]

        assert [inline["name"] for inline in inlines] == ["comments"]
        names = {field["name"] for field in inlines[0]["fields"]}

        # The parent link is supplied on save, never edited.
        assert "ticket" not in names
        assert {"author", "body", "position"} <= names

    def test_comments_are_saved_with_the_ticket(
        self,
        auth_client,
        desk,
    ):
        ticket = desk["ticket"]

        response = auth_client.patch(
            f"{self.URL}{ticket.pk}/",
            {
                "title": "Login fails, revised",
                "_inlines": {
                    "comments": [
                        {"author": "Yanis", "body": "Fixed.", "position": 2}
                    ]
                },
            },
            format="json",
            content_type="application/json",
        )

        assert response.status_code == 200, response.data

        ticket.refresh_from_db()
        assert ticket.title == "Login fails, revised"
        assert ticket.comments.count() == 2


class TestLiveUpdates:
    URL = "/example/events/"

    def test_every_frame_is_explained(self, auth_client):
        meanings = auth_client.get(self.URL).context["meanings"]

        assert "resource.changed" in meanings
        assert "notification.created" in meanings
        # The fallback, for a project's own event types.
        assert meanings[""]

    def test_sending_a_notification_to_oneself(self, auth_client, user):
        from generic.events.models import Notification

        auth_client.post(self.URL, {"action": "notify"})

        assert Notification.objects.filter(user=user).count() == 1

    def test_nothing_else_pretends_to_be_a_message(self, auth_client, user):
        """The passing message and the broadcast are gone: they reached
        no one but this page's log, which is not how people are told."""
        from generic.events.models import Notification

        for action in ("transient", "broadcast", "topic"):
            response = auth_client.post(self.URL, {"action": action})

            assert response.status_code == 200

        assert Notification.objects.count() == 0

    def test_a_sender_is_shown_the_way_to_write(self, admin_client):
        response = admin_client.get(self.URL)

        assert response.context["write_url"].endswith("/message/add/")

    def test_it_follows_the_reader_s_own_team(
        self,
        client,
        django_user_model,
        desk,
    ):
        camille = django_user_model.objects.create_user(
            username="camille",
            email="camille@example.test",
            password="x",
        )
        client.force_login(camille)

        context = client.get(self.URL).context

        assert context["queue_team"] == desk["team"]
        assert context["queue_topic"] == f"team.{desk['team'].pk}"
        assert context["queue_size"] == 1

    def test_anyone_else_sees_the_first_team(self, auth_client, desk):
        context = auth_client.get(self.URL).context

        assert context["queue_team"] == desk["team"]


class TestTeamQueue:
    """example/events.py: a channel per team, and what is said on it."""

    @pytest.fixture
    def said(self, monkeypatch):
        said = []
        monkeypatch.setattr(
            "example.events.publish_to_topic",
            lambda name, kind, payload, parameters: said.append(
                (kind, payload, parameters)
            ),
        )

        return said

    def test_the_channel_is_declared(self):
        from generic.events import registry

        assert registry.get("team.{team_id}") is not None

    def test_it_is_for_the_team_s_agents(
        self,
        django_user_model,
        user,
        admin_user,
        desk,
    ):
        from generic.events import registry

        topic = registry.get("team.{team_id}")
        team = {"team_id": str(desk["team"].pk)}
        other = {"team_id": str(desk["empty_team"].pk)}
        camille = django_user_model.objects.create_user(
            username="camille",
            email="camille@example.test",
            password="x",
        )

        assert topic.allows(camille, team) is True
        assert topic.allows(camille, other) is False
        assert topic.allows(user, team) is False
        assert topic.allows(admin_user, other) is True

    def test_a_ticket_change_says_the_team_s_new_count(self, desk, said):
        ticket = desk["ticket"]
        ticket.status = Ticket.Status.CLOSED
        ticket.save()

        assert said == [
            (
                "team.queue",
                {"team": desk["team"].pk, "open": 0},
                {"team_id": str(desk["team"].pk)},
            )
        ]

    def test_a_ticket_that_moves_tells_both_teams(self, desk, said):
        ticket = desk["ticket"]
        ticket.team = desk["empty_team"]
        ticket.save()

        counts = {payload["team"]: payload["open"] for _, payload, _ in said}

        assert counts == {desk["team"].pk: 0, desk["empty_team"].pk: 1}

    def test_closing_in_bulk_tells_the_team_too(self, desk, said):
        """update() sends no signal: the action tells the teams itself."""
        from example.models import Ticket as Model
        from generic.sites import site

        site.get_resource(Model).close(None, Model.objects.all())

        assert said[-1][1] == {"team": desk["team"].pk, "open": 0}


class TestTicketLinks:
    """A ticket's page offers more buttons than its header holds, on
    purpose: it is where the folding toolbar is seen at work."""

    def urls(self, client, ticket) -> list[str]:
        page = client.get(f"/example/ticket/{ticket.pk}/")

        return [item.url for item in page.context["toolbar_items"]]

    def test_it_leads_to_the_records_it_points_at(
        self,
        admin_client,
        support_desk,
    ):
        ticket = support_desk["login"]
        urls = self.urls(admin_client, ticket)

        assert f"/example/team/{ticket.team.pk}/" in urls
        assert f"/example/agent/{ticket.assignee.pk}/" in urls
        assert "https://status.example.com/" in urls
        # Ten buttons or so: more than any header holds.
        assert len(urls) >= 9

    def test_only_to_those_the_reader_may_open(
        self,
        worker_client,
        support_desk,
    ):
        """The desk agent may read teams and agents, not customers."""
        from example.models import Customer

        ticket = support_desk["login"]
        ticket.customer = Customer.objects.create(name="Northwind", code="NW")
        ticket.save()

        urls = self.urls(worker_client, ticket)

        assert f"/example/agent/{ticket.assignee.pk}/" in urls
        assert f"/example/customer/{ticket.customer.pk}/" not in urls

    def test_a_missing_relation_is_no_button(self, admin_client, support_desk):
        ticket = support_desk["export"]  # nobody assigned

        assert not any(
            "/example/agent/" in url for url in self.urls(admin_client, ticket)
        )

    def test_the_page_draws_the_more_menu(self, admin_client, support_desk):
        page = admin_client.get(f"/example/ticket/{support_desk['login'].pk}/")

        assert b'x-data="pageToolbar"' in page.content
        assert b"data-toolbar-more" in page.content

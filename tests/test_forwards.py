"""Dependent relations: a field's options follow another field.

The example's ticket declares ``Forward("assignee", on="team",
lookup="team")``: its form offers the agents of the team chosen, and a
save holds the pair to it.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Agent, Ticket
from generic.sites import Forward, site
from generic.sites.forwards import forwards_of

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/"
AGENTS = "/api/example/agent/autocomplete/"


def suggested(client, **params) -> list[str]:
    response = client.get(AGENTS, {"q": "", **params})
    assert response.status_code == 200, response.content

    return [row["text"] for row in response.json()["results"]]


def forwarded(team) -> dict:
    return {
        "forward_from": "example.ticket",
        "forward_field": "assignee",
        "forward_value": str(team.pk),
    }


def assignee_of(schema: dict) -> dict:
    return next(
        field for field in schema["fields"] if field["name"] == "assignee"
    )


class TestTheDeclaration:
    def test_a_lookup_or_a_filter_is_given(self):
        with pytest.raises(ImproperlyConfigured):
            Forward("assignee", on="team")

        with pytest.raises(ImproperlyConfigured):
            Forward(
                "assignee",
                on="team",
                lookup="team",
                filter=lambda queryset, value, request: queryset,
            )

    def test_the_resource_lists_them_by_field(self):
        resource = site.get_resource(Ticket)

        assert set(forwards_of(resource)) == {"assignee"}

    def test_the_form_tells_the_field_what_it_follows(self, admin_client):
        schema = admin_client.get(f"{TICKETS}form-schema/").json()

        assert assignee_of(schema)["forward"] == {
            "on": "team",
            "from": "example.ticket",
            "field": "assignee",
            "clear": True,
        }


class TestTheAutocomplete:
    def test_only_the_agents_of_the_team_are_offered(
        self, admin_client, support_desk
    ):
        front = support_desk["login"].team

        assert suggested(admin_client, **forwarded(front)) == [
            "Camille Rousseau"
        ]

    def test_without_a_team_every_agent_is(self, admin_client, support_desk):
        params = {**forwarded(support_desk["login"].team), "forward_value": ""}

        assert len(suggested(admin_client, **params)) == Agent.objects.count()

    def test_a_search_of_its_own_is_not_narrowed(
        self, admin_client, support_desk
    ):
        assert len(suggested(admin_client)) == Agent.objects.count()

    def test_a_forward_nobody_declared_narrows_nothing(
        self, admin_client, support_desk
    ):
        params = {
            **forwarded(support_desk["login"].team),
            "forward_field": "customer",
        }

        assert len(suggested(admin_client, **params)) == Agent.objects.count()

    def test_a_value_of_the_wrong_kind_matches_nothing(
        self, admin_client, support_desk
    ):
        params = {
            **forwarded(support_desk["login"].team),
            "forward_value": "abc",
        }

        assert suggested(admin_client, **params) == []

    def test_the_labels_of_held_values_are_not_narrowed(
        self, admin_client, support_desk
    ):
        """A ticket of another team's agent, saved before the rule,
        still shows whom it is assigned to."""
        yanis = support_desk["invoice"].assignee
        response = admin_client.get(
            AGENTS,
            {"ids": str(yanis.pk), **forwarded(support_desk["login"].team)},
        )

        assert [row["text"] for row in response.json()["results"]] == [
            yanis.name
        ]

    def test_a_reader_who_may_not_use_the_form_is_not_narrowed(
        self, django_user_model, client, support_desk
    ):
        reader = django_user_model.objects.create_user("reader", password="x")
        reader.user_permissions.add(
            Permission.objects.get(codename="view_agent"),
            Permission.objects.get(codename="view_ticket"),
        )
        client.force_login(reader)

        params = forwarded(support_desk["login"].team)

        assert len(suggested(client, **params)) == Agent.objects.count()


class TestAnAutocompleteView:
    def test_it_is_narrowed_too(self, admin_user, support_desk):
        """The endpoint an ``autocompleteUrl`` override names."""
        from rest_framework.test import APIRequestFactory, force_authenticate

        from generic.api import AutocompleteView

        class Agents(AutocompleteView):
            queryset = Agent.objects.all()
            search_fields = ("name",)
            label_field = "name"

        request = APIRequestFactory().get(
            "/", {"q": "", **forwarded(support_desk["login"].team)}
        )
        force_authenticate(request, admin_user)
        response = Agents.as_view()(request)

        assert [row["text"] for row in response.data["results"]] == [
            "Camille Rousseau"
        ]


class TestSaving:
    def test_an_agent_of_another_team_is_refused(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        yanis = support_desk["invoice"].assignee

        response = admin_client.patch(
            f"{TICKETS}{login.pk}/",
            {"assignee": yanis.pk},
            content_type="application/json",
        )
        login.refresh_from_db()

        assert response.status_code == 400
        assert "assignee" in response.json()
        assert login.assignee.name == "Camille Rousseau"

    def test_an_agent_of_the_team_is_taken(self, admin_client, support_desk):
        login = support_desk["login"]
        yanis = support_desk["invoice"].assignee

        response = admin_client.patch(
            f"{TICKETS}{login.pk}/",
            {"team": yanis.team_id, "assignee": yanis.pk},
            content_type="application/json",
        )
        login.refresh_from_db()

        assert response.status_code == 200, response.content
        assert login.assignee == yanis

    def test_a_cell_moving_the_ticket_leaves_it_unassigned(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        infra = support_desk["invoice"].team

        response = admin_client.patch(
            f"{TICKETS}{login.pk}/cells/",
            {"team": infra.pk},
            content_type="application/json",
        )
        login.refresh_from_db()

        assert response.status_code == 200, response.content
        assert login.team == infra
        assert login.assignee is None

    def test_a_pair_saved_before_the_rule_is_left_alone(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        yanis = support_desk["invoice"].assignee
        Ticket.objects.filter(pk=login.pk).update(assignee=yanis)

        response = admin_client.patch(
            f"{TICKETS}{login.pk}/cells/",
            {"priority": "low"},
            content_type="application/json",
        )
        login.refresh_from_db()

        assert response.status_code == 200, response.content
        assert login.assignee == yanis

    def test_a_filter_decides_with_the_request(
        self, admin_client, support_desk, monkeypatch
    ):
        """A ``filter`` sees the value and the request, for a rule a
        lookup cannot say - here, nobody at all."""
        resource = site.get_resource(Ticket)
        monkeypatch.setattr(
            resource,
            "forwards",
            (
                Forward(
                    "assignee",
                    on="team",
                    filter=lambda queryset, value, request: queryset.none(),
                ),
            ),
        )
        login = support_desk["login"]
        camille = login.assignee

        assert suggested(admin_client, **forwarded(login.team)) == []

        response = admin_client.patch(
            f"{TICKETS}{login.pk}/",
            {"assignee": None},
            content_type="application/json",
        )
        assert response.status_code == 200, response.content

        response = admin_client.patch(
            f"{TICKETS}{login.pk}/",
            {"assignee": camille.pk},
            content_type="application/json",
        )
        assert response.status_code == 400

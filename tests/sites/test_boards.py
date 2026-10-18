"""Boards: a resource's records as cards, a column per value of a field.

The example declares one on tickets, by priority, coloured by status,
editable: a ticket dragged to another column gets that priority.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Agent, Ticket
from generic.sites import Board, ModelResource, site
from generic.sites.boards import MAX_CARDS, bind_board

pytestmark = pytest.mark.django_db

BOARD = "/api/example/ticket/boards/priorities/"
PAGE = "/example/ticket/priorities/"


def move_url(ticket) -> str:
    return f"/api/example/ticket/{ticket.pk}/boards/priorities/"


def board(client, **params) -> dict:
    response = client.get(BOARD, params)

    assert response.status_code == 200, response.content

    return response.json()


def by_key(answer: dict) -> dict:
    return {column["key"]: column for column in answer["columns"]}


def move(client, ticket, column):
    return client.patch(
        move_url(ticket),
        {"column": column},
        content_type="application/json",
    )


@pytest.fixture
def reader_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="reader")
    user.user_permissions.set(
        Permission.objects.filter(codename="view_ticket")
    )
    client.force_login(user)

    return client


class TestTheColumns:
    def test_a_column_per_choice_in_its_order(
        self, admin_client, support_desk
    ):
        answer = board(admin_client)

        assert [column["key"] for column in answer["columns"]] == [
            "low",
            "normal",
            "high",
            "urgent",
        ]
        assert [column["label"] for column in answer["columns"]] == [
            "Low",
            "Normal",
            "High",
            "Urgent",
        ]
        assert answer["editable"] is True

    def test_each_holds_its_records_and_their_count(
        self, admin_client, support_desk
    ):
        columns = by_key(board(admin_client))

        assert [card["label"][:4] for card in columns["high"]["cards"]] == [
            "SD-1"
        ]
        assert columns["high"]["count"] == 1
        assert columns["urgent"]["cards"] == []
        assert columns["urgent"]["count"] == 0

    def test_a_column_takes_the_colour_of_its_tag(
        self, admin_client, support_desk
    ):
        high = by_key(board(admin_client))["high"]

        assert high["color"] or high["background"]

    def test_a_card_carries_its_page_colour_and_values(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        card = by_key(board(admin_client))["high"]["cards"][0]

        assert card["id"] == str(login.pk)
        assert card["url"] == f"/example/ticket/{login.pk}/"
        assert card["column"] == "high"
        # Coloured by its status, as the example's tag style draws it.
        assert card["color"] or card["background"]
        assert [cell["label"] for cell in card["cells"]] == [
            "Team",
            "Assignee",
            "Due on",
        ]

    def test_the_table_s_filters_and_search_apply(
        self, admin_client, support_desk
    ):
        tree = {
            "match": "all",
            "conditions": [
                {"column": "priority", "operator": "any_of", "value": ["low"]}
            ],
        }
        filtered = by_key(board(admin_client, filters=json.dumps(tree)))
        searched = by_key(board(admin_client, search="invoice"))

        assert filtered["low"]["count"] == 1
        assert filtered["normal"]["count"] == 0
        assert searched["normal"]["count"] == 1
        assert searched["high"]["count"] == 0

    def test_a_long_column_says_it_is_cut(self, admin_client, support_desk):
        team = support_desk["front"]
        Ticket.objects.bulk_create(
            Ticket(
                reference=f"BULK-{index}",
                title=f"Bulk {index}",
                team=team,
                priority=Ticket.Priority.URGENT,
            )
            for index in range(MAX_CARDS + 3)
        )
        urgent = by_key(board(admin_client))["urgent"]

        assert urgent["count"] == MAX_CARDS + 3
        assert len(urgent["cards"]) == MAX_CARDS
        assert urgent["truncated"] is True

    def test_refused_without_the_view_permission(
        self, client, django_user_model, support_desk
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))

        assert client.get(BOARD).status_code == 403

    def test_an_unknown_board_is_not_found(self, admin_client):
        response = admin_client.get("/api/example/ticket/boards/nope/")

        assert response.status_code == 404

    def test_a_reader_sees_cards_they_cannot_move(
        self, reader_client, support_desk
    ):
        answer = board(reader_client)

        assert answer["editable"] is False
        assert not by_key(answer)["high"]["cards"][0]["editable"]


class TestMovingACard:
    def test_a_card_takes_the_column_s_value(self, admin_client, support_desk):
        login = support_desk["login"]
        response = move(admin_client, login, "urgent")
        login.refresh_from_db()

        assert response.status_code == 200, response.content
        assert login.priority == "urgent"
        assert response.json()["column"] == "urgent"

    def test_a_column_the_board_lacks_is_refused(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]
        response = move(admin_client, login, "whenever")
        login.refresh_from_db()

        assert response.status_code == 400
        assert login.priority == "high"

    def test_refused_without_the_change_permission(
        self, reader_client, support_desk
    ):
        login = support_desk["login"]

        assert move(reader_client, login, "low").status_code == 403

    def test_the_cell_writer_s_rules_apply(
        self, admin_client, support_desk, monkeypatch
    ):
        resource = site.get_resource(Ticket)
        monkeypatch.setattr(
            resource,
            "can_edit_column",
            lambda request, column, obj=None: column != "priority",
        )
        login = support_desk["login"]

        assert move(admin_client, login, "low").status_code == 400

    def test_the_page_is_drawn(self, admin_client, support_desk):
        response = admin_client.get(PAGE)

        assert response.status_code == 200
        assert b'class="generic-board"' in response.content
        assert b"board-filter-table" in response.content


class TestARelation:
    """A foreign key: a column per related record, and the records
    without one."""

    @pytest.fixture
    def by_assignee(self):
        class Tickets(ModelResource):
            list_display = ("title", "assignee")
            editable_fields = ("assignee",)

        return bind_board(
            Board("people", field="assignee", editable=True),
            Tickets(Ticket, site),
        )

    @pytest.fixture
    def admin_request(self, rf, admin_user):
        request = rf.get("/")
        request.user = admin_user

        return request

    def test_a_column_per_record_and_one_for_none(
        self, by_assignee, admin_request, support_desk
    ):
        columns = by_assignee.get_columns(admin_request)
        agents = list(Agent.objects.all())

        assert [column.key for column in columns] == [
            *(agent.pk for agent in agents),
            None,
        ]
        assert columns[-1].label == "Not set"

    def test_the_records_without_one_are_in_the_last(
        self, by_assignee, admin_request, support_desk
    ):
        answer = by_assignee.answer(
            admin_request, Ticket.objects.order_by("pk")
        )
        empty = answer["columns"][-1]

        assert empty["key"] is None
        assert (
            empty["count"]
            == Ticket.objects.filter(assignee__isnull=True).count()
        )

    def test_a_card_moves_to_a_record_and_back_to_none(
        self, by_assignee, admin_request, support_desk
    ):
        login = support_desk["login"]
        yanis = support_desk["yanis"]

        by_assignee.move(admin_request, login, {"column": yanis.pk})
        login.refresh_from_db()
        assert login.assignee == yanis

        by_assignee.move(admin_request, login, {"column": None})
        login.refresh_from_db()
        assert login.assignee is None


class TestCheckedWhereItIsWritten:
    @pytest.mark.parametrize(
        "board, message",
        [
            (Board("Bad name", field="priority"), "lower case"),
            (Board("x", field="nope"), "not a field"),
            (Board("x", field="title"), "needs choices"),
            (Board("x", field="priority", editable=True), "editable_fields"),
            (Board("x", field="status", editable=True), "state field"),
            (Board("x", field="priority", fields="team"), "tuples"),
        ],
    )
    def test_a_declaration_it_cannot_follow(self, board, message):
        class Tickets(ModelResource):
            transitions = ("status",)

        with pytest.raises(ImproperlyConfigured, match=message):
            bind_board(board, Tickets(Ticket, site))

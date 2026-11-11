"""What a caller gets wrong is answered, not crashed on.

A body that is not an object, a key that cannot be one, a date that
does not exist: each is the caller's mistake and gets a 4xx - or
simply matches nothing - where it used to raise through to a 500.
"""

from __future__ import annotations

import json

import pytest
from rest_framework.exceptions import ValidationError

from example.models import Ticket
from generic.api.body import clean_keys
from generic.api.columns import FilterSpec
from generic.api.filters import date_engine, multiselect_engine
from generic.wiki import archive

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/"
BOOKS = "/api/books/"
TOGGLE = "/api/generic/watches/toggle/"

#: Bodies that parse as JSON and are not an object.
NOT_OBJECTS = ([1, 2], "text", 3, [{"ids": [1]}])


def post(client, url, body, method="post"):
    return getattr(client, method)(
        url, json.dumps(body), content_type="application/json"
    )


class TestABodyThatIsNotAnObject:
    @pytest.mark.parametrize("body", NOT_OBJECTS)
    @pytest.mark.parametrize(
        "path",
        ["", "actions/", "bulk-edit/", "undo/", "outline/move/", "rows/"],
    )
    def test_a_resource_refuses_it(
        self, admin_client, support_desk, path, body
    ):
        response = post(admin_client, f"{TICKETS}{path}", body)

        assert response.status_code == 400, response.content
        assert response.json() == {"detail": "Send a JSON object."}

    @pytest.mark.parametrize("body", NOT_OBJECTS)
    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_on_a_record_too(self, admin_client, support_desk, method, body):
        login = support_desk["login"]

        response = post(admin_client, f"{TICKETS}{login.pk}/", body, method)

        assert response.status_code == 400, response.content
        assert Ticket.objects.get(pk=login.pk).title == login.title

    @pytest.mark.parametrize("body", NOT_OBJECTS)
    def test_a_form_endpoint_refuses_it(self, api_client, library, body):
        response = api_client.post("/api/book-forms/", body, format="json")

        assert response.status_code == 400, response.content

    @pytest.mark.parametrize("body", NOT_OBJECTS)
    def test_the_watches_refuse_it(self, admin_client, body):
        response = post(admin_client, TOGGLE, body)

        assert response.status_code == 400, response.content

    def test_an_object_goes_through_as_before(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]

        response = post(
            admin_client, f"{TICKETS}{login.pk}/", {"title": "New"}, "patch"
        )

        assert response.status_code == 200, response.content
        assert Ticket.objects.get(pk=login.pk).title == "New"

    def test_reading_is_not_concerned(self, admin_client, support_desk):
        assert admin_client.get(TICKETS).status_code == 200


class TestAKeyThatCannotBeOne:
    @pytest.mark.parametrize("ids", ["abc", "1,abc", "1.5", "9" * 40])
    def test_the_autocomplete_labels_what_exists(
        self, admin_client, support_desk, ids
    ):
        response = admin_client.get(f"{TICKETS}autocomplete/?ids={ids}")

        assert response.status_code == 200, response.content

    def test_and_still_labels_the_good_ones(self, admin_client, support_desk):
        login = support_desk["login"]

        response = admin_client.get(
            f"{TICKETS}autocomplete/?ids={login.pk},abc"
        )

        assert [row["id"] for row in response.json()["results"]] == [login.pk]

    @pytest.mark.parametrize("page", ["9" * 30, "-4", "abc", "1e400"])
    def test_a_page_past_the_end_is_an_empty_one(
        self, admin_client, support_desk, page
    ):
        response = admin_client.get(
            f"{TICKETS}autocomplete/?q=login&page={page}"
        )

        assert response.status_code == 200, response.content

    def test_a_far_page_of_a_plain_autocomplete(self, api_client, library):
        response = api_client.get(
            f"/api/author-autocomplete/?q=a&page={'9' * 30}"
        )

        assert response.status_code == 200, response.content
        assert response.json()["results"] == []

    @pytest.mark.parametrize(
        "ids", [["abc"], [None], [[1]], [{"a": 1}], [1.5, "x"], [True]]
    )
    def test_a_bulk_action_on_them_selects_nothing(
        self, admin_client, support_desk, ids
    ):
        before = Ticket.objects.count()

        response = post(
            admin_client,
            f"{TICKETS}actions/",
            {"action": "delete_selected", "ids": ids},
        )

        assert response.status_code < 500, response.content
        assert Ticket.objects.count() == before

    @pytest.mark.parametrize("ids", [["abc"], [None, [1]]])
    def test_nor_a_bulk_edit(self, admin_client, support_desk, ids):
        response = post(
            admin_client,
            f"{TICKETS}bulk-edit/",
            {"ids": ids, "changes": {"priority": "low"}, "commit": True},
        )

        assert response.status_code < 500, response.content

    @pytest.mark.parametrize("object_id", ["abc", "1.5", "9" * 40])
    def test_a_watch_on_one_finds_nothing(
        self, admin_client, support_desk, object_id
    ):
        response = post(
            admin_client,
            TOGGLE,
            {"model": "example.ticket", "objectId": object_id},
        )

        assert response.status_code == 404, response.content

    def test_clean_keys_keeps_what_can_be_a_key(self):
        values = ["3", 4, "abc", None, [5], {"a": 1}, True, 1.5, "1.5"]

        assert clean_keys(Ticket, [*values, 2.0, "9" * 40]) == [3, 4, 2]


class TestADateThatDoesNotExist:
    date = FilterSpec(field="published_on", type="date", value_type="date")
    moment = FilterSpec(
        field="released_at", type="date", value_type="datetime"
    )

    @pytest.mark.parametrize(
        "value", ["2024-02-30", "2023-13-01", "0000-01-01", "2024-00-10"]
    )
    def test_it_is_refused(self, value):
        with pytest.raises(ValidationError):
            date_engine("published_on", self.date, "exact", value)

    @pytest.mark.parametrize("value", ["0001-01-01", "9999-12-31"])
    @pytest.mark.parametrize(
        "operator", ["exact", "before", "after", "on_or_before"]
    )
    def test_the_edge_of_the_calendar_is_refused(self, operator, value):
        """No midnight in every time zone: it used to overflow."""
        for spec in (self.date, self.moment):
            with pytest.raises(ValidationError):
                date_engine("released_at", spec, operator, value)

    def test_through_the_endpoint(self, api_client, library):
        for value in ("2024-02-30", "0001-01-01"):
            response = api_client.get(
                BOOKS,
                {
                    "draw": 1,
                    "advanced_filters": json.dumps(
                        {
                            "released_at": {
                                "operator": "before",
                                "value": value,
                            }
                        }
                    ),
                },
            )

            assert response.status_code == 400, (value, response.content)


class TestAChoiceThatIsNoNumber:
    spec = FilterSpec(
        field="author_id", type="multiselect", value_type="integer"
    )

    @pytest.mark.parametrize(
        "value", [float("inf"), float("nan"), "abc", None, [1]]
    )
    def test_it_is_refused(self, value):
        with pytest.raises(ValidationError):
            multiselect_engine("author", self.spec, "include", [value])


class TestAPositionOutOfRange:
    def test_an_archive_cannot_carry_one(self):
        assert archive._number(10**30) == archive.MAX_POSITION
        assert archive._number(7) == 7
        assert archive._number(-1) == 0
        assert archive._number("7") == 0

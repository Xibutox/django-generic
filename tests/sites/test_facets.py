"""Facets on a resource: relations, tags, permissions, _related."""

from __future__ import annotations

import json

import pytest

from example.models import Tag
from generic.sites.related import RELATED_PARAM
from tests.sites.test_resource_api import user_with

pytestmark = pytest.mark.django_db

FACETS = "/api/example/ticket/facets/"


def facet(client, column, **params):
    response = client.get(FACETS, {"column": column, **params})

    assert response.status_code == 200, response.content

    return response.json()


def counts(body) -> dict:
    return {entry["label"]: entry["count"] for entry in body["values"]}


class TestRelations:
    def test_a_foreign_key_is_counted_by_record(
        self, admin_client, support_desk
    ):
        body = facet(admin_client, "team")

        assert counts(body) == {"Front office": 2, "Infrastructure": 1}
        assert body["values"][0]["value"] == support_desk["front"].pk

    def test_a_search_looks_into_the_related_label(
        self, admin_client, support_desk
    ):
        body = facet(admin_client, "team", q="infra")

        assert counts(body) == {"Infrastructure": 1}

    def test_a_many_to_many_counts_rows_once_per_value(
        self, admin_client, support_desk
    ):
        body = facet(admin_client, "tags")

        assert counts(body) == {
            "regression": 1,
            "release": 1,
            "billing": 1,
            "Empty": 1,
        }

    def test_tags_come_with_their_colours(self, admin_client, support_desk):
        Tag.objects.filter(pk=support_desk["billing"].pk).update(
            background="#fde68a", color="#78350f"
        )
        body = facet(admin_client, "tags", q="bill")

        assert body["values"][0]["tag"] == {
            "label": "billing",
            "id": support_desk["billing"].pk,
            "color": "#78350f",
            "background": "#fde68a",
        }

    def test_a_choice_drawn_as_a_tag(self, admin_client, support_desk):
        body = facet(admin_client, "status")

        assert body["values"][0]["tag"]["color"]


class TestScope:
    def test_the_search_and_filters_apply(self, admin_client, support_desk):
        tree = {
            "match": "all",
            "conditions": [
                {
                    "column": "status",
                    "operator": "none_of",
                    "value": ["closed"],
                }
            ],
        }
        body = facet(
            admin_client,
            "team",
            filters=json.dumps(tree),
            **{"search[value]": "invoice"},
        )

        # SD-2 only: SD-3 matches the search but is closed.
        assert counts(body) == {"Infrastructure": 1}

    def test_a_related_table_counts_the_records_rows(
        self, admin_client, support_desk
    ):
        front = support_desk["front"]
        body = facet(
            admin_client,
            "priority",
            **{RELATED_PARAM: f"example.team.tickets:{front.pk}"},
        )

        assert sum(entry["count"] for entry in body["values"]) == 2

    def test_facets_need_the_view_permission(self, client, support_desk):
        client.force_login(user_with("view_team"))

        response = client.get(FACETS, {"column": "team"})

        assert response.status_code == 403


class TestGeneratedColumns:
    def test_the_list_keeps_its_filters_in_the_address(
        self, admin_client, support_desk
    ):
        options = admin_client.get("/example/ticket/").context["table_config"][
            "options"
        ]

        assert options["syncUrl"] is True

    def test_a_related_table_leaves_the_address_alone(
        self, admin_client, support_desk
    ):
        front = support_desk["front"]
        response = admin_client.get(f"/example/team/{front.pk}/")
        tickets = next(
            table
            for table in response.context["related_tables"]
            if table["name"] == "tickets"
        )

        assert tickets["config"]["options"]["syncUrl"] is False

    def test_a_many_valued_column_says_so(self, admin_client, support_desk):
        config = admin_client.get("/example/ticket/").context["table_config"]
        columns = {column["data"]: column for column in config["columns"]}

        assert columns["tags"]["filterMany"] is True
        assert "filterMany" not in columns["team"]

    def test_a_short_repeating_text_offers_its_values(self, admin_client, db):
        config = admin_client.get("/example/customer/").context["table_config"]
        columns = {column["data"]: column for column in config["columns"]}

        assert columns["city"]["facets"] is True
        # Unique: every value once, no use as a list.
        assert "facets" not in columns["code"]

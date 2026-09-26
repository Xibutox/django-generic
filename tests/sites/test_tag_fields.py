"""Fields a resource draws as coloured tags: table, filters, summary."""

from __future__ import annotations

import json

import pytest

from example.models import Tag
from tests.sites.test_resource_api import references, user_with

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/"
TAGS = "/api/example/tag/"


def columns_of(client, url: str = "/example/ticket/") -> dict:
    config = client.get(url).context["table_config"]

    return {column["data"]: column for column in config["columns"]}


class TestColumns:
    def test_a_many_to_many_keeps_its_autocomplete_filter(
        self,
        admin_client,
        support_desk,
    ):
        tags = columns_of(admin_client)["tags"]

        assert tags["type"] == "tags"
        assert tags["filterType"] == "multiselect"
        assert tags["autocompleteUrl"] == "/api/example/tag/autocomplete/"
        assert tags["tagUrl"] == "/example/tag/{id}/"

    def test_a_choice_keeps_its_choices(self, admin_client, support_desk):
        status = columns_of(admin_client)["status"]

        assert status["type"] == "tags"
        assert status["filterType"] == "multiselect"
        assert [choice["value"] for choice in status["choices"]] == [
            "open",
            "pending",
            "resolved",
            "closed",
        ]
        # A choice is no record: nothing to link to.
        assert "tagUrl" not in status

    def test_no_link_to_tags_the_user_may_not_open(
        self,
        client,
        support_desk,
    ):
        client.force_login(user_with("view_ticket"))

        assert "tagUrl" not in columns_of(client)["tags"]


class TestRows:
    def test_colours_come_from_the_records(self, admin_client, support_desk):
        Tag.objects.filter(pk=support_desk["billing"].pk).update(
            color="#78350f",
            background="#fde68a",
        )
        response = admin_client.get(
            TICKETS,
            {"draw": 1, "search[value]": "SD-2"},
        )

        assert response.json()["data"][0]["tags"] == [
            {
                "label": "billing",
                "id": support_desk["billing"].pk,
                "color": "#78350f",
                "background": "#fde68a",
            }
        ]

    def test_a_choice_is_drawn_with_its_label_and_colour(
        self,
        admin_client,
        support_desk,
    ):
        response = admin_client.get(
            TICKETS,
            {"draw": 1, "search[value]": "SD-1"},
        )
        row = response.json()["data"][0]

        # The value rides along, for a grid that edits the choice.
        assert row["status"] == [
            {"label": "Open", "color": "#2563eb", "value": "open"}
        ]
        assert row["priority"] == [
            {"label": "High", "color": "#ea580c", "value": "high"}
        ]

    def test_a_fixed_background_comes_with_its_text(
        self,
        admin_client,
        support_desk,
    ):
        from example.models import Ticket

        Ticket.objects.filter(reference="SD-1").update(priority="urgent")
        response = admin_client.get(
            TICKETS,
            {"draw": 1, "search[value]": "SD-1"},
        )

        assert response.json()["data"][0]["priority"] == [
            {
                "label": "Urgent",
                "color": "#ffffff",
                "background": "#dc2626",
                "value": "urgent",
            }
        ]

    def test_filtering_on_a_tag_still_works(self, admin_client, support_desk):
        response = admin_client.get(
            TICKETS,
            {
                "draw": 1,
                "advanced_filters": json.dumps(
                    {
                        "tags": {
                            "operator": "include",
                            "value": [support_desk["billing"].pk],
                        }
                    }
                ),
            },
        )

        assert references(response) == ["SD-2"]

    def test_filtering_on_a_choice_still_works(
        self,
        admin_client,
        support_desk,
    ):
        response = admin_client.get(
            TICKETS,
            {
                "draw": 1,
                "advanced_filters": json.dumps(
                    {"status": {"operator": "exclude", "value": ["open"]}}
                ),
            },
        )

        assert references(response) == ["SD-2", "SD-3"]

    def test_a_method_can_return_tags(self, admin_client, support_desk):
        Tag.objects.filter(pk=support_desk["regression"].pk).update(
            color="#dc2626"
        )
        response = admin_client.get(TAGS, {"draw": 1, "length": 10})
        rows = {row["name"]: row for row in response.json()["data"]}

        assert rows["regression"]["preview"] == [
            {
                "label": "regression",
                "id": support_desk["regression"].pk,
                "color": "#dc2626",
            }
        ]


class TestSummary:
    def test_a_figure_can_be_a_tag(self, admin_client, support_desk):
        billing = support_desk["billing"]
        body = admin_client.get(f"{TAGS}{billing.pk}/summary/").json()
        preview = next(
            stat for stat in body["stats"] if stat["name"] == "preview"
        )

        assert preview["type"] == "tags"
        assert preview["items"][0]["label"] == "billing"
        assert preview["items"][0]["url"] == f"/example/tag/{billing.pk}/"

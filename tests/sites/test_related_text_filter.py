"""A relation filtered by words: every record whose name holds them."""

from __future__ import annotations

import json

import pytest
from rest_framework.exceptions import ValidationError

from generic.api.columns import FilterSpec
from generic.api.filters import multiselect_engine
from generic.sites import site

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/"


def references(client, *conditions) -> list[str]:
    tree = {"match": "all", "conditions": list(conditions)}
    response = client.get(TICKETS, {"filters": json.dumps(tree)})

    assert response.status_code == 200, response.content

    return sorted(row["reference"] for row in response.json()["data"])


def condition(column, operator, value):
    return {"column": column, "operator": operator, "value": value}


class TestForeignKey:
    def test_contains_matches_the_related_name(
        self, admin_client, support_desk
    ):
        found = references(admin_client, condition("team", "contains", "fro"))

        assert found == ["SD-1", "SD-3"]

    def test_several_words_match_any_of_them(self, admin_client, support_desk):
        found = references(
            admin_client,
            condition("team", "contains", ["front", "infra"]),
        )

        assert found == ["SD-1", "SD-2", "SD-3"]

    def test_does_not_contain(self, admin_client, support_desk):
        found = references(
            admin_client, condition("team", "not_contains", "front")
        )

        assert found == ["SD-2"]

    def test_picked_values_still_work(self, admin_client, support_desk):
        found = references(
            admin_client,
            condition("team", "any_of", [support_desk["infra"].pk]),
        )

        assert found == ["SD-2"]


class TestManyToMany:
    def test_contains_lists_a_row_once(self, admin_client, support_desk):
        # SD-1 holds both "regression" and "release".
        found = references(admin_client, condition("tags", "contains", "re"))

        assert found == ["SD-1"]

    def test_does_not_contain_means_none_of_them(
        self, admin_client, support_desk
    ):
        found = references(
            admin_client, condition("tags", "not_contains", "release")
        )

        assert found == ["SD-2", "SD-3"]


class TestDeclaration:
    def test_a_relation_column_offers_words(self, admin_client, db):
        config = admin_client.get("/example/ticket/").context["table_config"]
        columns = {column["data"]: column for column in config["columns"]}

        assert columns["team"]["textSearch"] is True
        assert columns["tags"]["textSearch"] is True
        assert "textSearch" not in columns["status"]

    def test_the_spec_names_the_related_text(self):
        from example.models import Ticket

        serializer = site.get_resource(Ticket).get_table_serializer_class()
        specs = serializer.get_filter_specs()

        assert specs["team"].field == "team"
        assert specs["team"].text_field == "team__name"
        assert specs["status"].text_field is None


class TestEngine:
    def test_without_a_text_field_words_are_refused(self):
        spec = FilterSpec(field="status", type="multiselect")

        with pytest.raises(ValidationError):
            multiselect_engine("status", spec, "contains", "open")

    def test_with_one_the_text_engine_answers(self):
        spec = FilterSpec(
            field="team", type="multiselect", text_field="team__name"
        )

        predicate, negate = multiselect_engine(
            "team", spec, "not_contains", "front"
        )

        assert negate is True
        assert "team__name" in str(predicate)

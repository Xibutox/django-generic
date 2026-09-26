"""Filter trees: conditions grouped with all / any, the richer operators,
and facets - the values of a column with their counts."""

from __future__ import annotations

import datetime
import json

import pytest
from freezegun import freeze_time

from generic.api.columns import FilterSpec
from generic.api.filters import relative_period
from tests.factories import BookFactory

pytestmark = pytest.mark.django_db

BOOKS_URL = "/api/books/"


def titles(client, tree=None, **params) -> list[str]:
    if tree is not None:
        params["filters"] = json.dumps(tree)

    response = client.get(BOOKS_URL, params)

    assert response.status_code == 200, response.data

    return sorted(row["title"] for row in response.data["data"])


def refused(client, tree) -> dict:
    response = client.get(BOOKS_URL, {"filters": json.dumps(tree)})

    assert response.status_code == 400, response.data

    return response.data


def all_of(*conditions):
    return {"match": "all", "conditions": list(conditions)}


def any_of(*conditions):
    return {"match": "any", "conditions": list(conditions)}


def cond(column, operator, value=None):
    condition = {"column": column, "operator": operator}

    if value is not None:
        condition["value"] = value

    return condition


class TestGroups:
    def test_all_requires_every_condition(self, api_client, library):
        tree = all_of(
            cond("author", "contains", "Austen"),
            cond("is_available", "is_true"),
        )

        assert titles(api_client, tree) == ["Emma"]

    def test_any_requires_one(self, api_client, library):
        tree = any_of(
            cond("genre", "any_of", ["essay"]),
            cond("pages", "lt", 300),
        )

        assert titles(api_client, tree) == ["Essays", "Persuasion"]

    def test_groups_nest(self, api_client, library):
        tree = all_of(
            cond("is_available", "is_true"),
            any_of(cond("pages", "gt", 1000), cond("title", "equals", "Emma")),
        )

        assert titles(api_client, tree) == ["Emma", "Essays"]

    def test_several_conditions_on_one_column(self, api_client, library):
        tree = all_of(cond("pages", "gt", 250), cond("pages", "lt", 1000))

        assert titles(api_client, tree) == ["Emma"]

    def test_an_empty_tree_filters_nothing(self, api_client, library):
        assert len(titles(api_client, all_of())) == 3

    def test_a_condition_without_its_value_is_ignored(
        self, api_client, library
    ):
        assert len(titles(api_client, all_of(cond("title", "contains")))) == 3

    def test_the_older_payload_still_combines(self, api_client, library):
        result = titles(
            api_client,
            all_of(cond("pages", "lt", 1000)),
            advanced_filters=json.dumps(
                {"author": {"operator": "contains", "value": "Austen"}}
            ),
        )

        assert result == ["Emma", "Persuasion"]


class TestOperators:
    def test_text_any_of_several_values(self, api_client, library):
        tree = all_of(cond("title", "contains", ["emm", "ssay"]))

        assert titles(api_client, tree) == ["Emma", "Essays"]

    def test_text_none_of_several_values(self, api_client, library):
        tree = all_of(cond("title", "not_contains", ["emm", "ssay"]))

        assert titles(api_client, tree) == ["Persuasion"]

    def test_starts_and_ends(self, api_client, library):
        assert titles(
            api_client, all_of(cond("title", "starts_with", "Pe"))
        ) == ["Persuasion"]
        assert titles(
            api_client, all_of(cond("title", "ends_with", "ys"))
        ) == ["Essays"]

    def test_empty_and_not_empty(self, api_client, library):
        assert titles(api_client, all_of(cond("rating", "empty"))) == [
            "Essays"
        ]
        assert titles(
            api_client, all_of(cond("published_on", "not_empty"))
        ) == [
            "Emma",
            "Persuasion",
        ]

    def test_number_between(self, api_client, library):
        tree = all_of(cond("price", "between", [10, 20]))

        assert titles(api_client, tree) == ["Emma"]

    def test_number_between_with_one_bound(self, api_client, library):
        tree = all_of(cond("pages", "between", {"from": 400}))

        assert titles(api_client, tree) == ["Emma", "Essays"]

    def test_boolean_is_false(self, api_client, library):
        assert titles(
            api_client, all_of(cond("is_available", "is_false"))
        ) == ["Persuasion"]

    def test_choice_none_of(self, api_client, library):
        tree = all_of(cond("genre", "none_of", ["fiction"]))

        assert titles(api_client, tree) == ["Essays"]

    def test_date_before_is_strict(self, api_client, library):
        tree = all_of(cond("published_on", "before", "1815-12-23"))

        assert titles(api_client, tree) == []

    def test_date_on_or_after(self, api_client, library):
        tree = all_of(cond("published_on", "on_or_after", "1815-12-23"))

        assert titles(api_client, tree) == ["Emma", "Persuasion"]

    @freeze_time("2020-03-20 12:00:00")
    def test_last_days_on_a_datetime(self, api_client, library):
        tree = all_of(cond("released_at", "last_days", 7))

        assert titles(api_client, tree) == ["Emma"]

    @freeze_time("2020-03-20 12:00:00")
    def test_this_month(self, api_client, library):
        tree = all_of(cond("released_at", "this_month"))

        assert titles(api_client, tree) == ["Emma"]

    @freeze_time("2021-06-20 12:00:00")
    def test_older_than_days(self, api_client, library):
        tree = all_of(cond("released_at", "older_than_days", 30))

        assert titles(api_client, tree) == ["Emma"]


class TestRefusals:
    def test_an_undeclared_column(self, api_client, library):
        errors = refused(
            api_client, all_of(cond("publisher__name", "contains", "G"))
        )

        assert "not allowed" in str(errors).lower()

    def test_an_unknown_match(self, api_client, library):
        refused(api_client, {"match": "some", "conditions": []})

    def test_nesting_too_deep(self, api_client, library):
        tree = all_of(cond("title", "contains", "E"))

        for _level in range(6):
            tree = all_of(tree)

        refused(api_client, tree)

    def test_too_many_conditions(self, api_client, library):
        refused(api_client, all_of(*[cond("pages", "gt", 1)] * 51))

    def test_a_bad_number_of_days(self, api_client, library):
        refused(api_client, all_of(cond("released_at", "last_days", -3)))

    def test_an_inverted_range(self, api_client, library):
        refused(api_client, all_of(cond("pages", "between", [500, 100])))

    def test_a_list_instead_of_an_object(self, api_client, library):
        response = api_client.get(BOOKS_URL, {"filters": "[]"})

        assert response.status_code == 400


class TestRelativePeriods:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("today", ("2026-09-15", "2026-09-15")),
            ("yesterday", ("2026-09-14", "2026-09-14")),
            ("this_week", ("2026-09-14", "2026-09-20")),
            ("last_week", ("2026-09-07", "2026-09-13")),
            ("this_month", ("2026-09-01", "2026-09-30")),
            ("last_month", ("2026-08-01", "2026-08-31")),
            ("next_month", ("2026-10-01", "2026-10-31")),
            ("this_quarter", ("2026-07-01", "2026-09-30")),
            ("last_quarter", ("2026-04-01", "2026-06-30")),
            ("last_year", ("2025-01-01", "2025-12-31")),
        ],
    )
    def test_boundaries(self, name, expected):
        start, end = relative_period(name, datetime.date(2026, 9, 15))

        assert (start.isoformat(), end.isoformat()) == expected

    def test_a_quarter_across_a_year(self):
        start, end = relative_period("last_quarter", datetime.date(2026, 2, 3))

        assert (start, end) == (
            datetime.date(2025, 10, 1),
            datetime.date(2025, 12, 31),
        )


class TestFacets:
    def facets(self, client, column, tree=None, **params):
        params["column"] = column

        if tree is not None:
            params["filters"] = json.dumps(tree)

        response = client.get(f"{BOOKS_URL}facets/", params)

        assert response.status_code == 200, response.data

        return response.data

    def test_choices_come_with_labels_and_counts(self, api_client, library):
        body = self.facets(api_client, "genre")

        assert body["kind"] == "values"
        assert body["values"] == [
            {"value": "fiction", "label": "Fiction", "count": 2},
            {"value": "essay", "label": "Essay", "count": 1},
        ]

    def test_counts_follow_the_other_filters(self, api_client, library):
        body = self.facets(
            api_client,
            "genre",
            all_of(
                cond("is_available", "is_true"),
                # Its own condition is left out: the counts say what
                # choosing another genre would give.
                cond("genre", "any_of", ["essay"]),
            ),
        )

        assert {
            entry["value"]: entry["count"] for entry in body["values"]
        } == {
            "fiction": 1,
            "essay": 1,
        }

    def test_a_boolean(self, api_client, library):
        body = self.facets(api_client, "is_available")

        assert {
            entry["label"]: entry["count"] for entry in body["values"]
        } == {
            "Yes": 2,
            "No": 1,
        }

    def test_a_range(self, api_client, library):
        body = self.facets(api_client, "pages")

        assert body == {
            "kind": "range",
            "min": 249,
            "max": 1369,
            "empty": 0,
            "column": "pages",
        }

    def test_a_date_range_counts_the_empty_ones(self, api_client, library):
        body = self.facets(api_client, "published_on")

        assert (body["min"], body["max"], body["empty"]) == (
            "1815-12-23",
            "1817-12-20",
            1,
        )

    def test_a_search_among_the_labels(self, api_client, library):
        body = self.facets(api_client, "genre", q="ess")

        assert [entry["value"] for entry in body["values"]] == ["essay"]

    def test_labels_of_known_values(self, api_client, library):
        body = self.facets(api_client, "genre", ids="essay")

        assert body["values"] == [
            {"value": "essay", "label": "Essay", "count": 1}
        ]

    def test_more_says_the_list_was_cut(self, api_client, library, settings):
        from tests.testapp.viewsets import BookTableViewSet

        for index in range(3):
            BookFactory(title=f"Extra {index}", genre="poetry")

        limit = BookTableViewSet.facet_limit
        BookTableViewSet.facet_limit = 2

        try:
            body = self.facets(api_client, "genre")
        finally:
            BookTableViewSet.facet_limit = limit

        assert len(body["values"]) == 2
        assert body["more"] is True

    def test_free_text_has_no_facets(self, api_client, library):
        response = api_client.get(f"{BOOKS_URL}facets/", {"column": "title"})

        assert response.status_code == 400

    def test_an_unknown_column_has_no_facets(self, api_client, library):
        response = api_client.get(
            f"{BOOKS_URL}facets/", {"column": "publisher__name"}
        )

        assert response.status_code == 400

    def test_the_column_declares_its_facets(self, api_client, library):
        from tests.testapp.serializers import BookTableSerializer

        columns = {
            column["data"]: column
            for column in BookTableSerializer.get_datatable_columns()
        }

        assert columns["genre"]["facets"] is True
        assert "facets" not in columns["title"]
        # Not filterable: no facets either.
        assert "facets" not in columns["slug"]


def test_a_spec_is_still_a_plain_dataclass():
    assert FilterSpec(field="x", type="text").as_dict()["many"] is False

"""Filtering, searching and ordering.

These cover both halves: that a legitimate filter narrows the queryset
the way the client meant, and that anything outside the declaration is
refused rather than quietly passed to the ORM.
"""

from __future__ import annotations

import json

import pytest
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from generic.api.columns import FilterSpec
from generic.api.filters import (
    boolean_engine,
    date_engine,
    multiselect_engine,
    numeric_engine,
    text_engine,
)

pytestmark = pytest.mark.django_db

BOOKS_URL = "/api/books/"


def fetch(client, **params):
    """Call the table endpoint and return the row titles."""
    filters = params.pop("filters", None)

    if filters is not None:
        params["advanced_filters"] = json.dumps(filters)

    response = client.get(BOOKS_URL, params)

    assert response.status_code == 200, response.data

    return [row["title"] for row in response.data["data"]]


def expect_error(client, **params):
    filters = params.pop("filters", None)

    if filters is not None:
        params["advanced_filters"] = json.dumps(filters)

    response = client.get(BOOKS_URL, params)

    assert response.status_code == 400, response.data

    return response.data


# ---------------------------------------------------------------------
# Engines, in isolation
# ---------------------------------------------------------------------


class TestTextEngine:
    spec = FilterSpec(field="title", type="text")

    def test_contains(self):
        condition, negate = text_engine("title", self.spec, "contains", "em")

        # Through generic.search, which the suite installs: accents are
        # set aside as well as case.
        assert condition == Q(title__unaccented__icontains="em")
        assert negate is False

    def test_not_contains_is_an_exclusion(self):
        _, negate = text_engine("title", self.spec, "not_contains", "em")

        assert negate is True

    def test_unknown_operator_is_refused(self):
        with pytest.raises(ValidationError):
            text_engine("title", self.spec, "regex", ".*")


class TestNumericEngine:
    spec = FilterSpec(field="pages", type="integer", value_type="integer")

    def test_comparison(self):
        condition, negate = numeric_engine(
            "pages", self.spec, "greater_or_equal", "300"
        )

        assert condition == Q(pages__gte=300)
        assert negate is False

    def test_non_numeric_value_is_refused(self):
        with pytest.raises(ValidationError):
            numeric_engine("pages", self.spec, "exact", "many")

    def test_fractional_value_on_an_integer_column_is_refused(self):
        with pytest.raises(ValidationError):
            numeric_engine("pages", self.spec, "exact", "3.5")

    def test_fractional_value_is_fine_on_a_float_column(self):
        spec = FilterSpec(field="rating", type="float", value_type="float")

        condition, _ = numeric_engine("rating", spec, "exact", "3.5")

        assert condition is not None


class TestBooleanEngine:
    spec = FilterSpec(
        field="is_available",
        type="boolean",
        value_type="boolean",
    )

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("true", True),
            ("1", True),
            ("false", False),
            ("0", False),
            (True, True),
            (False, False),
        ],
    )
    def test_accepted_representations(self, raw, expected):
        condition, _ = boolean_engine("is_available", self.spec, "exact", raw)

        assert condition == Q(is_available=expected)

    def test_garbage_is_refused(self):
        with pytest.raises(ValidationError):
            boolean_engine("is_available", self.spec, "exact", "maybe")


class TestDateEngine:
    date_spec = FilterSpec(
        field="published_on",
        type="date",
        value_type="date",
    )
    datetime_spec = FilterSpec(
        field="released_at",
        type="date",
        value_type="datetime",
    )

    def test_a_date_column_compares_directly(self):
        condition, _ = date_engine(
            "published_on", self.date_spec, "exact", "1815-12-23"
        )

        # No ``__date`` lookup: that only exists on a datetime column.
        assert "published_on__date" not in str(condition)

    def test_a_datetime_column_uses_the_date_lookup(self):
        condition, _ = date_engine(
            "released_at", self.datetime_spec, "exact", "2020-03-15"
        )

        assert "released_at__date" in str(condition)

    def test_malformed_date_is_refused(self):
        with pytest.raises(ValidationError):
            date_engine("published_on", self.date_spec, "exact", "23/12/1815")

    def test_between_requires_both_bounds(self):
        with pytest.raises(ValidationError):
            date_engine(
                "published_on",
                self.date_spec,
                "between",
                {"from": "1800-01-01"},
            )

    def test_inverted_range_is_refused(self):
        with pytest.raises(ValidationError):
            date_engine(
                "published_on",
                self.date_spec,
                "between",
                {"from": "1900-01-01", "to": "1800-01-01"},
            )


class TestMultiselectEngine:
    spec = FilterSpec(field="genre", type="multiselect")

    def test_include(self):
        condition, negate = multiselect_engine(
            "genre", self.spec, "include", ["essay", "poetry"]
        )

        assert condition == Q(genre__in=["essay", "poetry"])
        assert negate is False

    def test_exclude_is_an_exclusion(self):
        _, negate = multiselect_engine(
            "genre", self.spec, "exclude", ["essay"]
        )

        assert negate is True

    def test_duplicates_are_collapsed(self):
        condition, _ = multiselect_engine(
            "genre", self.spec, "include", ["essay", "essay"]
        )

        assert condition == Q(genre__in=["essay"])

    def test_integer_value_type_coerces(self):
        spec = FilterSpec(
            field="author_id",
            type="multiselect",
            value_type="integer",
        )

        condition, _ = multiselect_engine(
            "author", spec, "include", ["1", "2"]
        )

        assert condition == Q(author_id__in=[1, 2])

    def test_a_non_list_value_is_refused(self):
        with pytest.raises(ValidationError):
            multiselect_engine("genre", self.spec, "include", "essay")


# ---------------------------------------------------------------------
# Through the endpoint
# ---------------------------------------------------------------------


class TestAdvancedFiltering:
    def test_text_contains(self, api_client, library):
        titles = fetch(
            api_client,
            filters={"title": {"operator": "contains", "value": "ss"}},
        )

        assert titles == ["Essays"]

    def test_text_filter_on_a_related_column(self, api_client, library):
        titles = fetch(
            api_client,
            filters={"author": {"operator": "exact", "value": "Jane Austen"}},
        )

        assert sorted(titles) == ["Emma", "Persuasion"]

    def test_numeric_comparison(self, api_client, library):
        titles = fetch(
            api_client,
            filters={
                "pages": {
                    "operator": "greater_or_equal",
                    "value": "474",
                }
            },
        )

        assert sorted(titles) == ["Emma", "Essays"]

    def test_boolean_filter(self, api_client, library):
        titles = fetch(
            api_client,
            filters={"is_available": {"operator": "exact", "value": "false"}},
        )

        assert titles == ["Persuasion"]

    def test_date_filter_on_a_date_column(self, api_client, library):
        titles = fetch(
            api_client,
            filters={
                "published_on": {
                    "operator": "less_than",
                    "value": "1816-01-01",
                }
            },
        )

        assert titles == ["Emma"]

    def test_date_filter_on_a_datetime_column(self, api_client, library):
        titles = fetch(
            api_client,
            filters={
                "released_at": {
                    "operator": "exact",
                    "value": "2020-03-15",
                }
            },
        )

        assert titles == ["Emma"]

    def test_date_range(self, api_client, library):
        titles = fetch(
            api_client,
            filters={
                "released_at": {
                    "operator": "between",
                    "value": {
                        "from": "2020-01-01",
                        "to": "2020-12-31",
                    },
                }
            },
        )

        assert titles == ["Emma"]

    def test_multiselect(self, api_client, library):
        titles = fetch(
            api_client,
            filters={"genre": {"operator": "include", "value": ["essay"]}},
        )

        assert titles == ["Essays"]

    def test_filters_combine(self, api_client, library):
        titles = fetch(
            api_client,
            filters={
                "author": {
                    "operator": "contains",
                    "value": "Austen",
                },
                "is_available": {
                    "operator": "exact",
                    "value": "true",
                },
            },
        )

        assert titles == ["Emma"]

    def test_an_empty_value_does_not_filter(self, api_client, library):
        titles = fetch(
            api_client,
            filters={"title": {"operator": "contains", "value": ""}},
        )

        assert len(titles) == 3


class TestFilteringIsWhitelisted:
    def test_an_undeclared_column_is_refused(self, api_client, library):
        errors = expect_error(
            api_client,
            filters={
                "publisher__name": {
                    "operator": "contains",
                    "value": "Gallimard",
                }
            },
        )

        assert "not allowed" in str(errors).lower()

    def test_a_non_filterable_column_is_refused(
        self,
        api_client,
        library,
    ):
        errors = expect_error(
            api_client,
            filters={"slug": {"operator": "contains", "value": "emma"}},
        )

        assert "not allowed" in str(errors).lower()

    def test_an_orm_lookup_cannot_be_injected(
        self,
        api_client,
        library,
    ):
        """A column name carrying a lookup suffix is not a column."""
        expect_error(
            api_client,
            filters={
                "title__icontains": {
                    "operator": "contains",
                    "value": "a",
                }
            },
        )

    def test_malformed_json_is_refused(self, api_client, library):
        response = api_client.get(
            BOOKS_URL,
            {"advanced_filters": "{not json"},
        )

        assert response.status_code == 400

    def test_a_json_array_is_refused(self, api_client, library):
        response = api_client.get(
            BOOKS_URL,
            {"advanced_filters": "[]"},
        )

        assert response.status_code == 400


class TestGlobalSearch:
    def test_search_spans_every_searchable_column(
        self,
        api_client,
        library,
    ):
        titles = fetch(api_client, **{"search[value]": "Orwell"})

        assert titles == ["Essays"]

    def test_search_matches_the_row_title(self, api_client, library):
        titles = fetch(api_client, **{"search[value]": "persu"})

        assert titles == ["Persuasion"]

    def test_a_blank_search_returns_everything(
        self,
        api_client,
        library,
    ):
        assert len(fetch(api_client, **{"search[value]": "   "})) == 3


class TestOrdering:
    def test_datatables_ordering(self, api_client, library):
        titles = fetch(
            api_client,
            **{
                "columns[0][data]": "pages",
                "order[0][column]": "0",
                "order[0][dir]": "desc",
            },
        )

        assert titles == ["Essays", "Emma", "Persuasion"]

    def test_ordering_resolves_the_related_path(
        self,
        api_client,
        library,
    ):
        titles = fetch(
            api_client,
            **{
                "columns[0][data]": "author",
                "order[0][column]": "0",
                "order[0][dir]": "asc",
            },
        )

        # George Orwell sorts before Jane Austen by author name.
        assert titles[0] == "Essays"

    def test_a_non_orderable_column_is_ignored(
        self,
        api_client,
        library,
    ):
        titles = fetch(
            api_client,
            **{
                "columns[0][data]": "slug",
                "order[0][column]": "0",
                "order[0][dir]": "desc",
            },
        )

        # Falls back to the queryset's own ordering rather than
        # ordering on something the serializer did not allow.
        assert titles == ["Emma", "Essays", "Persuasion"]

    def test_plain_ordering_parameter(self, api_client, library):
        titles = fetch(api_client, ordering="-title")

        assert titles == ["Persuasion", "Essays", "Emma"]

    def test_plain_ordering_rejects_an_unknown_column(
        self,
        api_client,
        library,
    ):
        response = api_client.get(BOOKS_URL, {"ordering": "publisher_id"})

        assert response.status_code == 400

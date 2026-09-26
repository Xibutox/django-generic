"""The list endpoint: envelope, pagination, rendering and permissions."""

from __future__ import annotations

import json

import pytest
from django.test import override_settings

from tests.factories import BookFactory

pytestmark = pytest.mark.django_db

BOOKS_URL = "/api/books/"


class TestResponseEnvelope:
    def test_the_datatables_envelope_is_returned(
        self,
        api_client,
        library,
    ):
        response = api_client.get(BOOKS_URL, {"draw": "7"})

        assert response.status_code == 200
        assert set(response.data) == {
            "draw",
            "recordsTotal",
            "recordsFiltered",
            "data",
        }
        assert response.data["draw"] == 7
        assert response.data["recordsTotal"] == 3
        assert response.data["recordsFiltered"] == 3

    def test_draw_is_coerced_to_an_integer(self, api_client, library):
        """DataTables requires the counter to be cast, not echoed."""
        response = api_client.get(
            BOOKS_URL,
            {"draw": "<script>alert(1)</script>"},
        )

        assert response.data["draw"] == 0

    def test_records_total_ignores_the_filters(
        self,
        api_client,
        library,
    ):
        response = api_client.get(
            BOOKS_URL,
            {
                "advanced_filters": json.dumps(
                    {
                        "genre": {
                            "operator": "include",
                            "value": ["essay"],
                        }
                    }
                )
            },
        )

        assert response.data["recordsTotal"] == 3
        assert response.data["recordsFiltered"] == 1
        assert len(response.data["data"]) == 1

    def test_the_total_count_can_be_switched_off(
        self,
        api_client,
        library,
    ):
        response = api_client.get(
            "/api/books-no-total/",
            {
                "advanced_filters": json.dumps(
                    {
                        "genre": {
                            "operator": "include",
                            "value": ["essay"],
                        }
                    }
                )
            },
        )

        # Without the extra COUNT the two numbers coincide.
        assert response.data["recordsTotal"] == 1
        assert response.data["recordsFiltered"] == 1


class TestPagination:
    @pytest.fixture
    def many_books(self, db):
        return [BookFactory() for _ in range(25)]

    def test_default_page_size_comes_from_the_settings(
        self,
        api_client,
        many_books,
    ):
        response = api_client.get(BOOKS_URL)

        # tests.settings sets TABLE_PAGE_SIZE to 10.
        assert len(response.data["data"]) == 10

    def test_length_controls_the_page_size(
        self,
        api_client,
        many_books,
    ):
        response = api_client.get(BOOKS_URL, {"length": "5"})

        assert len(response.data["data"]) == 5

    def test_start_offsets_the_page(self, api_client, many_books):
        first = api_client.get(BOOKS_URL, {"length": "5"})
        second = api_client.get(
            BOOKS_URL,
            {"length": "5", "start": "5"},
        )

        first_titles = {row["title"] for row in first.data["data"]}
        second_titles = {row["title"] for row in second.data["data"]}

        assert not first_titles & second_titles

    def test_length_is_clamped_to_the_maximum(
        self,
        api_client,
        many_books,
    ):
        with override_settings(GENERIC={"TABLE_MAX_PAGE_SIZE": 3}):
            response = api_client.get(BOOKS_URL, {"length": "1000"})

        assert len(response.data["data"]) == 3

    def test_unlimited_length_is_refused_by_default(
        self,
        api_client,
        many_books,
    ):
        response = api_client.get(BOOKS_URL, {"length": "-1"})

        # Falls back to the default page size rather than dumping the
        # whole table.
        assert len(response.data["data"]) == 10

    def test_unlimited_length_can_be_allowed(
        self,
        api_client,
        many_books,
    ):
        with override_settings(
            GENERIC={
                "TABLE_ALLOW_UNLIMITED_PAGE_SIZE": True,
                "TABLE_MAX_PAGE_SIZE": 500,
            }
        ):
            response = api_client.get(BOOKS_URL, {"length": "-1"})

        assert len(response.data["data"]) == 25

    def test_a_garbage_length_falls_back_to_the_default(
        self,
        api_client,
        many_books,
    ):
        response = api_client.get(BOOKS_URL, {"length": "lots"})

        assert len(response.data["data"]) == 10

    def test_a_negative_start_is_clamped(self, api_client, many_books):
        response = api_client.get(BOOKS_URL, {"start": "-40"})

        assert len(response.data["data"]) == 10


class TestRendering:
    def test_the_datatables_format_is_accepted(
        self,
        api_client,
        library,
    ):
        response = api_client.get(BOOKS_URL, {"format": "datatables"})

        assert response.status_code == 200

    def test_an_error_is_rendered_as_datatables_expects(
        self,
        api_client,
        library,
    ):
        response = api_client.get(
            BOOKS_URL,
            {
                "format": "datatables",
                "advanced_filters": json.dumps(
                    {"nope": {"operator": "contains", "value": "x"}}
                ),
            },
        )

        assert response.status_code == 400

        payload = json.loads(response.content)

        # Without the ``error`` key DataTables shows an empty table and
        # says nothing.
        assert payload["error"]
        assert payload["data"] == []
        assert payload["recordsTotal"] == 0

    def test_plain_json_keeps_the_drf_error_shape(
        self,
        api_client,
        library,
    ):
        response = api_client.get(
            BOOKS_URL,
            {
                "advanced_filters": json.dumps(
                    {"nope": {"operator": "contains", "value": "x"}}
                )
            },
        )

        assert response.status_code == 400
        assert "advanced_filters" in response.data


class TestSerialization:
    def test_rows_carry_every_declared_column(
        self,
        api_client,
        library,
    ):
        response = api_client.get(BOOKS_URL, {"ordering": "title"})
        row = response.data["data"][0]

        assert row["title"] == "Emma"
        assert row["author"] == "Jane Austen"
        assert row["slug"] == "emma"

    def test_null_values_survive(self, api_client, library):
        response = api_client.get(BOOKS_URL, {"ordering": "title"})
        rows = {row["title"]: row for row in response.data["data"]}

        assert rows["Essays"]["rating"] is None
        assert rows["Essays"]["published_on"] is None


class TestPermissions:
    def test_the_default_endpoint_requires_authentication(
        self,
        api_client,
        library,
    ):
        response = api_client.get("/api/books-protected/")

        assert response.status_code in {401, 403}

    def test_an_authenticated_user_gets_the_rows(
        self,
        authenticated_client,
        library,
    ):
        response = authenticated_client.get("/api/books-protected/")

        assert response.status_code == 200
        assert response.data["recordsTotal"] == 3


class TestAggregatedTable:
    URL = "/api/authors-summary/"

    def test_rows_are_grouped_and_aggregated(
        self,
        api_client,
        library,
    ):
        response = api_client.get(self.URL)

        assert response.status_code == 200

        rows = {row["author"]: row for row in response.data["data"]}

        assert rows["Jane Austen"]["book_count"] == 2
        assert rows["Jane Austen"]["total_pages"] == 474 + 249
        assert rows["George Orwell"]["book_count"] == 1

    def test_base_exclusions_hide_rows(self, api_client, library):
        response = api_client.get(self.URL)

        authors = {row["author"] for row in response.data["data"]}

        assert "Inactive Author" not in authors

    def test_filter_parameters_are_applied(self, api_client, library):
        response = api_client.get(self.URL, {"name": "orwell"})

        assert [row["author"] for row in response.data["data"]] == [
            "George Orwell"
        ]

    def test_advanced_filters_work_on_aggregates(
        self,
        api_client,
        library,
    ):
        response = api_client.get(
            self.URL,
            {
                "advanced_filters": json.dumps(
                    {
                        "book_count": {
                            "operator": "greater_than",
                            "value": "1",
                        }
                    }
                )
            },
        )

        assert [row["author"] for row in response.data["data"]] == [
            "Jane Austen"
        ]

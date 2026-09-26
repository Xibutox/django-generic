"""Select2 autocomplete endpoint."""

from __future__ import annotations

import pytest
from django.test import override_settings

from tests.factories import AuthorFactory

pytestmark = pytest.mark.django_db

URL = "/api/author-autocomplete/"


class TestResults:
    def test_the_select2_shape_is_returned(self, api_client, library):
        response = api_client.get(URL)

        assert response.status_code == 200
        assert set(response.data) == {"results", "pagination"}
        assert set(response.data["results"][0]) == {"id", "text"}

    def test_the_label_field_drives_the_text(self, api_client, library):
        response = api_client.get(URL, {"q": "Orwell"})

        assert [item["text"] for item in response.data["results"]] == [
            "George Orwell"
        ]

    def test_search_spans_every_declared_field(
        self,
        api_client,
        library,
    ):
        response = api_client.get(URL, {"q": "jane@test"})

        assert [item["text"] for item in response.data["results"]] == [
            "Jane Austen"
        ]

    def test_a_blank_term_returns_everything(
        self,
        api_client,
        library,
    ):
        response = api_client.get(URL, {"q": "  "})

        assert len(response.data["results"]) == 3

    def test_no_match_returns_an_empty_list(self, api_client, library):
        response = api_client.get(URL, {"q": "zzz"})

        assert response.data["results"] == []
        assert response.data["pagination"]["more"] is False


class TestPagination:
    @pytest.fixture
    def many_authors(self, db):
        return [AuthorFactory() for _ in range(30)]

    def test_the_first_page_reports_more(
        self,
        api_client,
        many_authors,
    ):
        response = api_client.get(URL)

        # AUTOCOMPLETE_PAGE_SIZE defaults to 25.
        assert len(response.data["results"]) == 25
        assert response.data["pagination"]["more"] is True

    def test_the_last_page_reports_no_more(
        self,
        api_client,
        many_authors,
    ):
        response = api_client.get(URL, {"page": "2"})

        assert len(response.data["results"]) == 5
        assert response.data["pagination"]["more"] is False

    def test_pages_do_not_overlap(self, api_client, many_authors):
        first = api_client.get(URL, {"page": "1"}).data["results"]
        second = api_client.get(URL, {"page": "2"}).data["results"]

        assert not {item["id"] for item in first} & {
            item["id"] for item in second
        }

    def test_a_garbage_page_falls_back_to_the_first(
        self,
        api_client,
        many_authors,
    ):
        response = api_client.get(URL, {"page": "later"})

        assert len(response.data["results"]) == 25


class TestMinimumInputLength:
    def test_a_short_term_returns_nothing(self, api_client, library):
        with override_settings(GENERIC={"AUTOCOMPLETE_MIN_INPUT_LENGTH": 3}):
            response = api_client.get(URL, {"q": "Ja"})

        assert response.data["results"] == []

    def test_a_long_enough_term_searches(self, api_client, library):
        with override_settings(GENERIC={"AUTOCOMPLETE_MIN_INPUT_LENGTH": 3}):
            response = api_client.get(URL, {"q": "Jane"})

        assert len(response.data["results"]) == 1

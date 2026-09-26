"""The listing view: columns, search, ordering, paging, bulk actions."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from tests.factories import BookFactory
from tests.testapp.models import Book

pytestmark = pytest.mark.django_db

URL = "/books/"


def titles(response) -> list[str]:
    return [row.instance.title for row in response.context["table"]]


class TestRendering:
    def test_the_page_renders(self, auth_client, library):
        response = auth_client.get(URL)

        assert response.status_code == 200
        assert "generic/list.html" in [
            template.name for template in response.templates if template.name
        ]

    def test_columns_come_from_list_display(self, auth_client, library):
        response = auth_client.get(URL)
        labels = [column.label for column in response.context["table"].columns]

        assert labels[:3] == ["Title", "Author", "Pages"]

    def test_a_computed_column_uses_its_short_description(
        self,
        auth_client,
        library,
    ):
        response = auth_client.get(URL)
        labels = [column.label for column in response.context["table"].columns]

        assert "Published year" in labels

    def test_a_computed_column_renders_its_value(
        self,
        auth_client,
        library,
    ):
        response = auth_client.get(URL, {"q": "Emma"})
        row = response.context["table"].rows[0]
        values = {cell["column"].name: str(cell["value"]) for cell in row}

        assert values["age"] == "1815"

    def test_booleans_render_as_words_not_true_false(
        self,
        auth_client,
        library,
    ):
        response = auth_client.get(URL, {"q": "Emma"})
        row = response.context["table"].rows[0]
        values = {cell["column"].name: str(cell["value"]) for cell in row}

        assert "Yes" in values["is_available"]

    def test_the_first_column_links_to_the_detail_page(
        self,
        auth_client,
        library,
    ):
        response = auth_client.get(URL, {"q": "Emma"})
        row = response.context["table"].rows[0]

        assert row.url == f"/books/{library['emma'].pk}/"
        assert row.cells[0]["is_link"] is True

    def test_a_listing_without_list_display_falls_back_to_str(
        self,
        auth_client,
        library,
    ):
        response = auth_client.get("/authors/")
        table = response.context["table"]

        assert len(table.columns) == 1
        assert "Jane Austen" in {str(row.cells[0]["value"]) for row in table}

    def test_an_empty_listing_renders(self, auth_client, db):
        response = auth_client.get(URL)

        assert response.status_code == 200
        assert response.context["table"].is_empty


class TestSearch:
    def test_search_narrows_the_rows(self, auth_client, library):
        assert titles(auth_client.get(URL, {"q": "Emma"})) == ["Emma"]

    def test_search_spans_every_declared_field(self, auth_client, library):
        assert titles(auth_client.get(URL, {"q": "Orwell"})) == ["Essays"]

    def test_a_blank_search_returns_everything(self, auth_client, library):
        assert len(titles(auth_client.get(URL, {"q": "   "}))) == 3


class TestOrdering:
    def test_ordering_by_a_column(self, auth_client, library):
        assert titles(auth_client.get(URL, {"o": "pages"})) == [
            "Persuasion",
            "Emma",
            "Essays",
        ]

    def test_descending_ordering(self, auth_client, library):
        assert titles(auth_client.get(URL, {"o": "-pages"}))[0] == "Essays"

    def test_an_unknown_column_is_ignored(self, auth_client, library):
        """A stale bookmark should still render the page."""
        response = auth_client.get(URL, {"o": "password"})

        assert response.status_code == 200
        assert titles(response) == ["Emma", "Essays", "Persuasion"]

    def test_a_computed_column_is_not_sortable(self, auth_client, library):
        columns = {
            column.name: column
            for column in auth_client.get(URL).context["table"].columns
        }

        assert columns["age"].is_sortable is False
        assert columns["title"].is_sortable is True

    def test_the_ordering_state_reaches_the_template(
        self,
        auth_client,
        library,
    ):
        response = auth_client.get(URL, {"o": "-pages"})

        assert response.context["ordering_state"] == {"pages": "desc"}


class TestPagination:
    def test_the_page_size_is_honoured(self, auth_client, db):
        for _index in range(12):
            BookFactory()

        response = auth_client.get(URL)

        assert len(response.context["table"].rows) == 5
        assert response.context["is_paginated"] is True

    def test_the_second_page_holds_different_rows(self, auth_client, db):
        for _index in range(12):
            BookFactory()

        first = titles(auth_client.get(URL))
        second = titles(auth_client.get(URL, {"page": "2"}))

        assert not set(first) & set(second)

    def test_the_total_count_ignores_pagination(self, auth_client, db):
        for _index in range(12):
            BookFactory()

        assert auth_client.get(URL).context["total_count"] == 12


class TestBulkActions:
    def test_an_action_runs_on_the_selected_rows(
        self,
        auth_client,
        library,
    ):
        emma = library["emma"]

        response = auth_client.post(
            URL,
            {
                "action": "mark_unavailable",
                "selected": [str(emma.pk)],
                "select_across": "0",
            },
        )

        assert response.status_code == 302

        emma.refresh_from_db()
        assert emma.is_available is False

        # The rows that were not selected are untouched.
        library["essays"].refresh_from_db()
        assert library["essays"].is_available is True

    def test_select_across_covers_the_filtered_rows(
        self,
        auth_client,
        library,
    ):
        auth_client.post(
            f"{URL}?q=Emma",
            {
                "action": "mark_unavailable",
                "select_across": "1",
            },
        )

        library["emma"].refresh_from_db()
        library["essays"].refresh_from_db()

        # "Select all" means everything the filter matches, never the
        # whole table.
        assert library["emma"].is_available is False
        assert library["essays"].is_available is True

    def test_an_unknown_action_changes_nothing(self, auth_client, library):
        response = auth_client.post(
            URL,
            {
                "action": "drop_everything",
                "selected": [str(library["emma"].pk)],
            },
        )

        assert response.status_code == 302
        assert Book.objects.count() == 3

    def test_an_empty_selection_changes_nothing(self, auth_client, library):
        auth_client.post(URL, {"action": "mark_unavailable", "selected": []})

        library["emma"].refresh_from_db()
        assert library["emma"].is_available is True


class TestPermissions:
    URL = "/books/protected/"

    def test_an_anonymous_visitor_is_redirected(self, client, library):
        response = client.get(self.URL)

        assert response.status_code == 302

    def test_a_user_without_the_permission_is_refused(
        self,
        client,
        user,
        library,
    ):
        client.force_login(user)

        assert client.get(self.URL).status_code == 403

    def test_the_model_permission_is_enough(
        self,
        client,
        user,
        library,
    ):
        user.user_permissions.add(Permission.objects.get(codename="view_book"))
        client.force_login(user)

        assert client.get(self.URL).status_code == 200

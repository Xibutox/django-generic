"""The create and update views."""

from __future__ import annotations

import pytest

from tests.testapp.models import Book

pytestmark = pytest.mark.django_db

CREATE_URL = "/books/add/"


def book_data(author, **overrides) -> dict:
    data = {
        "title": "New Book",
        "author": str(author.pk),
        "genre": "fiction",
        "pages": "120",
        "price": "9.99",
    }
    data.update(overrides)

    return data


class TestCreate:
    def test_the_form_renders(self, auth_client, library):
        response = auth_client.get(CREATE_URL)

        assert response.status_code == 200
        assert "fieldset_form" in response.context

    def test_a_valid_submission_creates_the_object(
        self,
        auth_client,
        library,
    ):
        response = auth_client.post(
            CREATE_URL,
            book_data(library["austen"]),
        )

        assert response.status_code == 302
        assert Book.objects.filter(title="New Book").exists()

    def test_it_redirects_to_the_detail_page(
        self,
        auth_client,
        library,
    ):
        response = auth_client.post(
            CREATE_URL,
            book_data(library["austen"]),
        )
        book = Book.objects.get(title="New Book")

        assert response["Location"] == f"/books/{book.pk}/"

    def test_save_and_continue_returns_to_the_form(
        self,
        auth_client,
        library,
    ):
        response = auth_client.post(
            CREATE_URL,
            {**book_data(library["austen"]), "_continue": "1"},
        )

        assert response["Location"] == CREATE_URL

    def test_save_and_add_another_returns_to_a_blank_form(
        self,
        auth_client,
        library,
    ):
        response = auth_client.post(
            CREATE_URL,
            {**book_data(library["austen"]), "_addanother": "1"},
        )

        assert response["Location"] == CREATE_URL

    def test_an_invalid_submission_redisplays_the_form(
        self,
        auth_client,
        library,
    ):
        response = auth_client.post(
            CREATE_URL,
            book_data(library["austen"], title=""),
        )

        assert response.status_code == 200
        assert not Book.objects.filter(pages=120).exists()

    def test_the_query_string_seeds_the_form(
        self,
        auth_client,
        library,
    ):
        """Lets a link pre-fill "add a book by *this* author"."""
        response = auth_client.get(
            CREATE_URL,
            {"author": str(library["austen"].pk)},
        )
        form = response.context["form"]

        assert form.initial["author"] == str(library["austen"].pk)

    def test_an_unknown_query_parameter_is_ignored(
        self,
        auth_client,
        library,
    ):
        response = auth_client.get(CREATE_URL, {"is_superuser": "1"})

        assert "is_superuser" not in response.context["form"].initial

    def test_a_success_message_is_shown(self, auth_client, library):
        response = auth_client.post(
            CREATE_URL,
            book_data(library["austen"]),
            follow=True,
        )
        messages = [str(item) for item in response.context["messages"]]

        assert any("added successfully" in text for text in messages)


class TestUpdate:
    @pytest.fixture
    def url(self, library) -> str:
        return f"/books/{library['emma'].pk}/change/"

    def test_the_form_is_bound_to_the_object(
        self,
        auth_client,
        url,
    ):
        response = auth_client.get(url)

        assert response.context["form"].instance.title == "Emma"

    def test_a_valid_submission_updates_the_object(
        self,
        auth_client,
        url,
        library,
    ):
        response = auth_client.post(
            url,
            book_data(library["austen"], title="Emma, revised"),
        )

        assert response.status_code == 302

        library["emma"].refresh_from_db()
        assert library["emma"].title == "Emma, revised"

    def test_the_subtitle_is_the_object(self, auth_client, url):
        response = auth_client.get(url)

        assert response.context["page_subtitle"] == "Emma"

    def test_the_delete_link_is_offered(self, auth_client, url, library):
        response = auth_client.get(url)

        assert response.context["delete_url"] == (
            f"/books/{library['emma'].pk}/delete/"
        )


class TestFieldsets:
    @pytest.fixture
    def url(self, library) -> str:
        return f"/books/{library['emma'].pk}/fieldsets/"

    def test_fields_are_grouped_as_declared(self, auth_client, url):
        response = auth_client.get(url)
        fieldsets = list(response.context["fieldset_form"])

        assert [fieldset.title for fieldset in fieldsets] == [
            None,
            "Commercial",
            "Meta",
        ]

    def test_a_tuple_puts_fields_on_one_row(self, auth_client, url):
        response = auth_client.get(url)
        first = list(response.context["fieldset_form"])[0]
        rows = list(first)

        assert len(rows[0].fields) == 1
        assert len(rows[1].fields) == 2
        assert rows[1].is_multiline is True

    def test_a_description_reaches_the_template(self, auth_client, url):
        response = auth_client.get(url)
        commercial = list(response.context["fieldset_form"])[1]

        assert commercial.description == "Pricing and classification."

    def test_collapse_is_advertised_to_the_client(
        self,
        auth_client,
        url,
    ):
        response = auth_client.get(url)
        commercial = list(response.context["fieldset_form"])[1]

        assert commercial.is_collapsible is True

    def test_a_readonly_field_renders_as_text(self, auth_client, url):
        response = auth_client.get(url)
        meta = list(response.context["fieldset_form"])[2]
        field = list(meta)[0].fields[0]

        assert field.is_readonly is True
        assert "read-only value" in str(field.contents)

    def test_the_form_still_saves(self, auth_client, url, library):
        response = auth_client.post(
            url,
            book_data(library["austen"], title="Renamed"),
        )

        assert response.status_code == 302

        library["emma"].refresh_from_db()
        assert library["emma"].title == "Renamed"

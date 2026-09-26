"""Tabular inlines: nothing is written unless everything validates."""

from __future__ import annotations

import pytest

from tests.factories import AuthorFactory, BookFactory, ChapterFactory
from tests.testapp.models import Book, Chapter

pytestmark = pytest.mark.django_db

URL = "/api/book-forms/"


@pytest.fixture
def author(db):
    return AuthorFactory(name="Jane Austen")


def book_payload(author, **overrides) -> dict:
    payload = {
        "title": "Emma",
        "author": author.pk,
        "genre": "fiction",
        "pages": 474,
        "price": "12.50",
        "is_available": True,
    }
    payload.update(overrides)

    return payload


class TestSchema:
    def test_inlines_are_described_in_the_schema(self, api_client, db):
        response = api_client.get(f"{URL}form-schema/")
        inlines = response.data["inlines"]

        assert len(inlines) == 1
        assert inlines[0]["name"] == "chapters"
        assert inlines[0]["presentation"] == "tabular"
        assert inlines[0]["maxRows"] == 5

    def test_the_parent_link_is_not_an_editable_column(
        self,
        api_client,
        db,
    ):
        response = api_client.get(f"{URL}form-schema/")
        names = {
            field["name"] for field in response.data["inlines"][0]["fields"]
        }

        # ``book`` is supplied by the viewset on save.
        assert "book" not in names
        assert {"title", "position"} <= names


class TestCreate:
    def test_a_parent_and_its_rows_are_created_together(
        self,
        api_client,
        author,
    ):
        response = api_client.post(
            URL,
            {
                **book_payload(author),
                "_inlines": {
                    "chapters": [
                        {"title": "Volume I", "position": 1},
                        {"title": "Volume II", "position": 2},
                    ]
                },
            },
            format="json",
        )

        assert response.status_code == 201, response.data

        book = Book.objects.get(pk=response.data["id"])

        assert book.chapters.count() == 2
        assert [
            row["title"] for row in response.data["_inlines"]["chapters"]
        ] == ["Volume I", "Volume II"]

    def test_a_parent_can_be_created_without_rows(
        self,
        api_client,
        author,
    ):
        response = api_client.post(
            URL,
            book_payload(author),
            format="json",
        )

        assert response.status_code == 201
        assert response.data["_inlines"]["chapters"] == []

    def test_an_invalid_row_rolls_the_parent_back(
        self,
        api_client,
        author,
    ):
        response = api_client.post(
            URL,
            {
                **book_payload(author),
                "_inlines": {
                    "chapters": [
                        {"title": "Fine", "position": 1},
                        {"title": "", "position": 2},
                    ]
                },
            },
            format="json",
        )

        assert response.status_code == 400
        # The parent must not survive a rejected row.
        assert not Book.objects.filter(title="Emma").exists()
        assert not Chapter.objects.exists()

    def test_a_row_carrying_an_id_on_create_is_refused(
        self,
        api_client,
        author,
    ):
        existing = ChapterFactory()

        response = api_client.post(
            URL,
            {
                **book_payload(author),
                "_inlines": {
                    "chapters": [{"id": existing.pk, "title": "Stolen"}]
                },
            },
            format="json",
        )

        assert response.status_code == 400

        existing.refresh_from_db()
        assert existing.title != "Stolen"


class TestUpdate:
    @pytest.fixture
    def book(self, author):
        book = BookFactory(title="Emma", author=author)
        ChapterFactory(book=book, title="Volume I", position=1)
        ChapterFactory(book=book, title="Volume II", position=2)

        return book

    def test_rows_can_be_edited_added_and_removed_at_once(
        self,
        api_client,
        book,
    ):
        first, second = book.chapters.order_by("position")

        response = api_client.patch(
            f"{URL}{book.pk}/",
            {
                "_inlines": {
                    "chapters": [
                        {"id": first.pk, "title": "Volume One"},
                        {"id": second.pk, "_delete": True},
                        {"title": "Volume III", "position": 3},
                    ]
                }
            },
            format="json",
        )

        assert response.status_code == 200, response.data

        titles = list(
            book.chapters.order_by("position").values_list(
                "title",
                flat=True,
            )
        )

        assert titles == ["Volume One", "Volume III"]

    def test_rows_left_out_of_the_payload_are_untouched(
        self,
        api_client,
        book,
    ):
        response = api_client.patch(
            f"{URL}{book.pk}/",
            {"title": "Emma, revised"},
            format="json",
        )

        assert response.status_code == 200
        assert book.chapters.count() == 2

    def test_a_row_belonging_to_another_parent_is_refused(
        self,
        api_client,
        book,
    ):
        """The row id is looked up among this parent's rows only."""
        foreign = ChapterFactory(title="Someone else's")

        response = api_client.patch(
            f"{URL}{book.pk}/",
            {
                "_inlines": {
                    "chapters": [{"id": foreign.pk, "title": "Hijacked"}]
                }
            },
            format="json",
        )

        assert response.status_code == 400

        foreign.refresh_from_db()
        assert foreign.title == "Someone else's"

    def test_an_invalid_row_rolls_back_the_parent_change(
        self,
        api_client,
        book,
    ):
        first = book.chapters.first()

        response = api_client.patch(
            f"{URL}{book.pk}/",
            {
                "title": "Should not stick",
                "_inlines": {"chapters": [{"id": first.pk, "title": ""}]},
            },
            format="json",
        )

        assert response.status_code == 400

        book.refresh_from_db()
        assert book.title == "Emma"

    def test_deletions_run_before_creations(self, api_client, book):
        """Frees a unique slot so the same request can reuse it."""
        first, second = book.chapters.order_by("position")

        response = api_client.patch(
            f"{URL}{book.pk}/",
            {
                "_inlines": {
                    "chapters": [
                        {"id": first.pk, "_delete": True},
                        {"title": "Replacement", "position": 1},
                    ]
                }
            },
            format="json",
        )

        assert response.status_code == 200, response.data
        assert book.chapters.filter(
            title="Replacement",
            position=1,
        ).exists()

    def test_deleting_an_unsaved_row_is_a_no_op(
        self,
        api_client,
        book,
    ):
        response = api_client.patch(
            f"{URL}{book.pk}/",
            {"_inlines": {"chapters": [{"_delete": True}]}},
            format="json",
        )

        assert response.status_code == 200
        assert book.chapters.count() == 2


class TestConstraints:
    @pytest.fixture
    def book(self, author):
        book = BookFactory(title="Emma", author=author)
        ChapterFactory(book=book, title="Volume I", position=1)

        return book

    def test_max_rows_is_enforced(self, api_client, author):
        response = api_client.post(
            URL,
            {
                **book_payload(author),
                "_inlines": {
                    "chapters": [
                        {"title": f"Chapter {index}", "position": index}
                        for index in range(6)
                    ]
                },
            },
            format="json",
        )

        assert response.status_code == 400
        assert "At most" in str(response.data)

    def test_min_rows_is_enforced(self, api_client, author):
        response = api_client.post(
            "/api/book-forms-required/",
            {
                **book_payload(author),
                "_inlines": {"chapters": []},
            },
            format="json",
        )

        assert response.status_code == 400
        assert "At least" in str(response.data)

    def test_deletion_can_be_forbidden(self, api_client, book):
        chapter = book.chapters.first()

        response = api_client.patch(
            f"/api/book-forms-required/{book.pk}/",
            {"_inlines": {"chapters": [{"id": chapter.pk, "_delete": True}]}},
            format="json",
        )

        assert response.status_code == 400
        assert book.chapters.count() == 1


class TestPayloadShape:
    def test_an_unknown_inline_name_is_refused(
        self,
        api_client,
        author,
    ):
        response = api_client.post(
            URL,
            {
                **book_payload(author),
                "_inlines": {"nope": []},
            },
            format="json",
        )

        assert response.status_code == 400
        assert "Unknown inline" in str(response.data)

    def test_a_non_object_inline_payload_is_refused(
        self,
        api_client,
        author,
    ):
        response = api_client.post(
            URL,
            {**book_payload(author), "_inlines": []},
            format="json",
        )

        assert response.status_code == 400

    def test_a_non_list_row_collection_is_refused(
        self,
        api_client,
        author,
    ):
        response = api_client.post(
            URL,
            {
                **book_payload(author),
                "_inlines": {"chapters": {"title": "x"}},
            },
            format="json",
        )

        assert response.status_code == 400


class TestRetrieve:
    def test_retrieve_embeds_the_rows(self, api_client, author):
        book = BookFactory(title="Emma", author=author)
        ChapterFactory(book=book, title="Volume I", position=1)

        response = api_client.get(f"{URL}{book.pk}/")

        assert response.status_code == 200
        assert [
            row["title"] for row in response.data["_inlines"]["chapters"]
        ] == ["Volume I"]


class TestDeletionPreview:
    def test_it_lists_what_would_be_removed(self, api_client, author):
        book = BookFactory(title="Emma", author=author)
        ChapterFactory(book=book, title="Volume I", position=1)

        response = api_client.get(f"{URL}{book.pk}/deletion-preview/")

        assert response.status_code == 200
        assert response.data["canDelete"] is True
        assert response.data["object"]["label"] == "Emma"
        assert "chapter" in str(response.data["nested"]).lower()

    def test_a_protected_relation_blocks_the_deletion(
        self,
        api_client,
        library,
    ):
        publisher = library["publisher"]

        response = api_client.get(
            f"/api/publishers/{publisher.pk}/deletion-preview/"
        )

        assert response.status_code == 200
        assert response.data["canDelete"] is False
        assert response.data["protected"]

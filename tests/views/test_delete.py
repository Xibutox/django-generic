"""The delete view and its cascade preview."""

from __future__ import annotations

import pytest

from generic.views import collect_deletion_summary
from tests.factories import ChapterFactory
from tests.testapp.models import Book, Chapter, Publisher

pytestmark = pytest.mark.django_db


@pytest.fixture
def url(library) -> str:
    return f"/books/{library['emma'].pk}/delete/"


class TestConfirmation:
    def test_the_page_renders(self, auth_client, url):
        response = auth_client.get(url)

        assert response.status_code == 200
        assert response.context["deletion"]["can_delete"] is True

    def test_it_lists_what_the_cascade_would_remove(
        self,
        auth_client,
        url,
    ):
        response = auth_client.get(url)
        rendered = response.content.decode()

        # Emma has two chapters, which go with it.
        assert "Volume I" in rendered
        assert "Volume II" in rendered

    def test_it_counts_the_affected_models(self, auth_client, url):
        response = auth_client.get(url)
        counts = {
            entry["label"]: entry["count"]
            for entry in response.context["deletion"]["counts"]
        }

        assert counts["chapters"] == 2

    def test_the_cancel_link_returns_to_the_object(
        self,
        auth_client,
        url,
        library,
    ):
        response = auth_client.get(url)

        assert response.context["cancel_url"] == (
            f"/books/{library['emma'].pk}/"
        )


class TestDeletion:
    def test_a_confirmed_deletion_removes_the_object(
        self,
        auth_client,
        url,
        library,
    ):
        response = auth_client.post(url)

        assert response.status_code == 302
        assert not Book.objects.filter(pk=library["emma"].pk).exists()

    def test_the_cascade_is_applied(self, auth_client, url):
        auth_client.post(url)

        assert not Chapter.objects.exists()

    def test_it_redirects_to_the_listing(self, auth_client, url):
        response = auth_client.post(url)

        assert response["Location"] == "/books/"

    def test_a_success_message_is_shown(self, auth_client, url):
        response = auth_client.post(url, follow=True)
        messages = [str(item) for item in response.context["messages"]]

        assert any("deleted successfully" in text for text in messages)


class TestProtectedRelations:
    @pytest.fixture
    def url(self, library) -> str:
        return f"/publishers/{library['publisher'].pk}/delete/"

    def test_the_page_explains_why_it_cannot_be_deleted(
        self,
        auth_client,
        url,
    ):
        response = auth_client.get(url)

        assert response.context["deletion"]["can_delete"] is False
        assert response.context["deletion"]["protected"]

    def test_the_confirm_button_is_not_offered(
        self,
        auth_client,
        url,
    ):
        response = auth_client.get(url)

        assert "Yes, delete" not in response.content.decode()

    def test_posting_anyway_is_refused(
        self,
        auth_client,
        url,
        library,
    ):
        """The page may have been open a while; check again on POST."""
        response = auth_client.post(url)

        assert response.status_code == 200
        assert Publisher.objects.filter(pk=library["publisher"].pk).exists()


class TestCollectDeletionSummary:
    def test_an_object_with_no_relations_can_be_deleted(
        self,
        library,
    ):
        summary = collect_deletion_summary(library["essays"])

        assert summary["can_delete"] is True

    def test_children_are_nested_under_their_parent(self, library):
        ChapterFactory(book=library["essays"], title="Only", position=9)

        summary = collect_deletion_summary(library["essays"])
        rendered = str(summary["nested"])

        assert "Only" in rendered

    def test_a_protected_relation_is_reported(self, library):
        summary = collect_deletion_summary(library["publisher"])

        assert summary["can_delete"] is False
        assert summary["protected"][0]["label"] == "Emma"

    def test_many_to_many_links_are_not_listed(self, support_desk):
        """ "Ticket-tag relationship: Ticket_tags object (4)" says nothing
        the ticket's own line does not - and the tag itself stays."""
        from example.models import Tag

        ticket = support_desk["login"]
        ticket.tags.add(Tag.objects.create(name="Billing"))

        summary = collect_deletion_summary(ticket)

        assert "relationship" not in str(summary["nested"]).lower()
        assert all(
            "relationship" not in count["label"].lower()
            for count in summary["counts"]
        )
        assert [item["label"] for item in summary["nested"]] == [str(ticket)]

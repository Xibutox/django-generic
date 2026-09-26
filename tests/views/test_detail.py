"""The detail view."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def url(library) -> str:
    return f"/books/{library['emma'].pk}/"


class TestRendering:
    def test_the_page_renders(self, auth_client, url):
        response = auth_client.get(url)

        assert response.status_code == 200

    def test_rows_follow_the_declared_order(self, auth_client, url):
        response = auth_client.get(url)
        names = [row["name"] for row in response.context["detail_rows"]]

        assert names == ["title", "author", "genre", "pages", "price"]

    def test_labels_come_from_the_model(self, auth_client, url):
        response = auth_client.get(url)
        labels = {
            row["name"]: row["label"]
            for row in response.context["detail_rows"]
        }

        assert labels["title"] == "Title"
        assert labels["pages"] == "Pages"

    def test_a_choice_field_shows_its_label(self, auth_client, url):
        response = auth_client.get(url)
        values = {
            row["name"]: str(row["value"])
            for row in response.context["detail_rows"]
        }

        # ``Fiction``, not ``fiction``.
        assert values["genre"] == "Fiction"

    def test_a_relation_shows_its_string(self, auth_client, url):
        response = auth_client.get(url)
        values = {
            row["name"]: str(row["value"])
            for row in response.context["detail_rows"]
        }

        assert values["author"] == "Jane Austen"

    def test_a_missing_object_is_a_404(self, auth_client, db):
        assert auth_client.get("/books/999999/").status_code == 404


class TestChrome:
    def test_the_subtitle_is_the_object(self, auth_client, url):
        response = auth_client.get(url)

        assert response.context["page_subtitle"] == "Emma"

    def test_the_breadcrumbs_lead_back_to_the_listing(
        self,
        auth_client,
        url,
    ):
        response = auth_client.get(url)
        crumbs = response.context["breadcrumbs"]

        assert crumbs[0].url == "/books/"
        assert crumbs[-1].label == "Emma"

    def test_the_toolbar_offers_change_and_delete(
        self,
        auth_client,
        url,
        user,
        library,
    ):
        from django.contrib.auth.models import Permission

        user.user_permissions.add(
            Permission.objects.get(codename="change_book"),
            Permission.objects.get(codename="delete_book"),
        )
        # Permission caching is per instance; a fresh login rebuilds it.
        auth_client.force_login(user)

        response = auth_client.get(url)
        labels = [item.label for item in response.context["toolbar_items"]]

        assert labels == ["Change", "Delete"]

    def test_toolbar_entries_the_user_may_not_use_are_hidden(
        self,
        auth_client,
        url,
    ):
        response = auth_client.get(url)

        # The plain fixture user holds no model permissions.
        assert response.context["toolbar_items"] == []

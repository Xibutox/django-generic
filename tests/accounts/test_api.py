"""The signed-in user's own state: preferences, profile, saved views."""

from __future__ import annotations

import pytest
from django.urls import reverse

from generic.accounts.models import SavedView, UserPreferences

pytestmark = pytest.mark.django_db


def patch(client, url: str, data: dict):
    return client.patch(url, data, content_type="application/json")


def post(client, url: str, data: dict):
    return client.post(url, data, content_type="application/json")


class TestPreferences:
    def test_reading_them_saves_nothing(self, auth_client, user):
        response = auth_client.get(reverse("generic:preferences"))

        assert response.status_code == 200
        assert response.json()["theme"] == "system"
        assert not UserPreferences.objects.filter(user=user).exists()

    def test_a_change_is_kept_on_the_account(self, auth_client, user):
        response = patch(
            auth_client,
            reverse("generic:preferences"),
            {"theme": "dark", "table_page_size": 25},
        )

        assert response.status_code == 200, response.json()

        preferences = UserPreferences.objects.get(user=user)
        assert preferences.theme == "dark"
        assert preferences.table_page_size == 25

    def test_an_unknown_value_is_refused(self, auth_client):
        response = patch(
            auth_client,
            reverse("generic:preferences"),
            {"theme": "purple"},
        )

        assert response.status_code == 400
        assert "theme" in response.json()

    def test_the_theme_is_applied_before_the_page_paints(
        self,
        auth_client,
        user,
    ):
        patch(auth_client, reverse("generic:preferences"), {"theme": "dark"})

        response = auth_client.get("/account/")

        assert b'data-theme-preference="dark"' in response.content

    def test_the_form_is_described_like_any_other(self, auth_client):
        schema = auth_client.get(reverse("generic:preferences-schema")).json()

        # The theme and the colours are drawn by the appearance card.
        assert schema["mode"] == "update"
        assert [field["name"] for field in schema["fields"]] == [
            "language",
            "navigation",
            "table_page_size",
            "notification_channel",
            "remember_table_state",
        ]

    def test_where_the_navigation_sits_is_kept_on_the_account(
        self,
        auth_client,
        user,
    ):
        """The pin in the bar saves through here, so another machine
        opens with the navigation where this user left it."""
        response = patch(
            auth_client,
            reverse("generic:preferences"),
            {"navigation": "floating"},
        )

        assert response.status_code == 200, response.json()
        assert UserPreferences.objects.get(user=user).navigation == "floating"

        page = auth_client.get("/account/")

        assert b'data-navigation-preference="floating"' in page.content

    def test_the_language_field_offers_the_project_s_languages(
        self,
        auth_client,
    ):
        schema = auth_client.get(reverse("generic:preferences-schema")).json()
        language = next(
            field for field in schema["fields"] if field["name"] == "language"
        )

        assert [choice["value"] for choice in language["choices"]] == [
            "en",
            "fr",
        ]

    def test_an_anonymous_user_has_none(self, client):
        response = client.get(reverse("generic:preferences"))

        assert response.status_code in (401, 403)


class TestAppearance:
    """The numbers every colour is computed from."""

    URL = "generic:preferences"

    def test_they_reach_the_page_before_it_paints(self, auth_client, user):
        """On <html>, inline: a page must not flash the wrong colours."""
        patch(
            auth_client,
            reverse(self.URL),
            {"accent_hue": 210, "contrast": 50},
        )

        rendered = auth_client.get("/account/").content.decode()

        assert "--ui-hue: 210;" in rendered
        assert "--ui-contrast: 0.5;" in rendered

    def test_a_value_outside_the_range_is_refused(self, auth_client):
        response = patch(
            auth_client,
            reverse(self.URL),
            {"contrast": 400},
        )

        assert response.status_code == 400
        assert "contrast" in response.json()

    def test_a_stored_value_is_clamped_on_the_way_out(self, user):
        """The style attribute is built from these numbers.

        Whatever a fixture, a migration or a shell put in the column,
        what reaches the page is inside the range.
        """
        preferences = UserPreferences(user=user, contrast=900)

        assert "--ui-contrast: 1;" in preferences.appearance_style()

    def test_only_what_the_user_set_travels(self, user):
        preferences = UserPreferences(user=user, tint=40)

        assert preferences.get_appearance() == {"tint": 40}
        assert preferences.appearance_style() == "--ui-tint: 0.4;"

    def test_the_colours_are_not_fields_of_the_form(self, auth_client):
        """Drawn by the appearance card, as sliders."""
        schema = auth_client.get(reverse("generic:preferences-schema")).json()
        names = [field["name"] for field in schema["fields"]]

        assert "accent_hue" not in names
        assert "contrast" not in names

    def test_the_page_has_no_size_of_its_own(self, auth_client):
        """The interface follows the browser's text size and zoom: there
        is no size preference to set, and none on the page."""
        patch(auth_client, reverse(self.URL), {"interface_scale": 125})
        rendered = auth_client.get("/account/").content.decode()

        assert "--ui-scale" not in rendered
        assert "interface_scale" not in rendered


class TestProfile:
    def test_the_user_edits_their_own_name(self, auth_client, user):
        response = patch(
            auth_client,
            reverse("generic:profile"),
            {"first_name": "Ada", "username": "someone-else"},
        )

        assert response.status_code == 200, response.json()

        user.refresh_from_db()
        assert user.first_name == "Ada"
        # The login is shown, never changed here.
        assert user.username != "someone-else"

    def test_an_external_account_keeps_the_provider_identity(
        self,
        client,
        django_user_model,
    ):
        external = django_user_model.objects.create_user(
            username="sso-user",
            password=None,
        )
        client.force_login(external)

        patch(client, reverse("generic:profile"), {"first_name": "Changed"})
        schema = client.get(reverse("generic:profile-schema")).json()

        external.refresh_from_db()
        assert external.first_name == ""
        assert all(field["readOnly"] for field in schema["fields"])


class TestSavedViews:
    TABLE = "site.example.ticket"

    def create(self, client, **fields):
        payload = {
            "table": self.TABLE,
            "name": "Mine",
            "state": {"columns": ["reference", "title"]},
            **fields,
        }

        return post(client, reverse("generic:saved-view-list"), payload)

    def test_a_view_is_listed_with_its_table(self, auth_client):
        url = reverse("generic:saved-view-list")

        assert self.create(auth_client).status_code == 201
        assert [
            view["name"]
            for view in auth_client.get(url, {"table": self.TABLE}).json()
        ] == ["Mine"]
        assert auth_client.get(url, {"table": "elsewhere"}).json() == []

    def test_a_name_is_used_once_per_table(self, auth_client):
        self.create(auth_client)

        again = self.create(auth_client)
        elsewhere = self.create(auth_client, table="site.example.team")

        assert again.status_code == 400
        assert "name" in again.json()
        assert elsewhere.status_code == 201

    def test_a_table_has_one_default_view(self, auth_client):
        first = self.create(auth_client, name="A", is_default=True).json()
        self.create(auth_client, name="B", is_default=True)

        assert list(
            SavedView.objects.filter(is_default=True).values_list(
                "name", flat=True
            )
        ) == ["B"]

        # Setting it back on the first moves it again.
        patch(
            auth_client,
            reverse("generic:saved-view-detail", args=[first["id"]]),
            {"is_default": True},
        )

        assert list(
            SavedView.objects.filter(is_default=True).values_list(
                "name", flat=True
            )
        ) == ["A"]

    def test_the_state_must_be_a_small_object(self, auth_client):
        assert self.create(auth_client, state=[1, 2]).status_code == 400
        assert (
            self.create(auth_client, state={"x": "y" * 30_000}).status_code
            == 400
        )

    def test_views_are_private(self, auth_client, staff_user):
        SavedView.objects.create(
            user=staff_user,
            table=self.TABLE,
            name="Theirs",
            state={},
        )

        assert auth_client.get(reverse("generic:saved-view-list")).json() == []

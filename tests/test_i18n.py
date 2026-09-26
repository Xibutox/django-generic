"""The interface in another language: catalogs, choice, switching."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from django.conf import global_settings
from django.urls import reverse
from django.utils import translation

from generic.accounts.models import UserPreferences
from generic.i18n import is_offered, language_menu, offered_languages

pytestmark = pytest.mark.django_db

SET_LANGUAGE = "/set-language/"


class TestCatalogs:
    """The French catalog is a deliverable: a missing .mo is silent."""

    def test_the_framework_speaks_french(self):
        with translation.override("fr"):
            assert translation.gettext("Dashboard") == "Tableau de bord"
            assert translation.gettext("Save") == "Enregistrer"

    def test_plurals_are_translated_as_plurals(self):
        with translation.override("fr"):
            one = translation.ngettext(
                "%(count)s %(name)s deleted.",
                "%(count)s %(name_plural)s deleted.",
                1,
            )
            many = translation.ngettext(
                "%(count)s %(name)s deleted.",
                "%(count)s %(name_plural)s deleted.",
                4,
            )

        assert one == "%(count)s %(name)s supprimé."
        assert many == "%(count)s %(name_plural)s supprimés."

    def test_english_falls_back_to_the_source_string(self):
        with translation.override("en"):
            assert translation.gettext("Dashboard") == "Dashboard"

    def test_the_example_speaks_french_too(self):
        with translation.override("fr"):
            assert translation.gettext("Tickets by status") == (
                "Tickets par statut"
            )

    def test_a_word_of_two_meanings_keeps_both(self):
        # "Open" is a ticket state in the example and the row action in
        # the framework; one catalog entry cannot say both, so the
        # example's labels carry a context.
        with translation.override("fr"):
            state = translation.pgettext("ticket status", "Open")
            action = translation.gettext("Open")

        assert state == "Ouvert"
        assert action == "Ouvrir"

    def test_the_browser_catalog_is_served_in_french(self, auth_client):
        response = auth_client.get(
            reverse("javascript-catalog"), headers={"accept-language": "fr"}
        )

        assert response.status_code == 200
        # The catalog is JavaScript; the strings are in it verbatim.
        assert "Enregistrer" in response.content.decode()


class TestCompiledCatalogs:
    """A .po edited without recompiling translates nothing, silently."""

    def compiler(self):
        path = (
            Path(__file__).resolve().parent.parent
            / "scripts"
            / "compile_messages.py"
        )
        spec = importlib.util.spec_from_file_location("compile_messages", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module

    def catalogs(self):
        repository = Path(__file__).resolve().parent.parent

        return sorted(
            path
            for directory in ("generic", "example")
            for path in (repository / directory / "locale").rglob("*.po")
        )

    def test_every_catalog_is_compiled_and_current(self):
        compiler = self.compiler()
        stale = [
            path.name
            for path in self.catalogs()
            if compiler.compile_catalog(path, check=True)
        ]

        assert self.catalogs(), "the framework ships no catalog"
        assert stale == []

    def test_the_compiler_keeps_a_context_with_its_message(self, tmp_path):
        catalog = tmp_path / "with-context.po"
        catalog.write_text(
            'msgid ""\nmsgstr ""\n\n'
            'msgctxt "ticket status"\nmsgid "Open"\nmsgstr "Ouvert"\n\n'
            'msgid "Open"\nmsgstr "Ouvrir"\n',
            encoding="utf-8",
        )
        entries = self.compiler().parse(catalog)

        # gettext keys a context onto the message with \x04.
        assert entries["ticket status\x04Open"] == "Ouvert"
        assert entries["Open"] == "Ouvrir"

    def test_the_compiler_refuses_what_it_cannot_read(self, tmp_path):
        broken = tmp_path / "broken.po"
        broken.write_text('msgwhat "Open"\n', encoding="utf-8")
        compiler = self.compiler()

        with pytest.raises(compiler.CatalogError, match="msgwhat"):
            compiler.parse(broken)


class TestOfferedLanguages:
    def test_the_project_narrows_what_it_offers(self):
        assert offered_languages() == [("en", "English"), ("fr", "French")]
        assert is_offered("fr") is True
        assert is_offered("de") is False

    def test_djangos_own_list_offers_no_choice(self, settings):
        # Untouched, LANGUAGES holds every language Django ships: that
        # says nothing about what this project translated.
        settings.LANGUAGES = global_settings.LANGUAGES

        assert offered_languages() == []
        assert language_menu() == []

    def test_a_single_language_is_not_a_menu(self, settings):
        settings.LANGUAGES = [("en", "English")]

        assert language_menu() == []

    def test_the_menu_ticks_the_active_language(self):
        with translation.override("fr"):
            menu = language_menu()

        assert [entry["code"] for entry in menu] == ["en", "fr"]
        assert [entry["is_current"] for entry in menu] == [False, True]

    def test_a_regional_variant_ticks_its_language(self):
        with translation.override("fr-ca"):
            menu = language_menu()

        assert menu[1]["is_current"] is True


class TestSwitching:
    def test_the_choice_is_saved_on_the_account(self, auth_client, user):
        response = auth_client.post(
            SET_LANGUAGE, {"language": "fr", "next": "/account/"}
        )

        assert response.status_code == 302
        assert response.url == "/account/"
        assert UserPreferences.objects.get(user=user).language == "fr"

    def test_the_choice_also_travels_as_a_cookie(self, auth_client, settings):
        response = auth_client.post(SET_LANGUAGE, {"language": "fr"})

        assert response.cookies[settings.LANGUAGE_COOKIE_NAME].value == "fr"

    def test_an_anonymous_visitor_may_choose_too(self, client, settings):
        response = client.post(SET_LANGUAGE, {"language": "fr"})

        assert response.status_code == 302
        assert response.cookies[settings.LANGUAGE_COOKIE_NAME].value == "fr"

    def test_a_language_the_project_does_not_offer_is_ignored(
        self,
        auth_client,
        user,
        settings,
    ):
        response = auth_client.post(SET_LANGUAGE, {"language": "de"})

        assert response.status_code == 302
        assert settings.LANGUAGE_COOKIE_NAME not in response.cookies
        assert not UserPreferences.objects.filter(user=user).exists()

    def test_it_never_redirects_off_the_site(self, auth_client):
        response = auth_client.post(
            SET_LANGUAGE,
            {"language": "fr", "next": "https://elsewhere.example/"},
        )

        assert response.url != "https://elsewhere.example/"

    def test_the_menu_is_drawn_in_the_frame(self, auth_client):
        rendered = auth_client.get("/account/").content.decode()

        assert SET_LANGUAGE in rendered
        assert "French" in rendered


class TestTheLanguageOfAPage:
    def test_a_saved_preference_wins_over_the_browser(self, auth_client, user):
        UserPreferences.objects.create(user=user, language="fr")

        response = auth_client.get(
            "/account/", headers={"accept-language": "en"}
        )

        assert response.headers["Content-Language"] == "fr"
        assert "Paramètres du compte" in response.content.decode()

    def test_without_a_preference_the_browser_decides(self, auth_client):
        response = auth_client.get(
            "/account/", headers={"accept-language": "fr"}
        )

        assert "Paramètres du compte" in response.content.decode()

    def test_english_is_served_as_written(self, auth_client):
        response = auth_client.get(
            "/account/", headers={"accept-language": "en"}
        )

        assert "Account settings" in response.content.decode()

    def test_the_language_reaches_the_html_tag(self, auth_client, user):
        UserPreferences.objects.create(user=user, language="fr")

        rendered = auth_client.get("/account/").content.decode()

        assert '<html lang="fr"' in rendered


class TestThePreference:
    def test_it_is_set_through_the_preferences_endpoint(
        self,
        auth_client,
        user,
    ):
        response = auth_client.patch(
            reverse("generic:preferences"),
            json.dumps({"language": "fr"}),
            content_type="application/json",
        )

        assert response.status_code == 200, response.json()
        assert UserPreferences.objects.get(user=user).language == "fr"

    def test_a_language_outside_the_project_is_refused(self, auth_client):
        response = auth_client.patch(
            reverse("generic:preferences"),
            json.dumps({"language": "de"}),
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "language" in response.json()

    def test_empty_means_follow_the_browser(self, auth_client, user):
        UserPreferences.objects.create(user=user, language="fr")

        auth_client.patch(
            reverse("generic:preferences"),
            json.dumps({"language": ""}),
            content_type="application/json",
        )
        response = auth_client.get(
            "/account/", headers={"accept-language": "en"}
        )

        assert UserPreferences.objects.get(user=user).language == ""
        assert "Account settings" in response.content.decode()

    def test_a_preference_no_longer_offered_is_ignored(
        self,
        auth_client,
        user,
        settings,
    ):
        UserPreferences.objects.create(user=user, language="fr")
        settings.LANGUAGES = [("en", "English")]

        response = auth_client.get(
            "/account/", headers={"accept-language": "en"}
        )

        assert "Account settings" in response.content.decode()

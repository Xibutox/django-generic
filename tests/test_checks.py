"""The system checks: what ``manage.py check`` says about how a project
plugged the framework in (generic/checks.py)."""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.test import override_settings

from generic import checks

pytestmark = pytest.mark.django_db


def ids(messages) -> list[str]:
    return [message.id for message in messages]


def without(values, removed):
    return [value for value in values if value != removed]


class TestTemplates:
    def test_the_example_way_passes(self):
        assert checks.check_templates() == []

    def test_the_request_processor_is_required(self):
        engine = {
            **settings.TEMPLATES[0],
            "OPTIONS": {
                "context_processors": without(
                    settings.TEMPLATES[0]["OPTIONS"]["context_processors"],
                    checks.REQUEST_PROCESSOR,
                )
            },
        }

        with override_settings(TEMPLATES=[engine]):
            assert ids(checks.check_templates()) == ["generic.E001"]


class TestMiddleware:
    def test_the_example_way_passes(self):
        assert checks.check_middleware() == []

    def test_a_missing_middleware_is_named(self):
        middleware = without(
            settings.MIDDLEWARE, "generic.middleware.CurrentUserMiddleware"
        )

        with override_settings(MIDDLEWARE=middleware):
            messages = checks.check_middleware()

        assert ids(messages) == ["generic.W001"]
        assert "who made them" in messages[0].msg

    def test_before_the_authentication_is_an_error(self):
        middleware = without(
            settings.MIDDLEWARE, "generic.middleware.UserLanguageMiddleware"
        )
        middleware.insert(0, "generic.middleware.UserLanguageMiddleware")

        with override_settings(MIDDLEWARE=middleware):
            assert ids(checks.check_middleware()) == ["generic.E002"]

    def test_several_languages_need_the_locale_middleware(self):
        middleware = without(settings.MIDDLEWARE, checks.LOCALE)

        with override_settings(
            MIDDLEWARE=middleware,
            LANGUAGES=[("en", "English"), ("fr", "French")],
        ):
            assert "generic.W002" in ids(checks.check_middleware())

        with override_settings(
            MIDDLEWARE=middleware, LANGUAGES=[("en", "English")]
        ):
            assert "generic.W002" not in ids(checks.check_middleware())


class TestRestFramework:
    def test_drfs_default_includes_the_session(self):
        with override_settings(REST_FRAMEWORK={}):
            assert checks.check_rest_framework() == []

    def test_a_list_without_it_is_an_error(self):
        with override_settings(
            REST_FRAMEWORK={
                "DEFAULT_AUTHENTICATION_CLASSES": [
                    "rest_framework.authentication.TokenAuthentication"
                ]
            }
        ):
            assert ids(checks.check_rest_framework()) == ["generic.E003"]


class TestMail:
    """Whether MAILERS is set is read from the settings module, which no
    override_settings can take back: the check reads it through
    ``checks.settings``, replaced here."""

    def unset(self, monkeypatch):
        monkeypatch.setattr(
            checks,
            "settings",
            SimpleNamespace(is_overridden=lambda name: name != "MAILERS"),
        )

    def test_the_suite_s_settings_pass(self):
        assert checks.check_mail() == []

    def test_without_mailers_it_is_said(self, monkeypatch):
        monkeypatch.setattr(checks, "HAS_MAILERS", True)
        self.unset(monkeypatch)

        messages = checks.check_mail()

        assert ids(messages) == ["generic.W006"]
        assert "MAILERS" in messages[0].hint

    def test_before_django_6_1_there_is_nothing_to_set(self, monkeypatch):
        monkeypatch.setattr(checks, "HAS_MAILERS", False)
        self.unset(monkeypatch)

        assert checks.check_mail() == []


class TestUrls:
    def test_the_test_urlconf_passes_but_for_login(self):
        with override_settings(LOGIN_URL="site:login"):
            assert checks.check_urls() == []

    def test_a_login_url_nobody_answers(self):
        with override_settings(LOGIN_URL="/nowhere/login/"):
            assert ids(checks.check_urls()) == ["generic.W004"]

    def test_the_site_not_mounted(self):
        with override_settings(ROOT_URLCONF="tests.checks_urls"):
            assert ids(checks.check_urls()) == ["generic.E004"]

    def test_the_rest_missing(self):
        with override_settings(
            ROOT_URLCONF="tests.checks_urls_site_only",
            LOGIN_URL="site:login",
        ):
            assert ids(checks.check_urls()) == [
                "generic.W003",
                "generic.I001",
            ]


class TestOptionalParts:
    def test_the_wiki_needs_nh3(self, monkeypatch):
        real = importlib.util.find_spec
        monkeypatch.setattr(
            checks.importlib.util,
            "find_spec",
            lambda name, *args: None if name == "nh3" else real(name, *args),
        )

        assert "generic.E005" in ids(checks.check_optional_parts())

    @pytest.mark.parametrize("module", ["docx", "docxcompose"])
    def test_the_word_merge_needs_its_libraries(self, monkeypatch, module):
        real = importlib.util.find_spec
        monkeypatch.setattr(
            checks.importlib.util,
            "find_spec",
            lambda name, *args: None if name == module else real(name, *args),
        )

        assert "generic.E009" in ids(checks.check_optional_parts())

    def test_the_word_merge_with_its_libraries_is_fine(self):
        assert "generic.E009" not in ids(checks.check_optional_parts())

    def test_a_socket_needs_asgi(self):
        with override_settings(ASGI_APPLICATION=None):
            found = ids(checks.check_optional_parts())

        assert found == (
            ["generic.W005"] if importlib.util.find_spec("channels") else []
        )

        with override_settings(
            ASGI_APPLICATION="example_project.asgi.application"
        ):
            assert "generic.W005" not in ids(checks.check_optional_parts())

    def test_not_when_the_socket_is_switched_off(self):
        with override_settings(
            ASGI_APPLICATION=None,
            GENERIC={"EVENTS_WEBSOCKET_URL": None},
        ):
            assert "generic.W005" not in ids(checks.check_optional_parts())

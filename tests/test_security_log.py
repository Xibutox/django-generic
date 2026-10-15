"""Security events: sign-ins and their failures, lockouts, passwords,
API tokens, rights granted and exports - in the log and on a screen.

The history says what changed and the access log who read what; these
are the questions asked first after an incident: who signed in from
where, who tried thirty passwords, who took the customer table away.
"""

from __future__ import annotations

import datetime
import logging

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone

from generic.audit import prune, record
from generic.audit.models import SecurityEvent
from generic.conf import generic_settings
from tests.factories import BookFactory

pytestmark = pytest.mark.django_db

LOGIN = "/login/"
LOGOUT = "/logout/"


def kinds() -> list[str]:
    return list(
        SecurityEvent.objects.order_by("at", "pk").values_list(
            "kind", flat=True
        )
    )


def last(kind: str) -> SecurityEvent:
    return SecurityEvent.objects.filter(kind=kind).latest("pk")


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user(
        username="alice",
        email="alice@example.test",
        password="a-long-enough-passphrase",
    )


@pytest.fixture
def boss(db):
    return get_user_model().objects.create_superuser(
        username="boss",
        email="boss@example.test",
        password="another-long-passphrase",
    )


def sign_in(client, password: str, username: str = "alice"):
    return client.post(
        LOGIN,
        {"username": username, "password": password},
        HTTP_USER_AGENT="Probe/1.0",
    )


class TestSigningIn:
    def test_a_sign_in_is_recorded_with_its_address(self, client, alice):
        assert sign_in(client, "a-long-enough-passphrase").status_code == 302

        event = last("signed_in")
        assert event.user == alice
        assert event.username == "alice"
        assert event.address == "127.0.0.1"
        assert event.user_agent == "Probe/1.0"

    def test_a_wrong_password_is_recorded_never_the_password(
        self, client, alice, caplog
    ):
        with caplog.at_level(logging.INFO, logger="generic.security"):
            sign_in(client, "a-wrong-guess")

        event = last("sign_in_failed")
        assert (event.user, event.username) == (alice, "alice")
        assert "a-wrong-guess" not in str(vars(event))
        # A refusal is worth a look: WARNING, with the account named.
        line = next(
            r for r in caplog.records if r.getMessage().startswith("sign_in")
        )
        assert line.levelno == logging.WARNING
        assert "account='alice'" in line.getMessage()
        assert "address=127.0.0.1" in line.getMessage()
        assert "a-wrong-guess" not in line.getMessage()

    def test_an_account_that_does_not_exist_is_named_as_typed(self, client):
        sign_in(client, "whatever", username="mallory")

        event = last("sign_in_failed")
        assert (event.user, event.username) == (None, "mallory")

    def test_the_lockout_is_recorded_once(self, client, alice, settings):
        settings.GENERIC = {**settings.GENERIC, "LOGIN_MAX_ATTEMPTS": 3}
        generic_settings._cache.clear()

        try:
            for _ in range(5):
                sign_in(client, "wrong")
        finally:
            generic_settings._cache.clear()

        locked = SecurityEvent.objects.filter(kind="locked_out")
        assert locked.count() == 1
        assert locked.get().username == "alice"
        assert "3 failed passwords" in locked.get().detail

    def test_signing_out_is_recorded(self, client, alice):
        client.force_login(alice)
        client.post(LOGOUT)

        assert kinds()[-1] == "signed_out"
        assert last("signed_out").user == alice


class TestAccounts:
    def test_changing_ones_password(self, client, alice):
        client.force_login(alice)
        response = client.post(
            "/account/password/",
            {
                "old_password": "a-long-enough-passphrase",
                "new_password1": "a-different-passphrase-9",
                "new_password2": "a-different-passphrase-9",
            },
        )

        assert response.status_code == 302
        event = last("password_changed")
        assert (event.user, event.actor_label) == (alice, "")

    def test_an_administrator_setting_it_is_named(self, client, alice, boss):
        client.force_login(boss)
        response = client.patch(
            f"/api/auth/user/{alice.pk}/",
            {"password": "a-brand-new-passphrase"},
            content_type="application/json",
        )

        assert response.status_code == 200
        event = last("password_changed")
        assert event.user == alice
        assert event.actor_label == "boss"

    def test_api_tokens_made_and_deleted(self, alice):
        from generic.tokens.models import ApiToken

        token, _key = ApiToken.objects.create(user=alice, name="CI")
        token.delete()

        assert kinds()[-2:] == ["token_created", "token_deleted"]
        assert last("token_deleted").detail == "CI"

    def test_a_right_granted_names_who_granted_it(self, alice, boss):
        from generic.grants import grant
        from generic.grants.models import AccessRequest

        asked = AccessRequest.objects.create(user=alice, kind="export")

        assert grant(asked, by=boss)
        event = last("access_granted")
        assert (event.user, event.actor_label, event.detail) == (
            alice,
            "boss",
            "export",
        )


class TestExports:
    def test_a_csv_export_says_how_many_rows_left(self, client, alice):
        for _ in range(3):
            BookFactory()
        client.force_login(alice)

        response = client.get("/api/books/export-csv/")
        b"".join(response.streaming_content)

        event = last("exported")
        assert event.user == alice
        assert "(csv): 3 rows" in event.detail

    def test_an_excel_export_too(self, client, alice):
        BookFactory()
        client.force_login(alice)

        response = client.get("/api/books/export/")
        b"".join(response.streaming_content)

        assert "(xlsx): 1 rows" in last("exported").detail


class TestTheLog:
    @override_settings(GENERIC={"SECURITY_LOG": False})
    def test_off_records_nothing(self, client, alice):
        sign_in(client, "a-long-enough-passphrase")
        sign_in(client, "wrong")

        assert not SecurityEvent.objects.exists()

    def test_a_project_records_its_own(self, rf, alice):
        request = rf.get("/")
        request.user = alice

        event = record("exported", request=request, detail="Yearly report")

        assert (event.user, event.detail) == (alice, "Yearly report")

    def test_the_screen_is_read_only_and_needs_its_permission(
        self, client, alice, boss
    ):
        record("signed_in", user=alice)
        event = SecurityEvent.objects.get()

        client.force_login(alice)
        assert client.get("/api/generic/securityevent/").status_code == 403

        alice.user_permissions.add(
            Permission.objects.get(codename="view_securityevent")
        )
        alice = get_user_model().objects.get(pk=alice.pk)
        client.force_login(alice)
        assert client.get("/api/generic/securityevent/").status_code == 200
        assert client.patch(
            f"/api/generic/securityevent/{event.pk}/",
            {"detail": "x"},
            content_type="application/json",
        ).status_code in (403, 405)

    def test_its_retention(self, alice):
        record("signed_in", user=alice)
        SecurityEvent.objects.update(
            at=timezone.now() - datetime.timedelta(days=400)
        )
        record("signed_in", user=alice)

        assert prune() == 0
        assert prune(days=365) == 1
        assert SecurityEvent.objects.count() == 1

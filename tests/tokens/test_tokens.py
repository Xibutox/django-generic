"""Personal API tokens: made once, read as their owner, refused well."""

from __future__ import annotations

import datetime

import pytest
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from generic.tokens.models import ApiToken
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

#: A refusal. DRF answers 401 when the first authentication class names
#: a scheme, 403 otherwise - the session, listed first here, names none.
REFUSED = (401, 403)

TOKENS = "/api/generic/tokens/"
TICKETS = "/api/example/ticket/"


def person(*codenames, **extra):
    user = UserFactory(**extra)
    user.user_permissions.set(
        Permission.objects.filter(codename__in=codenames)
    )

    return user


def token_for(user, **fields) -> str:
    fields.setdefault("expiry", datetime.timedelta(days=30))
    _instance, token = ApiToken.objects.create(user=user, **fields)

    return token


def script(token: str) -> APIClient:
    client = APIClient(enforce_csrf_checks=True)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    return client


class TestCallingTheApi:
    def test_a_token_reads_rows(self, support_desk):
        reader = person("view_ticket")

        response = script(token_for(reader)).get(TICKETS, {"draw": 1})

        assert response.status_code == 200
        assert response.json()["recordsTotal"] == 3

    def test_it_acts_with_its_owners_permissions_only(self, support_desk):
        stranger = person()

        response = script(token_for(stranger)).get(TICKETS, {"draw": 1})

        assert response.status_code == 403

    def test_a_read_token_cannot_write(self, support_desk):
        writer = person("view_ticket", "change_ticket")
        client = script(token_for(writer, scope="read"))
        url = f"{TICKETS}{support_desk['login'].pk}/"

        assert (
            client.patch(url, {"title": "x"}, format="json").status_code == 403
        )
        assert (
            client.post(
                f"{TICKETS}actions/",
                {"action": "delete_selected", "ids": [1]},
                format="json",
            ).status_code
            == 403
        )

    def test_a_read_write_token_writes_without_csrf(self, support_desk):
        writer = person("view_ticket", "change_ticket")
        client = script(token_for(writer, scope="read_write"))

        response = client.patch(
            f"{TICKETS}{support_desk['login'].pk}/",
            {"title": "From a script"},
            format="json",
        )

        assert response.status_code == 200, response.content
        support_desk["login"].refresh_from_db()
        assert support_desk["login"].title == "From a script"

    def test_an_expired_token_is_refused(self, support_desk):
        reader = person("view_ticket")
        _instance, token = ApiToken.objects.create(
            user=reader, expiry=datetime.timedelta(seconds=-1)
        )

        assert script(token).get(TICKETS).status_code in REFUSED

    def test_a_revoked_token_is_refused(self, support_desk):
        reader = person("view_ticket")
        token = token_for(reader)
        ApiToken.objects.filter(user=reader).delete()

        assert script(token).get(TICKETS).status_code in REFUSED

    def test_an_inactive_account_is_refused(self, support_desk):
        reader = person("view_ticket", is_active=False)

        assert script(token_for(reader)).get(TICKETS).status_code in REFUSED

    def test_a_wrong_token_is_refused(self, support_desk):
        assert script("nope" * 16).get(TICKETS).status_code in REFUSED

    def test_use_is_recorded_at_most_once_a_minute(self, support_desk):
        reader = person("view_ticket")
        token = token_for(reader)
        client = script(token)

        client.get(TICKETS)
        first = ApiToken.objects.get(user=reader).last_used_at
        client.get(TICKETS)

        assert first is not None
        assert ApiToken.objects.get(user=reader).last_used_at == first

    def test_a_session_still_needs_its_csrf_token(self, support_desk):
        writer = person("view_ticket", "change_ticket")
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(writer)

        response = client.patch(
            f"{TICKETS}{support_desk['login'].pk}/",
            {"title": "x"},
            format="json",
        )

        assert response.status_code == 403


class TestManagingTokens:
    def maker(self, client, *extra):
        user = person("add_apitoken", *extra)
        client.force_login(user)

        return user

    def test_creating_one_shows_it_once(self, client):
        user = self.maker(client)

        response = client.post(
            TOKENS,
            {"name": "Nightly report", "scope": "read", "days": 30},
            content_type="application/json",
        )

        assert response.status_code == 201, response.content
        token = response.json()["token"]
        listed = client.get(TOKENS).json()
        assert listed[0]["name"] == "Nightly report"
        assert "token" not in listed[0]
        stored = ApiToken.objects.get(user=user)
        # Only a hash is kept.
        assert token not in (stored.digest, stored.token_key)
        assert (
            stored.expiry.date()
            == (timezone.now() + datetime.timedelta(days=30)).date()
        )

    def test_the_created_token_works(self, client, support_desk):
        self.maker(client, "view_ticket")

        token = client.post(
            TOKENS, {"name": "x", "days": 30}, content_type="application/json"
        ).json()["token"]

        assert script(token).get(TICKETS).status_code == 200

    def test_without_the_permission_nothing_is_made(self, client):
        client.force_login(person())

        response = client.post(
            TOKENS, {"name": "x", "days": 30}, content_type="application/json"
        )

        assert response.status_code == 403

    def test_the_longest_life_is_capped(self, client):
        self.maker(client)

        response = client.post(
            TOKENS,
            {"name": "x", "days": 3650},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_never_expiring_needs_the_setting(self, client):
        self.maker(client)

        refused = client.post(
            TOKENS,
            {"name": "x", "days": None},
            content_type="application/json",
        )

        with override_settings(GENERIC={"API_TOKEN_MAX_DAYS": None}):
            allowed = client.post(
                TOKENS,
                {"name": "x", "days": None},
                content_type="application/json",
            )

        assert refused.status_code == 400
        assert allowed.status_code == 201

    @override_settings(GENERIC={"API_TOKEN_LIMIT_PER_USER": 1})
    def test_the_limit_per_person(self, client):
        self.maker(client)
        body = {"name": "x", "days": 30}

        client.post(TOKENS, body, content_type="application/json")
        second = client.post(TOKENS, body, content_type="application/json")

        assert second.status_code == 400

    def test_revoking_ones_own(self, client, support_desk):
        user = self.maker(client, "view_ticket")
        token = token_for(user)
        row = client.get(TOKENS).json()[0]

        assert client.delete(f"{TOKENS}{row['id']}/").status_code == 204
        assert script(token).get(TICKETS).status_code in REFUSED

    def test_nobody_revokes_anothers_through_the_account(self, client):
        other = person()
        token_for(other)
        victim = ApiToken.objects.get(user=other)
        self.maker(client)

        response = client.delete(f"{TOKENS}{victim.pk}/")

        assert response.status_code == 404
        assert ApiToken.objects.filter(pk=victim.pk).exists()

    def test_a_token_cannot_make_tokens(self):
        user = person("add_apitoken")

        response = script(token_for(user, scope="read_write")).post(
            TOKENS, {"name": "x", "days": 30}, format="json"
        )

        assert response.status_code in (401, 403)


class TestTheScreens:
    def test_the_account_page_offers_them(self, client):
        client.force_login(person("add_apitoken"))

        response = client.get("/account/")

        assert response.context["api_tokens"]["canCreate"] is True

    def test_an_administrator_revokes_anyones(self, client, support_desk):
        owner = person("view_ticket")
        token = token_for(owner)
        row = ApiToken.objects.get(user=owner)
        client.force_login(person("view_apitoken", "delete_apitoken"))

        response = client.delete(f"/api/generic_tokens/apitoken/{row.pk}/")

        assert response.status_code == 204
        assert script(token).get(TICKETS).status_code in REFUSED

    def test_nobody_changes_one(self, client):
        owner = person()
        token_for(owner)
        row = ApiToken.objects.get(user=owner)
        client.force_login(person("view_apitoken", "change_apitoken"))

        response = client.patch(
            f"/api/generic_tokens/apitoken/{row.pk}/",
            {"scope": "read_write"},
            content_type="application/json",
        )

        assert response.status_code == 403


class TestTheChecks:
    def test_tokens_the_api_does_not_accept_are_named(self, settings):
        from generic.tokens.checks import check_tokens

        settings.REST_FRAMEWORK = {
            "DEFAULT_AUTHENTICATION_CLASSES": [
                "rest_framework.authentication.SessionAuthentication"
            ]
        }

        assert "generic.W008" in [message.id for message in check_tokens()]

    def test_nothing_to_say_when_wired(self):
        from generic.tokens.checks import check_tokens

        assert check_tokens() == []

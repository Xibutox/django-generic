"""The sign-in page, when a password is not the only way in.

The framework speaks no protocol: what is tested here is the door -
which ways in are offered, in what order, carrying what, and what the
page refuses to do.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from generic.sites import site

pytestmark = pytest.mark.django_db

LOGIN = "/login/"


@pytest.fixture
def door():
    """The site's providers, restored afterwards whatever happens."""
    declared = list(site._sso_providers)
    site._sso_providers.clear()

    yield site

    site._sso_providers[:] = declared


def page(client, query: str = ""):
    return client.get(f"{LOGIN}{query}")


def providers(client, query: str = "") -> list[dict]:
    return page(client, query).context["sso_providers"]


class TestWhatIsOffered:
    def test_a_password_is_the_only_way_in_by_default(self, door, client):
        response = page(client)

        assert response.context["sso_providers"] == []
        assert response.context["password_login"] is True
        # The form, not folded away behind anything.
        assert "auth-password" not in response.content.decode()

    def test_a_declared_provider_leads(self, door, client):
        door.add_sso_provider("Entra ID", url="/sso/start/")
        html = page(client).content.decode()

        assert [entry["label"] for entry in providers(client)] == ["Entra ID"]
        assert 'href="/sso/start/"' in html
        # And the password form is still there, folded under it.
        assert "auth-password" in html

    def test_a_route_is_resolved_to_its_address(self, door, client):
        door.add_sso_provider("Example", route="example:sso")

        assert providers(client)[0]["url"].endswith("/sso/")

    def test_a_route_that_is_not_mounted_offers_nothing(self, door, client):
        """A library the project did not install must not take down the
        one page nobody can sign in without."""
        door.add_sso_provider("Ghost", route="nothing:here")

        assert providers(client) == []
        assert page(client).status_code == 200

    def test_they_come_in_the_order_they_declare(self, door, client):
        door.add_sso_provider("Second", url="/b/", order=1)
        door.add_sso_provider("First", url="/a/", order=0)

        assert [entry["label"] for entry in providers(client)] == [
            "First",
            "Second",
        ]

    def test_a_script_is_refused_where_it_is_declared(self, door):
        with pytest.raises(ImproperlyConfigured):
            door.add_sso_provider("Trouble", url="javascript:alert(1)")


class TestWhereItSendsYou:
    def test_the_destination_travels_with_the_link(self, door, client):
        door.add_sso_provider("Entra ID", url="/sso/start/")

        entry = providers(client, "?next=/example/ticket/")[0]

        assert entry["url"] == "/sso/start/?next=%2Fexample%2Fticket%2F"

    def test_an_address_off_this_site_does_not(self, door, client):
        """Django refuses it for the form; the button must not be the
        way round that."""
        door.add_sso_provider("Entra ID", url="/sso/start/")

        entry = providers(client, "?next=https://evil.test/")[0]

        assert entry["url"] == "/sso/start/"

    def test_a_provider_may_keep_its_own_state(self, door, client):
        """Some libraries carry the destination themselves."""
        door.add_sso_provider("Entra ID", url="/sso/start/", next_param="")

        entry = providers(client, "?next=/example/ticket/")[0]

        assert entry["url"] == "/sso/start/"

    def test_a_provider_that_already_has_a_query_keeps_it(
        self,
        door,
        client,
    ):
        door.add_sso_provider("Entra ID", url="/sso/start/?tenant=acme")

        entry = providers(client, "?next=/wiki/")[0]

        assert entry["url"] == "/sso/start/?tenant=acme&next=%2Fwiki%2F"


class TestForbiddingPasswords:
    @override_settings(GENERIC={"SSO_PASSWORD_LOGIN": False})
    def test_the_form_goes_when_something_else_is_offered(
        self,
        door,
        client,
    ):
        door.add_sso_provider("Entra ID", url="/sso/start/")
        response = page(client)

        assert response.context["password_login"] is False
        assert 'name="password"' not in response.content.decode()

    @override_settings(GENERIC={"SSO_PASSWORD_LOGIN": False})
    def test_but_never_when_nothing_else_is(self, door, client):
        """A page with no way in at all is a locked door, not a policy."""
        response = page(client)

        assert response.context["password_login"] is True
        assert 'name="password"' in response.content.decode()

    def test_signing_in_with_a_password_still_works(self, door, client, user):
        """The form is folded away, not disconnected."""
        door.add_sso_provider("Entra ID", url="/sso/start/")
        user.set_password("a-long-enough-passphrase")
        user.save()

        response = client.post(
            LOGIN,
            {
                "username": user.username,
                "password": "a-long-enough-passphrase",
                "next": "/",
            },
        )

        assert response.status_code == 302
        assert client.session.get("_auth_user_id") == str(user.pk)

    def test_a_refused_password_opens_the_fold(self, door, client, user):
        """The error would otherwise point at a form nobody can see."""
        door.add_sso_provider("Entra ID", url="/sso/start/")

        html = client.post(
            LOGIN,
            {"username": user.username, "password": "wrong"},
        ).content.decode()

        assert '<details class="auth-password" open>' in html


class TestTheSetting:
    @override_settings(
        GENERIC={
            "SSO_PROVIDERS": [
                {"label": "Entra ID", "url": "/sso/start/", "icon": "lock"}
            ]
        }
    )
    def test_a_provider_can_be_configured_rather_than_declared(
        self,
        door,
        client,
    ):
        entry = providers(client)[0]

        assert entry["label"] == "Entra ID"
        assert entry["icon"] == "lock"

    @override_settings(GENERIC={"SSO_PROVIDERS": [{"url": "/sso/"}]})
    def test_an_entry_without_a_label_is_refused(self, door, client):
        with pytest.raises(ImproperlyConfigured):
            page(client)

    @override_settings(
        GENERIC={"SSO_PROVIDERS": [{"label": "X", "rout": "a:b"}]}
    )
    def test_a_misspelled_key_is_refused_by_name(self, door, client):
        with pytest.raises(ImproperlyConfigured) as refusal:
            page(client)

        assert "rout" in str(refusal.value)

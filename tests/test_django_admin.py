"""Django's admin beside the site: its sign-in form behind the same
lock, and a setting that takes its pages away."""

from __future__ import annotations

import importlib

import pytest
from django.contrib import admin
from django.urls import clear_url_caches

from generic.accounts import throttle
from generic.accounts.adminforms import ThrottledAdminAuthenticationForm
from generic.conf import generic_settings
from generic.sites import site
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

ADMIN_LOGIN = "/admin/login/"
LOGIN = "/login/"


@pytest.fixture
def mounted(settings):
    """The admin in the URLconf, read again for each test: what it
    mounts is decided when the URLconf is."""
    import tests.admin_urls

    def read_again():
        importlib.reload(tests.admin_urls)
        clear_url_caches()

    settings.ROOT_URLCONF = "tests.admin_urls"
    read_again()

    yield read_again

    generic_settings.reload()
    read_again()


@pytest.fixture
def configure(settings, mounted):
    def configure(**values):
        settings.GENERIC = {**settings.GENERIC, **values}
        generic_settings.reload()
        mounted()

    return configure


@pytest.fixture
def boss():
    user = UserFactory(username="boss", is_staff=True, is_superuser=True)
    user.set_password("right-password")
    user.save()

    return user


def attempt(client, password: str, url: str = ADMIN_LOGIN):
    return client.post(url, {"username": "boss", "password": password})


class TestTheAdminSignInIsBehindTheLock:
    def test_the_default_admin_site_got_the_form(self):
        assert admin.site.login_form is ThrottledAdminAuthenticationForm

    def test_a_right_password_signs_in(self, client, boss, configure):
        configure(LOGIN_MAX_ATTEMPTS=3)

        assert attempt(client, "right-password").status_code == 302
        assert "_auth_user_id" in client.session

    def test_too_many_failures_there_lock_the_account(
        self, client, boss, configure
    ):
        configure(LOGIN_MAX_ATTEMPTS=3, LOGIN_LOCKOUT_MINUTES=10)

        for _ in range(3):
            attempt(client, "wrong")

        response = attempt(client, "right-password")

        assert response.status_code == 200
        assert "Too many failed attempts" in response.content.decode()
        assert "_auth_user_id" not in client.session
        assert throttle.is_locked(None, "boss")

    def test_an_account_locked_on_the_site_is_locked_there_too(
        self, client, boss, configure
    ):
        configure(LOGIN_MAX_ATTEMPTS=3)

        for _ in range(3):
            attempt(client, "wrong", url=LOGIN)

        response = attempt(client, "right-password")

        assert response.status_code == 200
        assert "_auth_user_id" not in client.session

    def test_and_the_other_way_round(self, client, boss, configure):
        configure(LOGIN_MAX_ATTEMPTS=3)

        for _ in range(3):
            attempt(client, "wrong")

        response = attempt(client, "right-password", url=LOGIN)

        assert response.status_code == 200
        assert "_auth_user_id" not in client.session

    def test_nothing_is_counted_when_the_lock_is_off(
        self, client, boss, configure
    ):
        configure(LOGIN_MAX_ATTEMPTS=None)

        for _ in range(8):
            attempt(client, "wrong")

        assert attempt(client, "right-password").status_code == 302


class TestTurningTheAdminOff:
    def test_it_answers_by_default(self, client, boss, mounted):
        client.force_login(boss)

        assert client.get("/admin/").status_code == 200
        assert client.get(ADMIN_LOGIN).status_code in (200, 302)
        assert site.get_admin_url(boss) == "/admin/"

    def test_no_page_of_it_answers_once_off(self, client, boss, configure):
        configure(DJANGO_ADMIN=False)
        client.force_login(boss)

        for url in ("/admin/", ADMIN_LOGIN, "/admin/auth/user/"):
            assert client.get(url).status_code == 404, url

    def test_its_sign_in_form_takes_no_password_once_off(
        self, client, boss, configure
    ):
        configure(DJANGO_ADMIN=False)

        assert attempt(client, "right-password").status_code == 404
        assert "_auth_user_id" not in client.session

    def test_the_link_to_it_goes_too(self, boss, configure):
        configure(DJANGO_ADMIN=False)

        assert site.get_admin_url(boss) == ""

    def test_the_site_itself_is_untouched(self, client, boss, configure):
        configure(DJANGO_ADMIN=False)
        client.force_login(boss)

        assert client.get("/").status_code == 200

    def test_the_switch_is_set_once(self):
        from django.apps import apps

        before = admin.site.get_urls
        apps.get_app_config("generic").arm_django_admin()

        assert admin.site.get_urls is before

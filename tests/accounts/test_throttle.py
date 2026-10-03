"""Failed passwords, counted: an account - or an address - that fails
too often is refused for a while, without its password being tried."""

from __future__ import annotations

import pytest

from generic.accounts import throttle
from generic.conf import generic_settings
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

LOGIN = "/login/"


@pytest.fixture
def alice():
    user = UserFactory(username="alice")
    user.set_password("right-password")
    user.save()

    return user


@pytest.fixture
def limits(settings):
    settings.GENERIC = {
        **settings.GENERIC,
        "LOGIN_MAX_ATTEMPTS": 3,
        "LOGIN_LOCKOUT_MINUTES": 10,
    }
    generic_settings._cache.clear()

    yield

    generic_settings._cache.clear()


def attempt(client, password: str, username: str = "alice", **extra):
    return client.post(
        LOGIN, {"username": username, "password": password}, **extra
    )


def test_a_right_password_signs_in(client, alice, limits):
    response = attempt(client, "right-password")

    assert response.status_code == 302


def test_too_many_failures_lock_the_account(client, alice, limits):
    for _ in range(3):
        attempt(client, "wrong")

    response = attempt(client, "right-password")

    assert response.status_code == 200
    assert "Too many failed attempts" in response.content.decode()
    assert "10 minutes" in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_the_name_is_read_without_case(client, alice, limits):
    for _ in range(3):
        attempt(client, "wrong", username="ALICE ")

    assert throttle.is_locked(None, "alice")


def test_a_success_starts_the_count_again(client, alice, limits):
    attempt(client, "wrong")
    attempt(client, "wrong")
    attempt(client, "right-password")
    client.logout()
    attempt(client, "wrong")
    attempt(client, "wrong")

    response = attempt(client, "right-password")

    assert response.status_code == 302


def test_an_address_trying_many_names_is_refused(client, alice, limits):
    # Four times the account's limit, over any accounts.
    for number in range(12):
        attempt(client, "wrong", username=f"nobody{number}")

    response = attempt(client, "right-password")

    assert response.status_code == 200
    assert "Too many failed attempts" in response.content.decode()


def test_another_address_still_signs_in(client, alice, limits):
    for number in range(12):
        attempt(client, "wrong", username=f"nobody{number}")

    response = attempt(client, "right-password", REMOTE_ADDR="10.1.1.1")

    assert response.status_code == 302


def test_none_counts_nothing(client, alice, settings):
    settings.GENERIC = {**settings.GENERIC, "LOGIN_MAX_ATTEMPTS": None}
    generic_settings._cache.clear()

    try:
        for _ in range(10):
            attempt(client, "wrong")

        assert attempt(client, "right-password").status_code == 302
    finally:
        generic_settings._cache.clear()

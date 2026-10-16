"""The project starts, and its pages answer."""

import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(client):
    user = get_user_model().objects.create_superuser(
        "admin", "admin@example.com", "a-long-test-password"
    )
    client.force_login(user)
    return user


def test_sign_in_page(client):
    assert client.get("/login/").status_code == 200


def test_signed_out_is_sent_to_sign_in(client):
    response = client.get("/")

    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_dashboard(client, admin):
    assert client.get("/").status_code == 200


def test_preferences(client, admin):
    response = client.get("/api/generic/account/preferences/")

    assert response.status_code == 200

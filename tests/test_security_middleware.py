"""generic.middleware: the idle sign-out and the Content-Security-Policy."""

from __future__ import annotations

import time

import pytest
from django.test import override_settings

from generic.middleware import (
    IDLE_HEADER,
    LAST_SEEN,
    RECOMMENDED_CSP,
    SIGNED_OUT_HEADER,
)

pytestmark = pytest.mark.django_db

IDLE = "generic.middleware.SessionIdleMiddleware"
CSP = "generic.middleware.CSPMiddleware"


@pytest.fixture
def with_idle(settings):
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, IDLE]
    settings.GENERIC = {**settings.GENERIC, "SESSION_IDLE_MINUTES": 30}


@pytest.fixture
def with_csp(settings):
    settings.MIDDLEWARE = [CSP, *settings.MIDDLEWARE]
    settings.GENERIC = {
        **settings.GENERIC,
        "CONTENT_SECURITY_POLICY": "recommended",
    }


def age_session(client, seconds):
    session = client.session
    session[LAST_SEEN] = int(time.time()) - seconds
    session.save()


# -- idle sign-out -----------------------------------------------------


def test_a_recent_session_stays_signed_in(with_idle, admin_client):
    admin_client.get("/")
    age_session(admin_client, 10 * 60)

    response = admin_client.get("/api/example/ticket/")

    assert response.status_code == 200
    assert SIGNED_OUT_HEADER not in response.headers


def test_a_session_left_alone_is_signed_out(with_idle, admin_client):
    admin_client.get("/")
    age_session(admin_client, 31 * 60)

    response = admin_client.get("/api/example/ticket/")

    assert response.status_code in (401, 403)
    assert response.headers[SIGNED_OUT_HEADER] == "idle"
    assert "_auth_user_id" not in admin_client.session


def test_the_sign_in_page_says_why(with_idle, admin_client):
    admin_client.get("/")
    age_session(admin_client, 31 * 60)

    response = admin_client.get("/", follow=True)

    assert b"without activity" in response.content


def test_a_page_refreshing_itself_keeps_nobody_signed_in(
    with_idle, admin_client
):
    """Requests keep coming, but each says nobody touched the page: they
    move the clock no further than the reader's last action, and the
    session ends 30 minutes after it."""
    admin_client.get("/")
    age_session(admin_client, 20 * 60)

    kept = admin_client.get(
        "/api/example/ticket/", headers={IDLE_HEADER: str(20 * 60)}
    )
    age_session(admin_client, 31 * 60)
    ended = admin_client.get(
        "/api/example/ticket/", headers={IDLE_HEADER: str(31 * 60)}
    )

    assert kept.status_code == 200
    assert ended.headers.get(SIGNED_OUT_HEADER) == "idle"


def test_a_touched_page_counts_as_activity(with_idle, admin_client):
    admin_client.get("/")
    age_session(admin_client, 29 * 60)

    response = admin_client.get(
        "/api/example/ticket/", headers={IDLE_HEADER: "5"}
    )

    assert response.status_code == 200
    assert int(time.time()) - admin_client.session[LAST_SEEN] < 60


def test_the_time_is_written_at_most_once_a_minute(with_idle, admin_client):
    admin_client.get("/")
    first = admin_client.session[LAST_SEEN]

    admin_client.get("/api/example/ticket/")

    assert admin_client.session[LAST_SEEN] == first


def test_off_without_the_setting(settings, admin_client):
    settings.MIDDLEWARE = [*settings.MIDDLEWARE, IDLE]
    admin_client.get("/")
    age_session(admin_client, 24 * 60 * 60)

    assert admin_client.get("/api/example/ticket/").status_code == 200


def test_a_nonsense_idle_header_is_activity(with_idle, admin_client):
    admin_client.get("/")

    response = admin_client.get(
        "/api/example/ticket/", headers={IDLE_HEADER: "soon"}
    )

    assert response.status_code == 200


# -- Content-Security-Policy -------------------------------------------


def test_every_page_gets_the_policy(with_csp, admin_client):
    response = admin_client.get("/")
    policy = response.headers["Content-Security-Policy"]

    assert "default-src 'self'" in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'self'" in policy
    assert "wss://testserver" in policy


def test_the_page_scripts_carry_the_nonce(with_csp, admin_client):
    response = admin_client.get("/")
    policy = response.headers["Content-Security-Policy"]
    nonce = policy.split("'nonce-")[1].split("'")[0]
    page = response.content.decode()

    assert f'<script nonce="{nonce}">' in page
    assert "<script>" not in page


def test_each_request_its_own_nonce(with_csp, admin_client):
    first = admin_client.get("/").headers["Content-Security-Policy"]
    second = admin_client.get("/").headers["Content-Security-Policy"]

    assert first != second


def test_report_only(settings, with_csp, admin_client):
    settings.GENERIC = {
        **settings.GENERIC,
        "CONTENT_SECURITY_POLICY_REPORT_ONLY": True,
    }

    response = admin_client.get("/")

    assert "Content-Security-Policy" not in response.headers
    assert (
        "default-src"
        in response.headers["Content-Security-Policy-Report-Only"]
    )


def test_a_policy_of_its_own(settings, with_csp, admin_client):
    settings.GENERIC = {
        **settings.GENERIC,
        "CONTENT_SECURITY_POLICY": {"default-src": ["'none'"]},
    }

    response = admin_client.get("/")

    assert response.headers["Content-Security-Policy"] == "default-src 'none'"


def test_off_by_default(settings, admin_client):
    settings.MIDDLEWARE = [CSP, *settings.MIDDLEWARE]

    assert "Content-Security-Policy" not in admin_client.get("/").headers


def test_an_answer_with_its_own_policy_keeps_it(with_csp, rf):
    from django.http import HttpResponse

    from generic.middleware import CSPMiddleware

    def view(request):
        response = HttpResponse("file")
        response.headers["Content-Security-Policy"] = "sandbox"
        return response

    request = rf.get("/")
    with override_settings(GENERIC={"CONTENT_SECURITY_POLICY": "recommended"}):
        response = CSPMiddleware(view)(request)

    assert response.headers["Content-Security-Policy"] == "sandbox"


def test_the_recommended_policy_allows_no_inline_script_without_nonce():
    assert "'unsafe-inline'" not in RECOMMENDED_CSP["script-src"]
    assert "'nonce'" in RECOMMENDED_CSP["script-src"]

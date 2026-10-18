"""The pages under the Content-Security-Policy every browser test uses."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

LIST = "/example/ticket/"


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


def test_the_list_works_under_the_policy(signed_in, console):
    """The header is sent, the page's own scripts run - the table draws
    its rows - and a script injected later is refused."""
    page = signed_in
    response = page.goto(LIST)
    policy = response.headers["content-security-policy"]

    assert "script-src 'self' 'unsafe-eval' 'nonce-" in policy
    expect(page.locator("#datatable tbody tr")).to_have_count(10)

    with page.expect_console_message(
        lambda message: "Content Security Policy" in message.text
    ):
        page.evaluate("""() => {
                const script = document.createElement("script");
                script.textContent = "window.injected = true";
                document.body.appendChild(script);
            }""")

    assert page.evaluate("() => window.injected") is None
    # The refusal is the console error this test is about.
    refused = [
        error for error in console.errors if "Content Security" in error
    ]
    assert refused
    console.errors[:] = [e for e in console.errors if e not in refused]


def test_the_table_says_how_long_the_page_was_left_alone(signed_in):
    """Its rows are fetched with X-Generic-Idle, so a redraw nobody
    asked for keeps no idle session alive (SessionIdleMiddleware)."""
    page = signed_in

    with page.expect_request(
        lambda request: "/api/example/ticket/" in request.url
    ) as rows:
        page.goto(LIST)

    assert rows.value.headers["x-generic-idle"].isdigit()

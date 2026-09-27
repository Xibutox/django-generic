"""The sign-in page, filled in as a person does."""

from __future__ import annotations

import re

from playwright.sync_api import expect


def open_password_form(page):
    page.goto("/login/")
    # The example declares a provider: its button leads, and the
    # password form waits folded underneath.
    expect(
        page.get_by_role("link", name="Continue with Example SSO")
    ).to_be_visible()
    page.get_by_text("Sign in with a password instead").click()


def test_the_password_form_signs_in_and_lands_on_the_dashboard(
    page, admin, password
):
    open_password_form(page)
    page.get_by_label("Username").fill("admin")
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()

    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    expect(page.get_by_role("button", name="Account menu")).to_be_visible()


def test_a_wrong_password_is_refused_on_the_page(page, admin):
    open_password_form(page)
    page.get_by_label("Username").fill("admin")
    page.get_by_label("Password").fill("not the password")
    page.get_by_role("button", name="Sign in", exact=True).click()

    expect(page.get_by_role("alert")).to_contain_text(
        "Please enter a correct username and password"
    )
    expect(page).to_have_url(re.compile(r"/login/$"))
    # Unfolded again, so the error points at a form one can see.
    expect(page.get_by_label("Password")).to_be_visible()

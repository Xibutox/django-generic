"""The add and change pages: a schema form, sent through the API."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from example.models import Ticket

ADD = "/example/ticket/add/"


def field(page, name):
    """A field's box on the form, by the field's name."""
    return page.locator(f'.sf-field[data-field="{name}"]')


def pick(page, name, typed, label):
    """Choose ``label`` in a Select2 relation, typing ``typed`` first."""
    field(page, name).locator(".select2-selection").click()
    page.locator(".select2-container--open .select2-search__field").fill(typed)
    page.locator(".select2-results__option", has_text=label).click()
    expect(field(page, name).locator(".select2-selection")).to_contain_text(
        label
    )


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


def test_a_required_field_left_empty_is_named(signed_in, console):
    page = signed_in
    # The server answers the form with a 400 and the errors: expected.
    console.allow(400, "/api/example/ticket/")
    page.goto(ADD)
    field(page, "title").locator("input").fill("Projector does not start")

    page.get_by_role("button", name="Create").click()

    expect(field(page, "reference")).to_have_class(re.compile("has-error"))
    expect(field(page, "reference").locator(".sf-errors")).to_have_text(
        "This field may not be blank."
    )
    expect(page.locator(".schema-form .form-errors").first).to_contain_text(
        "Please correct the errors below."
    )
    expect(page).to_have_url(re.compile(re.escape(ADD) + "$"))
    assert not Ticket.objects.filter(title="Projector does not start").exists()


def test_a_new_ticket_is_saved_and_shown(signed_in):
    page = signed_in
    page.goto(ADD)

    field(page, "reference").locator("input").fill("SD-2001")
    field(page, "title").locator("input").fill("Projector does not start")
    pick(page, "team", "Infra", "Infrastructure")
    page.get_by_role("button", name="Create").click()

    expect(page).to_have_url(re.compile(r"/example/ticket/\d+/$"))
    ticket = Ticket.objects.get(reference="SD-2001")
    assert page.url.endswith(f"/example/ticket/{ticket.pk}/")
    expect(page.locator("h1")).to_have_text(
        "SD-2001 - Projector does not start"
    )
    team = page.locator(".summary-field").filter(
        has=page.locator("dt", has_text="Team")
    )
    expect(team.locator("dd")).to_contain_text("Infrastructure")
    assert ticket.team.name == "Infrastructure"


def test_an_edited_title_is_saved_and_kept_in_the_history(signed_in, desk):
    page = signed_in
    ticket = desk["login"]
    page.goto(f"/example/ticket/{ticket.pk}/change/")
    title = field(page, "title").locator("input")
    expect(title).to_have_value("Login fails after password reset")

    title.fill("Login fails after every password reset")
    page.get_by_role("button", name="Save", exact=True).click()

    # Saved, and back on the ticket's page, under its new title.
    expect(page).to_have_url(re.compile(rf"/example/ticket/{ticket.pk}/$"))
    expect(page.locator("h1")).to_have_text(
        "SD-1001 - Login fails after every password reset"
    )
    page.locator(".summary-tab", has_text="History").click()

    change = page.locator(".history-entry").first.locator(".history-change")
    expect(change.locator(".history-change__field")).to_have_text("Title")
    expect(change.locator(".history-change__from")).to_have_text(
        "Login fails after password reset"
    )
    expect(change.locator(".history-change__to")).to_have_text(
        "Login fails after every password reset"
    )
    expect(page.locator(".history-entry").first).to_contain_text("admin")


def test_a_reader_is_refused_the_add_page(
    page, desk, viewer, sign_in, console
):
    sign_in(viewer)
    # Refused is what is expected: the browser logs the 403 all the same.
    console.allow(403, ADD)

    response = page.goto(ADD)

    assert response.status == 403
    expect(page.locator(".schema-form")).to_have_count(0)

"""An outline level opening its records in a dialog, edit mode or not.

The customers' outline declares its time entries with
``open_in_dialog=True``: a time entry's link opens its form over the
outline without the *Edit* button, and once it is saved the entries are
read again, the ticket above them still open.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


@pytest.fixture
def desk(transactional_db):
    from example.models import Agent, Customer, Team, Ticket, TimeEntry

    team = Team.objects.create(name="Front office", code="FO")
    agent = Agent.objects.create(name="Camille Rousseau", team=team)
    acme = Customer.objects.create(name="Acme", code="ACME")
    ticket = Ticket.objects.create(
        reference="SD-1",
        title="Login fails",
        team=team,
        customer=acme,
    )
    entry = TimeEntry.objects.create(
        ticket=ticket, agent=agent, hours=Decimal("1.50"), note="Setup"
    )

    return {"acme": acme, "ticket": ticket, "entry": entry}


def rows(page, depth):
    return page.locator(f"tr.outline-row[data-depth='{depth}']")


def unfold(page, depth, text):
    row = rows(page, depth).filter(has_text=text)
    row.locator(".tree-row__toggle").click()

    return row


def test_a_time_entry_opens_in_a_dialog_outside_edit_mode(
    page, admin, sign_in, desk
):
    from example.models import TimeEntry

    sign_in(admin)
    page.goto("/example/customer/?outline=1")
    unfold(page, 0, "Acme")
    unfold(page, 1, "SD-1")
    entry = rows(page, 2).filter(has_text="Setup")
    expect(entry).to_have_count(1)

    # Not editing: the ticket's link is its page, the entry's a dialog.
    expect(page.locator(".dt-outline-edit")).to_have_attribute(
        "aria-pressed", "false"
    )
    expect(
        rows(page, 1).first.locator(".outline-row__open.is-dialog")
    ).to_have_count(0)
    expect(entry.locator(".outline-row__open.is-dialog")).to_have_count(1)

    entry.locator(".outline-row__open").click()
    dialog = page.locator("dialog.dialog--frame")
    expect(dialog).to_be_visible()
    form = page.frame_locator("dialog.dialog--frame iframe")
    note = form.get_by_role("textbox", name="Note", exact=True)
    expect(note).to_have_value("Setup")
    note.fill("Setup, then a call")
    form.get_by_role("button", name="Save", exact=True).click()
    expect(dialog).to_have_count(0)

    # Read again where it stands: the ticket still open, the page kept.
    expect(rows(page, 2)).to_contain_text("Setup, then a call")
    expect(rows(page, 1).first).to_have_attribute("aria-expanded", "true")
    expect(page).to_have_url(r"/example/customer/?outline=1")
    assert TimeEntry.objects.get().note == "Setup, then a call"

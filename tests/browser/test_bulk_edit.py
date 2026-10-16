"""Bulk edit: the selection bar's dialog, its review and its write."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from example.models import Ticket

pytestmark = pytest.mark.browser

LIST = "/example/ticket/"


def row(page, reference):
    return page.locator("#datatable tbody tr").filter(has_text=reference)


@pytest.fixture
def dialog(page, desk, admin, sign_in):
    """The dialog, opened on SD-1001 (open) and SD-1004 (closed)."""
    sign_in(admin)
    page.goto(LIST)

    for reference in ("SD-1001", "SD-1004"):
        row(page, reference).locator(".dt-row-check").check()

    bar = page.locator(".dt-selection-bar")
    bar.locator(".dt-selection-bar__action").select_option("__bulk_edit__")
    bar.get_by_role("button", name="Apply").click()

    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Edit the selected tickets")
    expect(dialog).to_contain_text("2 tickets selected.")

    return dialog


def line(dialog, index):
    return dialog.locator(".bulk-edit__line").nth(index)


def choose_team(page, dialog, index, name):
    line(dialog, index).locator(".select2-selection").click()
    page.locator(".select2-results__option", has_text=name).click()


def test_the_review_names_what_is_left_and_the_write_follows_it(page, dialog):
    closed = Ticket.objects.get(reference="SD-1004")
    line(dialog, 0).locator(".bulk-edit__field").select_option("priority")
    line(dialog, 0).locator(".bulk-edit__value select").select_option("urgent")
    dialog.get_by_role("button", name="Add a field").click()
    line(dialog, 1).locator(".bulk-edit__field").select_option("team")
    choose_team(page, dialog, 1, "Infrastructure")

    dialog.get_by_role("button", name="Review the change").click()

    review = dialog.locator(".bulk-edit__review")
    # A closed ticket stays with its team (TicketResource).
    expect(review).to_contain_text("1 ticket will change.")
    expect(review).to_contain_text("1 will be left as it is:")
    expect(review).to_contain_text("SD-1004")
    expect(review).to_contain_text("Not to be changed on this record: team.")
    # The review wrote nothing.
    assert Ticket.objects.get(reference="SD-1001").priority != "urgent"

    dialog.get_by_role("button", name="Apply to 1").click()

    expect(page.locator(".toast")).to_contain_text("1 ticket changed.")
    expect(row(page, "SD-1001")).to_contain_text("Urgent")
    login = Ticket.objects.get(reference="SD-1001")
    assert login.priority == Ticket.Priority.URGENT
    assert login.team.name == "Infrastructure"
    # Left as it was, whole: not half-written.
    left = Ticket.objects.get(reference="SD-1004")
    assert (left.team_id, left.priority) == (closed.team_id, closed.priority)


def test_changing_anything_after_the_review_asks_for_a_new_one(page, dialog):
    line(dialog, 0).locator(".bulk-edit__field").select_option("is_billable")
    line(dialog, 0).locator(".bulk-edit__value input").check()
    dialog.get_by_role("button", name="Review the change").click()
    expect(
        dialog.get_by_role("button", name=re.compile("Apply to"))
    ).to_be_visible()

    dialog.get_by_role("button", name="Add a field").click()

    expect(
        dialog.get_by_role("button", name="Review the change")
    ).to_be_visible()
    expect(dialog.locator(".bulk-edit__review")).to_be_empty()


def test_tags_are_added_beside_each_tickets_own(page, dialog):
    line(dialog, 0).locator(".bulk-edit__field").select_option("tags")
    line(dialog, 0).locator(".bulk-edit__mode").select_option("add")
    line(dialog, 0).locator(".select2-selection").click()
    page.locator(".select2-results__option", has_text="billing").click()
    dialog.locator(".dialog__title").click()

    dialog.get_by_role("button", name="Review the change").click()
    dialog.get_by_role("button", name="Apply to 2").click()

    expect(page.locator(".toast")).to_contain_text("2 tickets changed.")
    assert set(
        Ticket.objects.get(reference="SD-1001").tags.values_list(
            "name", flat=True
        )
    ) == {"regression", "release", "billing"}


def test_a_reader_is_not_offered_it(page, desk, viewer, sign_in):
    sign_in(viewer)
    page.goto(LIST)

    # Nothing to change, nothing to tick.
    expect(page.locator("#datatable tbody tr").first).to_be_visible()
    expect(page.locator(".dt-row-check")).to_have_count(0)

"""Undo: the button after a delete, a bulk action and a bulk edit."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from example.models import Ticket

pytestmark = pytest.mark.browser

LIST = "/example/ticket/"


def row(page, reference):
    return page.locator("#datatable tbody tr").filter(has_text=reference)


def undo_in(region):
    return region.get_by_role("button", name="Undo")


@pytest.fixture
def tickets(page, desk, admin, sign_in):
    sign_in(admin)
    page.goto(LIST)
    expect(row(page, "SD-1001")).to_be_visible()

    return page


def test_a_row_deleted_from_its_menu_comes_back(tickets):
    page = tickets
    menu = row(page, "SD-1002").locator(".dt-row-menu")
    # Scrolled to first: a scroll closes the menu it opens.
    menu.scroll_into_view_if_needed()
    menu.click()
    page.get_by_role("menuitem", name="Delete", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="Yes, delete").click()

    toast = page.locator(".toast").filter(has_text="was deleted")
    expect(toast).to_be_visible()
    expect(row(page, "SD-1002")).to_have_count(0)

    undo_in(toast).click()

    expect(page.locator(".toast").filter(has_text="Undone")).to_be_visible()
    expect(row(page, "SD-1002")).to_be_visible()
    assert Ticket.objects.filter(reference="SD-1002").exists()


def test_a_record_deleted_from_its_form_is_undone_from_the_list(tickets):
    page = tickets
    ticket = Ticket.objects.get(reference="SD-1005")
    page.goto(f"/example/ticket/{ticket.pk}/change/")
    page.get_by_role("button", name="Delete").first.click()
    page.get_by_role("dialog").get_by_role("button", name="Yes, delete").click()

    page.wait_for_url(f"**{LIST}")
    toast = page.locator(".toast").filter(has_text="was deleted")
    expect(toast).to_be_visible()

    undo_in(toast).click()

    expect(row(page, "SD-1005")).to_be_visible()


def test_a_bulk_delete_comes_back_with_its_comments(tickets):
    page = tickets
    comments = Ticket.objects.get(reference="SD-1001").comments.count()

    for reference in ("SD-1001", "SD-1003"):
        row(page, reference).locator(".dt-row-check").check()

    bar = page.locator(".dt-selection-bar")
    bar.locator(".dt-selection-bar__action").select_option("delete_selected")
    bar.get_by_role("button", name="Apply").click()
    page.get_by_role("dialog").get_by_role("button", name="Delete").click()

    toast = page.locator(".toast").filter(has_text="deleted")
    expect(toast).to_be_visible()
    expect(row(page, "SD-1003")).to_have_count(0)

    undo_in(toast).click()

    expect(row(page, "SD-1001")).to_be_visible()
    expect(row(page, "SD-1003")).to_be_visible()
    back = Ticket.objects.get(reference="SD-1001")
    assert back.comments.count() == comments


def test_the_delete_page_offers_it_on_the_list(tickets):
    page = tickets
    ticket = Ticket.objects.get(reference="SD-1004")
    page.goto(f"/example/ticket/{ticket.pk}/delete/")
    page.locator(".delete-form button[type=submit]").first.click()

    message = page.locator(".message").filter(has_text="was deleted")
    expect(message).to_be_visible()

    undo_in(message).click()

    expect(page.locator(".toast").filter(has_text="Undone")).to_be_visible()
    expect(message).to_have_count(0)
    expect(row(page, "SD-1004")).to_be_visible()


def test_an_applied_bulk_edit_is_taken_back(tickets):
    page = tickets
    before = Ticket.objects.get(reference="SD-1001").priority
    row(page, "SD-1001").locator(".dt-row-check").check()
    bar = page.locator(".dt-selection-bar")
    bar.locator(".dt-selection-bar__action").select_option("__bulk_edit__")
    bar.get_by_role("button", name="Apply").click()
    dialog = page.get_by_role("dialog")
    line = dialog.locator(".bulk-edit__line").nth(0)
    line.locator(".bulk-edit__field").select_option("priority")
    line.locator(".bulk-edit__value select").select_option("urgent")
    dialog.get_by_role("button", name="Review the change").click()
    dialog.get_by_role("button", name="Apply to 1").click()

    card = page.locator(".toast").filter(has_text="1 ticket changed.")
    expect(card).to_be_visible()

    undo_in(card).click()

    expect(page.locator(".toast").filter(has_text="Undone")).to_be_visible()
    assert Ticket.objects.get(reference="SD-1001").priority == before

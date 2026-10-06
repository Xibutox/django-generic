"""The ticket list: a DataTable drawn from the API, and what it offers."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from example.models import Ticket

LIST = "/example/ticket/"


def references(page):
    """The Reference cell of every row on screen, whatever its column."""
    return page.locator("#datatable tbody td").filter(
        has_text=re.compile(r"^SD-\d+$")
    )


def row(page, reference):
    return page.locator("#datatable tbody tr").filter(has_text=reference)


def info(page):
    return page.locator("#datatable_wrapper .dt-info")


def search_box(page):
    return page.locator(".dt-toolbar__search input")


def numbers(*values):
    return [f"SD-{value}" for value in values]


@pytest.fixture
def ticket_list(page, desk, admin, sign_in):
    sign_in(admin)
    page.goto(LIST)
    expect(references(page)).to_have_text(numbers(*range(1001, 1011)))

    return page


def test_the_rows_are_drawn_from_the_api(ticket_list):
    page = ticket_list

    expect(info(page)).to_have_text("1 to 10 of 25 rows")
    expect(row(page, "SD-1001")).to_contain_text(
        "Login fails after password reset"
    )
    expect(row(page, "SD-1001")).to_contain_text("Acme Corporation")


def test_typing_in_the_search_box_narrows_the_rows(ticket_list):
    page = ticket_list

    search_box(page).fill("invoice")

    expect(references(page)).to_have_text(numbers(1002, 1003, 1016))
    expect(info(page)).to_contain_text("1 to 3 of 3 rows")


def test_a_column_header_orders_the_rows(ticket_list):
    page = ticket_list

    page.locator('#datatable th[title="Title"]').click()

    # By title, A to Z: "Backup job failed overnight" first.
    expect(references(page).first).to_have_text("SD-1020")
    expect(page.locator("#datatable tbody tr").first).to_contain_text(
        "Backup job failed overnight"
    )


def test_the_next_page_shows_the_next_rows(ticket_list):
    page = ticket_list

    page.locator(".dt-paging").get_by_role("link", name="Next").click()

    expect(references(page)).to_have_text(numbers(*range(1011, 1021)))
    expect(info(page)).to_have_text("11 to 20 of 25 rows")


def test_a_reload_keeps_the_search_and_the_page(ticket_list):
    page = ticket_list

    # Every other ticket was reported by phone: thirteen, two pages.
    search_box(page).fill("phone")
    expect(info(page)).to_contain_text("1 to 10 of 13 rows")
    page.locator(".dt-paging").get_by_role("link", name="Next").click()
    expect(references(page)).to_have_text(numbers(1021, 1023, 1025))

    # The search travels in the address, the page in the table's own
    # saved state: both come back.
    expect(page).to_have_url(re.compile(r"[?&]search=phone"))
    page.reload()

    expect(search_box(page)).to_have_value("phone")
    expect(references(page)).to_have_text(numbers(1021, 1023, 1025))
    expect(info(page)).to_contain_text("11 to 13 of 13 rows")


def test_a_typed_filter_narrows_and_its_chip_takes_it_back(ticket_list):
    page = ticket_list

    # name:value followed by a space turns into a chip.
    search_box(page).fill("status:open ")

    chip = page.locator(".dt-filterbar .dt-chip")
    expect(chip).to_have_count(1)
    expect(chip).to_contain_text("Status")
    expect(chip).to_contain_text("Open")
    expect(search_box(page)).to_have_value("")
    expect(references(page)).to_have_text(
        numbers(1001, 1005, 1009, 1013, 1017, 1021, 1025)
    )
    expect(page).to_have_url(re.compile(r"[?&]filters="))

    chip.locator(".dt-chip__remove").click()

    expect(chip).to_have_count(0)
    expect(references(page)).to_have_text(numbers(*range(1001, 1011)))
    expect(info(page)).to_have_text("1 to 10 of 25 rows")


def test_a_typed_relation_filter_can_hold_words(ticket_list):
    page = ticket_list

    # "~": every customer whose name contains the words, none picked.
    search_box(page).fill("customer:~acme ")

    chip = page.locator(".dt-filterbar .dt-chip")
    expect(chip).to_have_count(1)
    expect(chip).to_contain_text("contains")
    expect(chip).to_contain_text("acme")
    expect(info(page)).to_contain_text("1 to 9 of 9 rows")


def assignee_values(page, term):
    # The search row's field, not the header's funnel.
    page.locator(
        ".dt-filter-field__picker[aria-label='Filter Assignee']"
    ).click()
    editor = page.locator(".dt-editor")
    editor.locator(".dt-choices input[type=search]").fill(term)
    # Camille Rousseau and Lea Martin.
    expect(editor.locator(".dt-choice")).to_have_count(2)

    return editor


def test_every_value_a_search_found_is_picked_at_once(ticket_list):
    page = ticket_list
    editor = assignee_values(page, "ea")

    editor.get_by_role("button", name="Select the 2 values found").click()

    expect(editor.locator(".dt-choice input:checked")).to_have_count(2)
    expect(info(page)).to_contain_text("1 to 10 of 12 rows")
    expect(
        editor.get_by_role("button", name="Unselect these values")
    ).to_be_visible()


def test_a_relation_search_can_become_the_filter(ticket_list):
    page = ticket_list
    editor = assignee_values(page, "ea")

    editor.get_by_role("button", name="Contains \u201cea\u201d").click()

    expect(editor.locator(".dt-editor__operator")).to_have_value("contains")
    expect(info(page)).to_contain_text("1 to 10 of 12 rows")


def test_a_bulk_transition_says_what_was_done_and_skipped(ticket_list):
    page = ticket_list
    # SD-1001 is open and may close; SD-1004 is closed already.
    for reference in ("SD-1001", "SD-1004"):
        row(page, reference).locator(".dt-row-check").check()

    bar = page.locator(".dt-selection-bar")
    expect(bar).to_contain_text("2 selected")
    bar.locator(".dt-selection-bar__action").select_option("transition:close")
    bar.get_by_role("button", name="Apply").click()

    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Close this ticket?")
    dialog.locator(".dialog__footer").get_by_role(
        "button", name="Close"
    ).click()

    expect(page.locator(".toast")).to_contain_text("Close: 1 done, 1 skipped")
    expect(row(page, "SD-1001")).to_contain_text("Closed")
    assert (
        Ticket.objects.get(reference="SD-1001").status == Ticket.Status.CLOSED
    )


def test_the_excel_export_downloads_a_workbook(ticket_list):
    page = ticket_list

    page.get_by_role("button", name="Export", exact=True).click()

    with page.expect_download() as download:
        page.locator(".dt-export-panel").get_by_role(
            "button", name="Excel"
        ).click()

    assert download.value.suggested_filename.endswith(".xlsx")


def test_a_reader_is_offered_no_add_button(page, desk, viewer, sign_in):
    sign_in(viewer)
    page.goto(LIST)

    expect(references(page)).to_have_text(numbers(*range(1001, 1011)))
    expect(page.get_by_role("link", name="Add Ticket")).to_have_count(0)
    # Nor bulk actions to change anything: nothing to tick.
    expect(page.locator(".dt-row-check")).to_have_count(0)

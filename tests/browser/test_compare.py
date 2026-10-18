"""Records side by side: ticked on the list, compared on their page."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser

LIST = "/example/ticket/"


def row(page, reference):
    return page.locator("#datatable tbody tr").filter(has_text=reference)


@pytest.fixture
def compared(page, desk, admin, sign_in):
    """SD-1001, SD-1002 and SD-1004, ticked and compared."""
    sign_in(admin)
    page.goto(LIST)

    for reference in ("SD-1001", "SD-1002", "SD-1004"):
        row(page, reference).locator(".dt-row-check").check()

    bar = page.locator(".dt-selection-bar")
    bar.locator(".dt-selection-bar__action").select_option("__compare__")
    bar.get_by_role("button", name="Apply").click()

    page.wait_for_url("**/example/ticket/compare/?ids=*")
    expect(page.locator(".compare-table")).to_be_visible()

    return page


def test_the_ticked_rows_are_set_side_by_side(compared):
    page = compared
    heads = page.locator(".compare-table thead .compare-table__record")

    expect(heads).to_have_count(3)
    expect(heads.nth(0)).to_contain_text("SD-1001")
    expect(heads.nth(2)).to_contain_text("SD-1004")
    priority = page.locator(".compare-row", has_text="Priority")
    expect(priority.locator("td")).to_have_count(3)


def test_only_the_differences_hides_the_rows_alike(compared):
    page = compared
    alike = page.locator(".compare-row.is-same").first
    different = page.locator(".compare-row.is-different").first

    expect(alike).to_be_visible()
    page.get_by_text("Only the differences").click()

    expect(alike).to_be_hidden()
    expect(different).to_be_visible()


def test_a_record_is_taken_out_and_the_address_follows(compared):
    page = compared
    page.get_by_role("button", name="Remove SD-1004").click()

    heads = page.locator(".compare-table thead .compare-table__record")
    expect(heads).to_have_count(2)
    assert "SD-1004" not in heads.all_inner_texts()[-1]
    assert page.url.count(",") == 1
    # Two left: nothing more to take out.
    expect(page.locator(".compare-table__remove")).to_have_count(0)


def test_one_row_ticked_is_not_compared(page, desk, admin, sign_in):
    sign_in(admin)
    page.goto(LIST)
    row(page, "SD-1001").locator(".dt-row-check").check()

    bar = page.locator(".dt-selection-bar")
    bar.locator(".dt-selection-bar__action").select_option("__compare__")
    bar.get_by_role("button", name="Apply").click()

    expect(page.locator(".toast")).to_contain_text("Tick between 2 and 6")
    assert "/compare/" not in page.url

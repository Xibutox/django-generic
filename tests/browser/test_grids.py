"""The Triage grid: cells that are their controls, saved as they change."""

from __future__ import annotations

from playwright.sync_api import expect

from example.models import Ticket

TRIAGE = "/example/triage/"


def priority(page, reference):
    row = page.locator("table.dataTable tbody tr").filter(has_text=reference)

    return row.locator('select[aria-label="Priority"]')


def test_an_edited_cell_is_saved_and_still_there_after_a_reload(
    page, desk, admin, sign_in
):
    sign_in(admin)
    page.goto(TRIAGE)
    cell = priority(page, "SD-1001")
    expect(cell).to_have_value("high")

    with page.expect_response(
        lambda response: "/cells/" in response.url
        and response.request.method == "PATCH"
    ) as saved:
        cell.select_option("urgent")

    assert saved.value.ok
    assert (
        Ticket.objects.get(reference="SD-1001").priority
        == Ticket.Priority.URGENT
    )

    page.reload()

    expect(priority(page, "SD-1001")).to_have_value("urgent")
    # The ticket beside it kept its own.
    expect(priority(page, "SD-1002")).to_have_value("normal")

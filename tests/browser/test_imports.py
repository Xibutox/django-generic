"""The ticket import: a file chosen, its columns matched, checked, written."""

from __future__ import annotations

from playwright.sync_api import expect

from example.models import Ticket

CSV = (
    "Reference;Title;Team;Priority\n"
    "SD-2001;Projector does not start;Front office;High\n"
    "SD-2002;Badge reader rejects everyone;Infrastructure;Urgent\n"
)


def stat(page, label):
    return page.locator(".stat").filter(
        has=page.locator(".stat__label", has_text=label)
    )


def test_a_csv_file_is_matched_checked_and_imported(
    page, desk, admin, sign_in
):
    sign_in(admin)
    page.goto("/example/ticket/import/")

    page.locator('input[type="file"]').set_input_files(
        {
            "name": "tickets.csv",
            "mimeType": "text/csv",
            "buffer": CSV.encode(),
        }
    )

    # Each column of the file, and where it goes.
    mapping = page.locator(".import__mapping tbody tr")
    expect(mapping).to_have_count(4)
    expect(mapping.first.locator("th")).to_have_text("Reference")
    expect(mapping.first.locator("select")).to_have_value("reference")
    expect(mapping.nth(2).locator("select")).to_have_value("team")

    # A dry run first: two new tickets, nothing written yet.
    expect(stat(page, "To create").locator(".stat__value")).to_have_text("2")
    expect(stat(page, "With errors").locator(".stat__value")).to_have_text("0")
    assert not Ticket.objects.filter(reference="SD-2001").exists()

    page.locator(".import__actions").get_by_role(
        "button", name="Import"
    ).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Create 2 and update 0 records?")
    dialog.locator(".dialog__footer").get_by_role(
        "button", name="Import"
    ).click()

    expect(page.locator(".toast")).to_contain_text("2 created, 0 updated.")
    imported = Ticket.objects.filter(reference__in=("SD-2001", "SD-2002"))
    assert {
        (ticket.reference, ticket.team.name, ticket.priority)
        for ticket in imported
    } == {
        ("SD-2001", "Front office", Ticket.Priority.HIGH),
        ("SD-2002", "Infrastructure", Ticket.Priority.URGENT),
    }

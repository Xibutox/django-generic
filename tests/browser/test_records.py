"""A ticket's summary page: its related tables and its transitions."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from example.models import Ticket, TicketComment


def related_rows(page, name):
    return page.locator(f'table[data-related="{name}"] tbody tr')


def tab(page, title):
    return page.locator(".summary-tab", has_text=title)


def transitions(page):
    return page.get_by_role("group", name="State")


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


def test_the_first_tab_loads_its_rows_every_time(signed_in, desk):
    """The regression test for 1.1.0's race.

    The page's own script and Alpine run before the tables' script, so
    the first tab asked for a table before ``GenericDataTables.start``
    existed ("is not a function"): summary.js waits for
    ``generic:datatables-loaded`` since. A race, so several loads.
    """
    page = signed_in
    url = f"/example/ticket/{desk['login'].pk}/"

    for attempt in range(5):
        page.goto(url)

        expect(tab(page, "Time entries")).to_have_attribute(
            "aria-selected", "true"
        )
        expect(related_rows(page, "time_entries")).to_have_count(3)
        expect(related_rows(page, "time_entries").first).to_contain_text(
            "Reproduced the failure"
        )


def test_another_tab_loads_its_table_and_counts_it(signed_in, desk):
    page = signed_in
    ticket = desk["login"]
    page.goto(f"/example/ticket/{ticket.pk}/")
    expect(related_rows(page, "time_entries")).to_have_count(3)
    comments = tab(page, "Comments")
    # What the page was rendered with...
    expect(comments.locator(".summary-tab__count")).to_have_text("2")

    # ...until the table itself says otherwise.
    TicketComment.objects.create(
        ticket=ticket,
        author="Lea Martin",
        body="The customer confirms.",
        position=3,
    )
    comments.click()

    expect(comments).to_have_attribute("aria-selected", "true")
    expect(related_rows(page, "comments")).to_have_count(3)
    expect(related_rows(page, "comments").last).to_contain_text(
        "The customer confirms."
    )
    expect(comments.locator(".summary-tab__count")).to_have_text("3")


def test_resolve_asks_for_the_resolution_then_moves_on(signed_in, desk):
    page = signed_in
    ticket = desk["login"]
    page.goto(f"/example/ticket/{ticket.pk}/")
    expect(transitions(page).get_by_role("button")).to_have_count(3)

    transitions(page).get_by_role("button", name="Resolve").click()

    dialog = page.get_by_role("dialog")
    expect(dialog.locator(".dialog__title")).to_have_text("Resolve")
    dialog.get_by_label("Resolution").fill("Reset links now last a day.")
    dialog.locator(".dialog__footer").get_by_role(
        "button", name="Resolve"
    ).click()

    expect(page.locator(".toast")).to_contain_text("Resolve: done.")
    status = page.locator(".summary-field").filter(
        has=page.locator("dt", has_text="Status")
    )
    expect(status.locator("dd")).to_contain_text("Resolved")
    # What a resolved ticket may do instead.
    expect(transitions(page).get_by_role("button")).to_have_count(2)
    expect(
        transitions(page).get_by_role("button", name="Reopen")
    ).to_be_visible()
    expect(
        transitions(page).get_by_role("button", name="Resolve")
    ).to_have_count(0)

    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.RESOLVED
    assert ticket.resolution == "Reset links now last a day."


def test_reopen_is_not_offered_without_its_permission(
    page, desk, worker, sign_in
):
    # A desk agent may change tickets, but not reopen one.
    sign_in(worker)
    resolved = desk["tickets"]["SD-1003"]
    assert resolved.status == Ticket.Status.RESOLVED

    page.goto(f"/example/ticket/{resolved.pk}/")

    expect(
        transitions(page).get_by_role("button", name="Close")
    ).to_be_visible()
    expect(
        transitions(page).get_by_role("button", name="Reopen")
    ).to_have_count(0)

"""The chart its reader draws above the list: the toolbar's Chart
button, the choices, what is remembered."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

LIST = "/example/ticket/"
TABLE = "document.getElementById('datatable').genericDataTable"


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)
    page.goto(LIST)
    expect(page.locator("#datatable tbody tr")).to_have_count(10)

    return page


def panel(page):
    return page.locator(".chart-builder")


def button(page):
    return page.locator(".dt-chart-toggle")


def title(page):
    return panel(page).locator(".chart-card__title span[x-text]")


def control(page, label):
    return panel(page).locator(".chart-builder__control", has_text=label)


def test_it_is_closed_until_opened(signed_in):
    page = signed_in

    expect(button(page)).to_have_attribute("aria-pressed", "false")
    expect(panel(page)).to_be_hidden()

    button(page).click()

    expect(panel(page)).to_be_visible()
    expect(button(page)).to_have_attribute("aria-pressed", "true")
    # The first choice field the model has: the priority.
    expect(title(page)).to_have_text("Number of tickets by priority")
    expect(panel(page).locator("canvas").first).to_be_visible()

    panel(page).get_by_title("Hide the chart").click()

    expect(panel(page)).to_be_hidden()
    expect(button(page)).to_have_attribute("aria-pressed", "false")


def test_the_reader_chooses_what_it_shows(signed_in):
    page = signed_in
    button(page).click()

    control(page, "Group by").locator("select").select_option("status")
    expect(title(page)).to_have_text("Number of tickets by status")

    control(page, "Split by").locator("select").select_option("priority")
    expect(title(page)).to_have_text(
        "Number of tickets by status and priority"
    )
    expect(panel(page).get_by_text("Stacked")).to_be_visible()

    # A donut has one series: no second field to choose.
    panel(page).get_by_role("button", name="Donut").click()
    expect(title(page)).to_have_text("Number of tickets by status")
    expect(control(page, "Split by")).to_be_hidden()


def test_it_is_remembered_and_saved_with_the_views(signed_in):
    page = signed_in
    button(page).click()
    control(page, "Group by").locator("select").select_option("status")
    panel(page).get_by_role("button", name="Donut").click()
    expect(title(page)).to_have_text("Number of tickets by status")

    page.reload()

    expect(panel(page)).to_be_visible()
    expect(title(page)).to_have_text("Number of tickets by status")

    state = page.evaluate(f"{TABLE}.captureState().chart")

    assert state["open"] is True
    assert state["type"] == "donut"
    assert state["group_by"] == "status"

    # A view saved with the chart closed closes it; one saved before
    # the chart existed leaves it alone; the reset closes it.
    page.evaluate(f"{TABLE}.applyState({{chart: {{open: false}}}})")
    expect(panel(page)).to_be_hidden()

    page.evaluate(
        f"{TABLE}.applyState({{chart: {{open: true, group_by: 'team'}}}})"
    )
    expect(title(page)).to_have_text("Number of tickets by team")

    page.evaluate(f"{TABLE}.applyState({{search: ''}})")
    expect(panel(page)).to_be_visible()

    page.evaluate(f"{TABLE}.resetLayout()")
    expect(panel(page)).to_be_hidden()


def pivot(page):
    return panel(page).locator(".pivot-table")


def open_pivot(page):
    button(page).click()
    panel(page).get_by_role("button", name="Table").click()
    control(page, "Split by").locator("select").select_option("team")
    expect(pivot(page).locator("thead")).to_contain_text("Front office")


def test_a_table_crosses_two_fields_with_totals(signed_in, desk):
    from example.models import Ticket

    page = signed_in
    open_pivot(page)

    expect(panel(page).locator("canvas").first).to_be_hidden()
    expect(pivot(page).locator("thead th").last).to_have_text("Total")
    # Every ticket of the list, in the bottom right corner.
    expect(pivot(page).locator(".pivot-table__all")).to_have_text(
        str(Ticket.objects.count())
    )


def test_a_figure_clicked_filters_the_table(signed_in, desk):
    from example.models import Ticket

    page = signed_in
    open_pivot(page)
    urgent = Ticket.objects.filter(priority="urgent")
    expected = urgent.filter(team__name="Front office").count()

    row = pivot(page).locator("tbody tr", has_text="Urgent")
    column = [
        (text or "").strip()
        for text in pivot(page).locator("thead th").all_text_contents()
    ].index("Front office")
    row.locator("td, th").nth(column).locator("button").click()

    expect(page.locator(".dt-chip")).to_have_count(2)
    expect(page.locator("#datatable tbody tr")).to_have_count(expected)


def test_the_table_downloads_as_csv(signed_in, desk):
    page = signed_in
    open_pivot(page)

    with page.expect_download() as caught:
        panel(page).get_by_title("Download as CSV").click()

    text = open(caught.value.path(), encoding="utf-8-sig").read()

    assert text.splitlines()[0].endswith(",Total")
    assert text.splitlines()[-1].startswith("Total,")

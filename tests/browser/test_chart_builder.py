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

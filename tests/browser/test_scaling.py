"""A laptop at 125% display scaling: the page still shows its content.

A 1920x1080 screen at the 125% Windows sets by default leaves the
browser about 1536x730 CSS pixels. Before, a list with charts showed
one row of its table above the fold there, and a record's summary spent
three lines on two buttons and its last change.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

LIST = "/example/ticket/"

SCALED = {"width": 1536, "height": 730}
FULL = {"width": 1920, "height": 950}


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


def has_class(name):
    return re.compile(rf"(^|\s){name}(\s|$)")


def open_list(page):
    page.goto(LIST)
    expect(page.locator("#datatable tbody tr")).to_have_count(10)
    expect(page.locator(".chart-grid .chart-card").first).to_be_visible()


def rows_in_view(page):
    height = page.viewport_size["height"]

    return sum(
        1
        for row in page.locator("#datatable tbody tr").all()
        if row.bounding_box()["y"] + row.bounding_box()["height"] <= height
    )


def test_a_list_shows_its_rows_under_its_charts(signed_in):
    page = signed_in
    page.set_viewport_size(SCALED)
    open_list(page)

    assert page.locator(".topbar").bounding_box()["height"] == 48
    for card in page.locator(".chart-grid .chart-card__body").all():
        # 28% of the window at most.
        assert card.bounding_box()["height"] <= 730 * 0.28 + 1

    assert rows_in_view(page) >= 3


def test_a_full_hd_window_keeps_its_spacing(signed_in):
    page = signed_in
    page.set_viewport_size(FULL)
    open_list(page)

    assert page.locator(".topbar").bounding_box()["height"] == 56


def test_a_folded_chart_stays_folded_and_unfolds(signed_in):
    page = signed_in
    page.set_viewport_size(SCALED)
    open_list(page)
    before = rows_in_view(page)

    for button in page.locator(".chart-card__fold").all():
        button.click()

    expect(page.locator(".chart-grid .chart-card.is-folded")).to_have_count(
        page.locator(".chart-grid .chart-card").count()
    )
    assert rows_in_view(page) > before

    # Remembered in this browser.
    page.reload()
    expect(page.locator("#datatable tbody tr")).to_have_count(10)
    card = page.locator(".chart-grid .chart-card").first
    expect(card).to_have_class(has_class("is-folded"))
    expect(card.locator(".chart-card__canvas")).to_be_hidden()

    # Opened again, it draws at its width.
    card.locator(".chart-card__fold").click()
    expect(card).not_to_have_class(has_class("is-folded"))
    expect(card.locator(".chart-card__canvas canvas")).to_be_visible()
    assert (
        card.locator(".chart-card__canvas canvas").bounding_box()["width"]
        > 200
    )


def test_a_records_buttons_and_last_change_share_a_line(signed_in, desk):
    page = signed_in
    page.set_viewport_size(SCALED)
    page.goto(f"/example/ticket/{desk['login'].pk}/")

    state = page.get_by_role("group", name="State")
    actions = page.get_by_role("group", name="Actions")
    expect(state).to_be_visible()
    expect(actions).to_be_visible()

    assert state.bounding_box()["y"] == pytest.approx(
        actions.bounding_box()["y"], abs=1
    )


def scale_display(page, factor, size=SCALED):
    """The window as Windows scaling draws it: CSS pixels, each worth
    ``factor`` screen pixels."""
    session = page.context.new_cdp_session(page)
    session.send(
        "Emulation.setDeviceMetricsOverride",
        {**size, "deviceScaleFactor": factor, "mobile": False},
    )


def root_font_size(page):
    return page.evaluate(
        "parseFloat(getComputedStyle(document.documentElement).fontSize)"
    )


@pytest.mark.parametrize("factor", [1.25, 1.5])
def test_a_scaled_laptop_draws_the_interface_a_tenth_smaller(
    signed_in, factor
):
    page = signed_in
    scale_display(page, factor)
    open_list(page)

    assert root_font_size(page) == pytest.approx(16 * 0.9)


@pytest.mark.parametrize("factor", [1, 2])
def test_plain_and_retina_screens_keep_the_browsers_size(signed_in, factor):
    page = signed_in
    scale_display(page, factor)
    open_list(page)

    assert root_font_size(page) == 16

"""Controls that stand side by side line up: edges, heights, tops.

Measured in the page, as the eye sees them: a box two pixels shorter
than its neighbour, or a card a step lower than the one beside it, is
what these tests catch.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

LIST = "/example/ticket/"


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


def box(locator):
    return locator.bounding_box()


def open_list(page):
    page.goto(LIST)
    expect(page.locator("#datatable tbody tr")).to_have_count(10)


def test_the_navigation_filter_shares_the_links_edges(signed_in):
    page = signed_in
    open_list(page)

    search = box(page.locator(".sidebar__search .input"))
    link = box(page.locator(".sidebar .nav-link").first)

    assert search["x"] == pytest.approx(link["x"], abs=0.5)
    assert search["x"] + search["width"] == pytest.approx(
        link["x"] + link["width"], abs=0.5
    )


def test_the_table_tools_are_one_height(signed_in):
    page = signed_in
    open_list(page)

    toolbar = page.locator(".dt-toolbar").first
    heights = {
        name: box(toolbar.locator(selector).first)["height"]
        for name, selector in (
            ("filter", ".dt-tool"),
            ("filter row", ".dt-filter-row-toggle"),
            ("reload", ".dt-toolbar__tools > .icon-button"),
        )
    }

    assert len({round(height) for height in heights.values()}) == 1, heights


def test_the_paging_buttons_are_as_tall_as_the_page_length(signed_in):
    page = signed_in
    open_list(page)

    length = box(page.locator(".dt-length select"))
    button = box(page.locator(".dt-paging button").first)

    assert button["height"] == pytest.approx(length["height"], abs=0.5)


def test_a_chart_period_picker_is_a_small_control(signed_in):
    page = signed_in
    open_list(page)

    period = page.locator(".chart-card__period").first
    expect(period).to_be_visible()
    tool = period.locator("xpath=..").locator(".icon-button").first

    assert box(period)["height"] == pytest.approx(30, abs=0.5)
    assert box(tool)["y"] + box(tool)["height"] / 2 == pytest.approx(
        box(period)["y"] + box(period)["height"] / 2, abs=0.5
    )


def test_cards_in_a_stack_take_only_its_gap(signed_in):
    page = signed_in
    page.goto("/account/")

    column = page.locator(".stack:has(> .card + .card)").first
    # The profile and preferences forms load their schema after the
    # page: measured before they are drawn, the first card grows
    # between one reading and the next.
    expect(column.locator(".js-schema-form .schema-form")).to_have_count(
        column.locator(".js-schema-form").count()
    )
    space, gap = page.evaluate(
        """el => {
            const [first, second] = el.querySelectorAll(":scope > .card");
            return [
                second.getBoundingClientRect().top
                    - first.getBoundingClientRect().bottom,
                parseFloat(getComputedStyle(el).rowGap),
            ];
        }""",
        column.element_handle(),
    )

    assert space == pytest.approx(gap, abs=0.5)

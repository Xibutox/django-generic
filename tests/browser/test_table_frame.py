"""A long table scrolls in a frame of the window's height.

Scrolled to, a list shows its toolbar, its column titles, its rows and
its paging together: the rows scroll inside their own box, the header
pinned at its top (table_frame.js, datatables.css, tree.css).
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

LIST = "/example/ticket/"

# A 1920x1080 laptop at 125%: the window the frame matters most in.
SCALED = {"width": 1536, "height": 730}

FRAME = "#datatable_wrapper .dt-layout-table > .dt-layout-cell"


@pytest.fixture
def long_list(page, desk, admin, sign_in):
    """The 25 tickets on one page: more rows than the window holds."""
    sign_in(admin)
    page.set_viewport_size(SCALED)
    page.goto(LIST)
    expect(page.locator("#datatable tbody tr")).to_have_count(10)
    page.locator("#datatable_wrapper .dt-length select").select_option("25")
    expect(page.locator("#datatable tbody tr")).to_have_count(25)

    return page


def frame_state(page):
    return page.locator(FRAME).evaluate("""frame => ({
            maxHeight: frame.style.maxHeight,
            scrolls: frame.scrollHeight > frame.clientHeight,
        })""")


def scroll_to_the_table(page):
    """The page scrolled so the table's card starts under the top bar."""
    page.evaluate("""() => {
            const card = document.querySelector("#datatable_wrapper")
                .closest(".module");
            const bar = document.querySelector(".topbar").offsetHeight;
            window.scrollTo(
                0, card.getBoundingClientRect().top + window.scrollY - bar
            );
        }""")


def test_the_rows_scroll_in_a_frame_of_the_window(long_list):
    page = long_list

    expect(page.locator(FRAME)).to_have_attribute(
        "style", re.compile(r"max-height: \d+px")
    )
    assert frame_state(page)["scrolls"]

    scroll_to_the_table(page)

    # Toolbar, titles, rows and paging: all in the window at once.
    for part in (
        ".dt-toolbar__search",
        "#datatable thead",
        "#datatable_wrapper .dt-paging",
    ):
        box = page.locator(part).first.bounding_box()
        assert box["y"] >= page.locator(".topbar").bounding_box()["height"]
        assert box["y"] + box["height"] <= SCALED["height"], part


def test_the_header_stays_at_the_top_of_the_frame(long_list):
    page = long_list
    scroll_to_the_table(page)
    titles = page.locator("#datatable thead tr.dt-column-titles")
    before = titles.bounding_box()["y"]

    page.locator(FRAME).evaluate("frame => { frame.scrollTop = 400; }")

    expect(page.locator("#datatable tbody tr").first).not_to_be_in_viewport()
    assert abs(titles.bounding_box()["y"] - before) <= 1
    # Drawn over the rows, not under them: what is at the header's
    # place is the header.
    box = titles.bounding_box()
    assert page.evaluate(
        "([x, y]) => !!document.elementFromPoint(x, y).closest('thead')",
        [box["x"] + 40, box["y"] + box["height"] / 2],
    )


def test_a_short_table_keeps_its_height(long_list):
    page = long_list

    page.locator(".dt-toolbar__search input").fill("invoice")
    expect(page.locator("#datatable tbody tr")).to_have_count(3)

    assert not frame_state(page)["scrolls"]


def test_a_frame_can_be_turned_off(long_list):
    page = long_list

    page.locator(FRAME).evaluate("""frame => {
            frame.dataset.tableFrame = "false";
            window.Generic.tableFrame.update();
        }""")

    expect(page.locator(FRAME)).not_to_have_attribute(
        "style", re.compile(r"max-height")
    )
    assert not frame_state(page)["scrolls"]

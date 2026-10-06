"""A tree unfolded a level at a time: a bill of materials."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from example.models import Article, BomLine


def row(page, text):
    return page.locator(".tree-row", has_text=text).first


def unfold(page, text):
    row(page, text).locator(".tree-row__toggle").click()


@pytest.fixture
def signed_in(page, bom, admin, sign_in):
    sign_in(admin)

    return page


@pytest.fixture
def terminals(bom):
    """An assembly of 120 parts: more than two pages of a level."""
    rail = Article.objects.create(
        reference="TS-1", name="Terminal rail", kind="assembly"
    )
    BomLine.objects.create(parent=bom["BK-1"], child=rail, position=30)
    BomLine.objects.bulk_create(
        BomLine(
            parent=rail,
            child=Article.objects.create(
                reference=f"TB-{index:03}", name="Terminal block"
            ),
            position=index,
        )
        for index in range(1, 121)
    )

    return rail


def test_levels_unfold_as_they_are_opened(signed_in, bom):
    page = signed_in
    page.goto("/example/article/bom/")

    expect(row(page, "BK-1 City bicycle")).to_be_visible()
    # Nothing below the roots until one is opened.
    expect(page.locator(".tree-row", has_text="WH-1")).to_have_count(0)

    unfold(page, "BK-1")
    unfold(page, "WH-1 Wheel")
    unfold(page, "HB-1 Hub")

    screw = page.locator(".tree-row", has_text="SC-1 Screw")
    # Three levels down under the hub, then under the bicycle itself.
    expect(screw).to_have_count(2)
    expect(screw.first).to_have_attribute("aria-level", "4")
    expect(screw.first).to_contain_text("4.000")
    expect(screw.last).to_have_attribute("aria-level", "2")

    unfold(page, "BK-1")
    expect(page.locator(".tree-row", has_text="HB-1")).to_have_count(0)


def test_a_large_level_comes_a_page_at_a_time_and_is_searched(
    signed_in, terminals
):
    page = signed_in
    page.goto("/example/article/bom/")
    unfold(page, "BK-1")
    unfold(page, "TS-1 Terminal rail")

    blocks = page.locator(".tree-row", has_text="Terminal block")
    expect(blocks).to_have_count(50)

    page.get_by_role("button", name="Show 50 more").click()
    expect(blocks).to_have_count(100)

    search = page.get_by_role("searchbox", name="Search this level")
    search.fill("TB-11")
    expect(blocks).to_have_count(10)
    # Typing goes on while the rows below are drawn again.
    expect(search).to_be_focused()
    expect(search).to_have_value("TB-11")


def test_the_summary_tabs_unfold_both_ways(signed_in, bom):
    page = signed_in
    page.goto(f"/example/article/{bom['HB-1'].pk}/")

    tree = page.locator('.generic-tree[data-tree="tree-bom"]')
    expect(tree.locator(".tree-row", has_text="SC-1 Screw")).to_be_visible()

    page.locator(".summary-tab", has_text="Where used").click()
    up = page.locator('.generic-tree[data-tree="tree-bom-up"]')
    expect(up.locator(".tree-row", has_text="WH-1 Wheel")).to_be_visible()
    up.locator(".tree-row", has_text="WH-1").locator(
        ".tree-row__toggle"
    ).click()
    expect(
        up.locator(".tree-row", has_text="BK-1 City bicycle")
    ).to_be_visible()


def test_the_keyboard_walks_the_tree(signed_in, bom):
    page = signed_in
    page.goto("/example/article/bom/")
    first = row(page, "BK-1 City bicycle")
    expect(first).to_be_visible()

    first.focus()
    page.keyboard.press("ArrowRight")
    expect(row(page, "WH-1 Wheel")).to_be_visible()
    page.keyboard.press("ArrowRight")
    expect(row(page, "WH-1 Wheel")).to_be_focused()
    page.keyboard.press("ArrowLeft")
    expect(first).to_be_focused()
    page.keyboard.press("ArrowLeft")
    expect(page.locator(".tree-row", has_text="WH-1")).to_have_count(0)

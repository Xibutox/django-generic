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


def test_found_at_any_depth_then_back(signed_in, terminals):
    page = signed_in
    page.goto("/example/article/bom/")
    expect(row(page, "BK-1 City bicycle")).to_be_visible()

    # The articles' own search box, above the tree.
    find = page.locator(".tree-filters").get_by_role("searchbox")
    find.fill("TB-119")
    find.press("Enter")

    # Unfolded down to it, through the 120 blocks of the rail.
    match = page.locator(".tree-row.is-match")
    expect(match).to_have_count(1)
    expect(match).to_contain_text("TB-119 Terminal block")
    expect(match).to_have_attribute("aria-level", "3")
    expect(page.locator(".tree__status")).to_contain_text("1 match")
    expect(
        page.locator(".tree-row--foot", has_text="119 more, not matching")
    ).to_be_visible()

    page.locator(".tree-row--foot", has_text="119 more").get_by_role(
        "button", name="Show them all"
    ).click()
    expect(page.locator(".tree-row", has_text="Terminal block")).to_have_count(
        50
    )

    find.fill("")
    find.press("Enter")
    expect(page.locator(".tree-row.is-match")).to_have_count(0)
    expect(row(page, "BK-1 City bicycle")).to_be_visible()
    expect(page.locator(".tree-row", has_text="WH-1")).to_have_count(0)


def test_the_exploded_bom(signed_in, bom):
    page = signed_in
    page.goto(f"/example/article/{bom['BK-1'].pk}/bom-flat/")

    table = page.locator('table[data-config="tree-flat-table"]')
    expect(table.locator("tbody tr")).to_have_count(5)
    expect(table.locator("tbody tr").nth(2)).to_contain_text("SC-1 Screw")
    expect(table.locator("tbody tr").nth(2)).to_contain_text("8.000")

    page.get_by_role("link", name="One row per record").click()
    expect(table.locator("tbody tr")).to_have_count(4)
    expect(table.locator("tbody tr", has_text="SC-1 Screw")).to_contain_text(
        "20"
    )


def test_the_articles_filters_search_the_tree(signed_in, bom):
    page = signed_in
    page.goto("/example/article/bom/")
    expect(row(page, "BK-1 City bicycle")).to_be_visible()

    search = page.locator(".tree-filters").get_by_role("searchbox")
    search.fill("kind:assembly")
    search.press("Enter")

    # A chip, as on the list: the tree shows every assembly, unfolded.
    expect(page.locator(".tree-filters .dt-filterbar")).to_contain_text(
        "Assembly"
    )
    matches = page.locator(".tree-row.is-match")
    expect(matches).to_have_count(2)
    expect(matches.first).to_contain_text("WH-1 Wheel")
    expect(matches.last).to_contain_text("HB-1 Hub")
    expect(page.locator(".tree__status")).to_contain_text("2 matches")


def test_a_tab_has_the_filters_too(signed_in, bom):
    page = signed_in
    page.goto(f"/example/article/{bom['WH-1'].pk}/")

    tab = page.locator("#related-tree-bom")
    expect(tab.locator(".tree-row", has_text="HB-1 Hub")).to_be_visible()

    search = tab.locator(".tree-filters").get_by_role("searchbox")
    search.fill("screw")
    search.press("Enter")

    expect(tab.locator(".tree-row.is-match")).to_contain_text("SC-1 Screw")
    expect(tab.locator(".tree-row", has_text="SP-1 Spoke")).to_have_count(0)

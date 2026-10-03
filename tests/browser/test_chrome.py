"""The frame around every page: palette, theme, language, navigation."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

LIST = "/example/ticket/"


def open_list(page):
    """The ticket list, once its scripts have drawn the rows."""
    page.goto(LIST)
    expect(page.locator("#datatable tbody tr")).to_have_count(10)


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


def test_the_palette_opens_a_ticket_by_its_reference(signed_in, desk):
    page = signed_in
    open_list(page)

    page.keyboard.press("Control+k")
    palette = page.locator(".palette__input")
    expect(palette).to_be_focused()
    palette.fill("SD-1007")
    expect(page.locator(".palette__item").first).to_contain_text(
        "SD-1007 - Mailbox full"
    )
    palette.press("Enter")

    ticket = desk["tickets"]["SD-1007"]
    expect(page).to_have_url(re.compile(rf"/example/ticket/{ticket.pk}/$"))
    expect(page.locator("h1")).to_have_text("SD-1007 - Mailbox full")


def test_the_dark_theme_is_chosen_and_kept(signed_in, admin):
    page = signed_in
    open_list(page)
    html = page.locator("html")
    expect(html).not_to_have_attribute("data-theme", "dark")

    page.get_by_role("button", name="Switch theme").click()
    with page.expect_response(
        lambda response: "/preferences/" in response.url
        and response.request.method == "PATCH"
    ):
        page.get_by_role("menuitemradio", name="Dark").click()

    expect(html).to_have_attribute("data-theme", "dark")
    admin.generic_preferences.refresh_from_db()
    assert admin.generic_preferences.theme == "dark"

    page.reload()

    expect(html).to_have_attribute("data-theme", "dark")


def test_french_from_the_account_menu_translates_the_navigation(signed_in):
    page = signed_in
    open_list(page)
    navigation = page.locator("#sidebar")
    expect(navigation.get_by_role("link", name="Dashboard")).to_be_visible()

    page.get_by_role("button", name="Account menu").click()
    page.locator('button[name="language"][value="fr"]').click()

    expect(page.locator("html")).to_have_attribute("lang", "fr")
    expect(
        navigation.get_by_role("link", name="Tableau de bord")
    ).to_be_visible()
    # The example's teams; the framework's own (generic.teams, installed
    # in the suite) are translated the same.
    expect(navigation.locator('a[href="/example/team/"]')).to_contain_text(
        "Équipes"
    )
    expect(
        navigation.locator('a[href="/generic_teams/team/"]')
    ).to_contain_text("Équipes")
    expect(navigation.get_by_role("link", name="Dashboard")).to_have_count(0)


def test_on_a_phone_the_navigation_opens_over_the_page_and_closes(
    signed_in,
):
    page = signed_in
    page.set_viewport_size({"width": 390, "height": 844})
    open_list(page)
    html = page.locator("html")
    navigation = page.locator("#sidebar")
    expect(navigation).to_be_hidden()

    page.locator(".topbar .js-sidebar-toggle").click()

    expect(html).to_have_class(re.compile(r"\bsidebar-open\b"))
    expect(navigation).to_be_visible()
    expect(navigation.get_by_role("link", name="Tickets")).to_be_visible()
    # Over the page, which a backdrop dims.
    backdrop = page.locator(".sidebar-backdrop")
    expect(backdrop).to_be_visible()

    # A tap beside the panel closes it.
    backdrop.click(position={"x": 370, "y": 600})

    expect(navigation).to_be_hidden()
    expect(html).not_to_have_class(re.compile(r"\bsidebar-open\b"))

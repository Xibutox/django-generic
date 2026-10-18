"""A board of tickets: a column per priority, a card per ticket."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from example.models import Ticket

PAGE = "/example/ticket/priorities/"


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


def column(page, key: str):
    return page.locator(f'.board-column[data-column="{key}"]')


def card(page, reference: str):
    return page.locator(".board-card-item", has_text=reference)


def test_each_ticket_sits_in_the_column_of_its_priority(signed_in, desk):
    page = signed_in
    page.goto(PAGE)

    for priority in ("low", "normal", "high", "urgent"):
        count = Ticket.objects.filter(priority=priority).count()
        expect(
            column(page, priority).locator(".board-card-item")
        ).to_have_count(count)
        expect(
            column(page, priority).locator(".board-column__count")
        ).to_have_text(str(count))

    login = Ticket.objects.get(reference="SD-1001")
    expect(column(page, login.priority)).to_contain_text("SD-1001")


def test_the_search_box_above_narrows_the_board(signed_in, desk):
    page = signed_in
    page.goto(PAGE)
    expect(page.locator(".board-card-item").first).to_be_visible()

    page.locator(".board-filters input[type=search]").fill("SD-1001")

    expect(page.locator(".board-card-item")).to_have_count(1)


def test_a_ticket_dragged_to_another_column_takes_its_priority(
    signed_in, desk
):
    page = signed_in
    login = Ticket.objects.get(reference="SD-1001")
    target = "urgent" if login.priority != "urgent" else "low"
    page.goto(PAGE)

    source = card(page, "SD-1001").locator(".board-card-item__label")
    start = source.bounding_box()
    box = column(page, target).bounding_box()
    x, y = start["x"] + 5, start["y"] + start["height"] / 2

    # A few pixels first, as a hand would: Chromium starts an HTML drag
    # from the element the mouse leaves, not from where it lands.
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 5, y + 5, steps=5)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 40, steps=10)
    page.mouse.up()

    expect(column(page, target)).to_contain_text("SD-1001")
    login.refresh_from_db()
    assert login.priority == target


def test_a_ticket_is_moved_from_the_keyboard_too(signed_in, desk):
    page = signed_in
    login = Ticket.objects.get(reference="SD-1001")
    target = "low" if login.priority != "low" else "high"
    page.goto(PAGE)

    menu = card(page, "SD-1001").get_by_role("combobox", name="Move SD-1001")
    menu.focus()
    menu.select_option(label=str(Ticket.Priority(target).label))

    expect(column(page, target)).to_contain_text("SD-1001")
    login.refresh_from_db()
    assert login.priority == target


def test_a_reader_sees_the_board_and_moves_nothing(
    page, desk, viewer, sign_in
):
    sign_in(viewer)
    page.goto(PAGE)

    expect(page.locator(".board-card-item").first).to_be_visible()
    expect(page.locator(".board-card-item[draggable=true]")).to_have_count(0)
    expect(page.locator(".board-card-item__move")).to_have_count(0)

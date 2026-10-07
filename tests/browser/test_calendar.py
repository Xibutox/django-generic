"""The dashboard's key figures and cards, and a calendar of tickets."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from example.models import Ticket


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


@pytest.fixture
def due(desk):
    """SD-1001 due today, SD-1002 tomorrow; the others not due."""
    today = timezone.localdate()
    Ticket.objects.filter(reference="SD-1001").update(due_on=today)
    Ticket.objects.filter(reference="SD-1002").update(
        due_on=today + datetime.timedelta(days=1)
    )

    return today


def day(page, when: datetime.date):
    return page.locator(f'.calendar-day[data-day="{when.isoformat()}"]')


def test_the_dashboard_fills_its_figures_and_cards(signed_in, desk):
    page = signed_in
    page.goto("/")

    still_open = Ticket.objects.filter(status__in=("open", "pending")).count()
    tile = page.locator('.kpi[data-kpi-url$="/kpis/open/"]')

    expect(tile.locator("[data-kpi-value]")).to_have_text(str(still_open))
    expect(
        page.locator(".record-card:not(.record-card--loading)").first
    ).to_be_visible()

    tile.click()
    page.wait_for_url("**/example/ticket/?filters=*")


def test_tickets_sit_on_their_due_day(signed_in, due):
    page = signed_in
    page.goto("/example/ticket/due/")

    expect(day(page, due).locator(".calendar-event")).to_contain_text(
        "SD-1001"
    )
    expect(
        day(page, due + datetime.timedelta(days=1)).locator(".calendar-event")
    ).to_contain_text("SD-1002")


def test_the_search_box_above_narrows_the_calendar(signed_in, due):
    page = signed_in
    page.goto("/example/ticket/due/?view=list")

    expect(page.locator(".calendar-list .calendar-event")).to_have_count(2)

    page.locator(".calendar-filters input[type=search]").fill("Login")

    expect(page.locator(".calendar-list .calendar-event")).to_have_count(1)
    expect(page.locator(".calendar-list")).to_contain_text("SD-1001")


def test_a_ticket_dragged_to_another_day_is_due_then(signed_in, due):
    page = signed_in
    page.goto("/example/ticket/due/")
    later = due + datetime.timedelta(days=2)

    chip = day(page, due).locator(".calendar-event", has_text="SD-1001")
    chip.drag_to(day(page, later))

    expect(day(page, later).locator(".calendar-event")).to_contain_text(
        "SD-1001"
    )
    assert Ticket.objects.get(reference="SD-1001").due_on == later

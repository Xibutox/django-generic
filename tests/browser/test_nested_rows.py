"""Records holding records: a row of an inline opened in its own window.

A supplier's form edits its equipment as rows; each piece of equipment
holds maintenance visits, edited on the equipment's own form. The icon
on a row opens that form in a popup window, so the supplier's form
keeps what is not saved yet.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from example.models import Equipment, Maintenance, Supplier


@pytest.fixture
def supplier(transactional_db):
    supplier = Supplier.objects.create(name="Pixel Works")
    Equipment.objects.create(
        name="ProArt 24", serial_number="EQ-1", supplier=supplier
    )

    return supplier


@pytest.fixture
def signed_in(page, admin, sign_in):
    sign_in(admin)

    return page


def row(page):
    return page.locator('[data-inline="equipment"] .inline-row').first


def cell(page, name):
    return row(page).locator(f'td[data-label="{name}"] input')


def test_a_row_is_edited_in_a_window_and_read_again(signed_in, supplier):
    page = signed_in
    page.goto(f"/example/supplier/{supplier.pk}/change/#tab-inline-equipment")

    # Changed here, not saved: the window must not lose it.
    cell(page, "Serial number").fill("EQ-1-B")

    with page.expect_popup() as opened:
        row(page).get_by_role("button", name="Open in a window").click()

    popup = opened.value
    popup.wait_for_load_state()
    popup.locator('.sf-field[data-field="name"] input').fill("ProArt 27")
    popup.get_by_role("tab", name="Maintenance visits").click()
    popup.get_by_role("button", name="Add another maintenance visit").click()
    popup.locator('[data-inline="maintenances"] .inline-row input').nth(
        1
    ).fill("Stand replaced")
    popup.get_by_role("button", name="Save", exact=True).click()
    popup.wait_for_event("close")

    expect(cell(page, "Name")).to_have_value("ProArt 27")
    expect(cell(page, "Serial number")).to_have_value("EQ-1-B")
    assert Maintenance.objects.filter(
        equipment__supplier=supplier, description="Stand replaced"
    ).exists()
    assert Equipment.objects.get(supplier=supplier).serial_number == "EQ-1"


def test_a_new_row_asks_to_save_first(signed_in, supplier):
    page = signed_in
    page.goto(f"/example/supplier/{supplier.pk}/change/#tab-inline-equipment")
    page.get_by_role("button", name="Add another equipment").click()
    new = page.locator('[data-inline="equipment"] .inline-row.is-new')
    new.locator('td[data-label="Name"] input').fill("Latitude 7440")
    new.locator('td[data-label="Serial number"] input').fill("EQ-2")

    new.get_by_role("button", name="Open in a window").click()
    page.get_by_role("dialog").get_by_role("button", name="Save").click()

    # Saved where it stands: the row has a record now, and opens.
    expect(
        page.locator('[data-inline="equipment"] .inline-row')
    ).to_have_count(2)
    expect(page.locator(".inline-row.is-new")).to_have_count(0)
    assert Equipment.objects.filter(serial_number="EQ-2").exists()

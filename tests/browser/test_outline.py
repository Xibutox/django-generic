"""A list's outline, and its Edit button, in the browser.

The suppliers' list unfolds into their equipment, and each piece of
equipment into its maintenance visits (``auto(Supplier, ...,
outline=("equipment", "maintenances"))``); the list itself has an
*Edit* button turning it into a grid.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from example.models import Equipment, Maintenance, Supplier

pytestmark = pytest.mark.browser

LIST = "/example/supplier/"


@pytest.fixture
def stock(transactional_db):
    acme = Supplier.objects.create(name="Acme", country="France")
    Supplier.objects.create(name="Bolt", country="Spain")
    laptop = Equipment.objects.create(
        name="Laptop", serial_number="L-1", supplier=acme
    )
    Equipment.objects.create(name="Screen", serial_number="S-1", supplier=acme)
    Maintenance.objects.create(equipment=laptop, description="Battery")

    return {"acme": acme, "laptop": laptop}


def rows(page, depth):
    return page.locator(f"tr.outline-row[data-depth='{depth}']")


def unfold(page, depth, text):
    row = rows(page, depth).filter(has_text=text)
    row.locator(".tree-row__toggle").click()

    return row


def test_the_list_unfolds_level_after_level(page, admin, sign_in, stock):
    sign_in(admin)
    page.goto(LIST)

    page.locator(".dt-outline-toggle").click()

    # The table's rows make way for the outline.
    expect(page.locator(".dt-outline")).to_be_visible()
    expect(page.locator("#datatable")).to_be_hidden()
    expect(rows(page, 0)).to_have_count(2)

    unfold(page, 0, "Acme")
    expect(rows(page, 1)).to_have_count(2)
    expect(page.locator(".outline-head").first).to_contain_text("Equipment")

    unfold(page, 1, "L-1")
    expect(rows(page, 2)).to_contain_text("Battery")
    expect(page.locator(".tree-row--foot").first).to_contain_text(
        "Add maintenance visit"
    )

    # The table's search narrows the first level.
    page.locator(".dt-toolbar__search input").fill("bolt")
    expect(rows(page, 0)).to_have_count(1)
    expect(rows(page, 0)).to_contain_text("Bolt")

    # Remembered, and back to the table.
    page.reload()
    expect(page.locator(".dt-outline")).to_be_visible()
    page.locator(".dt-outline-toggle").click()
    expect(page.locator("#datatable")).to_be_visible()


def test_a_cell_is_written_where_it_stands(
    page, admin, sign_in, stock, console
):
    # The refused serial number below is a 400, on purpose.
    console.allow(400, "/api/example/equipment/")
    sign_in(admin)
    page.goto(LIST + "?outline=1")

    unfold(page, 0, "Acme")
    page.locator(".dt-outline-edit").click()

    # The level in the name's order: the laptop first.
    laptop = rows(page, 1).first
    laptop.locator("select").first.select_option("other")

    expect(laptop.locator("td.is-saving")).to_have_count(0)
    page.wait_for_function(
        "() => !document.querySelector('.outline-table td.is-saving')"
    )
    expect(laptop.locator("td.is-invalid")).to_have_count(0)
    page.wait_for_timeout(300)
    assert Equipment.objects.get(pk=stock["laptop"].pk).kind == "other"

    # Refused: said under the cell, nothing written.
    serial = laptop.locator("input.input").nth(1)
    expect(serial).to_have_value("L-1")
    serial.fill("")
    serial.press("Enter")
    expect(laptop.locator(".cell-editor__error")).to_be_visible()
    assert Equipment.objects.get(pk=stock["laptop"].pk).serial_number == "L-1"

    # Back to reading: the values, not the controls.
    page.locator(".dt-outline-edit").click()
    expect(laptop.locator("select")).to_have_count(0)
    expect(laptop).to_contain_text("Other")


def test_a_reader_reads(page, viewer, sign_in, stock):
    sign_in(viewer)
    page.goto(LIST + "?outline=1")

    unfold(page, 0, "Acme")
    expect(rows(page, 1)).to_have_count(2)
    expect(page.locator(".dt-outline-edit")).to_have_count(0)
    expect(page.locator(".dt-edit-toggle")).to_have_count(0)


def test_the_edit_button_turns_the_list_into_a_grid(
    page, admin, sign_in, stock
):
    sign_in(admin)
    page.goto(LIST)

    page.locator(".dt-edit-toggle").click()
    page.wait_for_url("**edit=1**")

    acme = page.locator("#datatable tbody tr").first
    country = acme.locator("input.input").nth(4)
    expect(country).to_have_value("France")
    country.fill("Italy")
    country.press("Enter")
    page.wait_for_timeout(500)
    page.wait_for_function(
        "() => !document.querySelector('#datatable td.is-saving')"
    )
    assert Supplier.objects.get(name="Acme").country == "Italy"

    page.locator(".dt-edit-toggle").click()
    page.wait_for_url(lambda url: "edit=1" not in url)
    expect(page.locator("#datatable input.input")).to_have_count(0)

"""*Add* buttons opening the form in a dialog, in the browser.

The example's equipment has ``add_in_dialog``: a supplier's Equipment
tab and the suppliers' outline add a piece over the page, which reads
its rows again once it is saved.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from example.models import Equipment, Maintenance, Supplier

pytestmark = pytest.mark.browser


@pytest.fixture
def stock(transactional_db):
    acme = Supplier.objects.create(name="Acme", country="France")
    laptop = Equipment.objects.create(
        name="Laptop", serial_number="L-1", supplier=acme
    )
    Equipment.objects.create(name="Screen", serial_number="S-1", supplier=acme)
    Maintenance.objects.create(equipment=laptop, description="Battery")

    return {"acme": acme}


def rows(page, depth):
    return page.locator(f"tr.outline-row[data-depth='{depth}']")


def unfold(page, depth, text):
    row = rows(page, depth).filter(has_text=text)
    row.locator(".tree-row__toggle").click()

    return row


def fill_and_save(page, name, serial):
    dialog = page.locator("dialog.dialog--frame")
    expect(dialog).to_be_visible()
    form = page.frame_locator("dialog.dialog--frame iframe")
    form.get_by_role("textbox", name="Name", exact=True).fill(name)
    form.get_by_role("textbox", name="Serial number", exact=True).fill(serial)
    form.get_by_role("button", name="Create", exact=True).click()
    expect(dialog).to_have_count(0)


def test_an_outline_level_adds_in_a_dialog(page, admin, sign_in, stock):
    sign_in(admin)
    page.goto("/example/supplier/?outline=1")

    acme = unfold(page, 0, "Acme")
    unfold(page, 1, "L-1")
    expect(rows(page, 2)).to_contain_text("Battery")

    foot = page.locator(".tree-row--foot[data-depth='1']")
    foot.get_by_role("link", name="Add equipment").click()
    fill_and_save(page, "Dock", "D-1")

    # The supplier read again: the new piece, its count, and what was
    # open below it still open.
    expect(rows(page, 1)).to_have_count(3)
    expect(rows(page, 1).filter(has_text="D-1")).to_be_visible()
    expect(acme.locator(".tree-row__count")).to_have_text("3")
    expect(rows(page, 2)).to_contain_text("Battery")
    expect(page).to_have_url(r"/example/supplier/?outline=1")
    assert Equipment.objects.get(serial_number="D-1").supplier == stock["acme"]


def test_a_related_table_adds_in_a_dialog(page, admin, sign_in, stock):
    sign_in(admin)
    page.goto(f"/example/supplier/{stock['acme'].pk}/")
    page.get_by_role("tab", name="Equipment").click()

    panel = page.locator("#related-equipment")
    expect(panel.locator("tbody tr")).to_have_count(2)
    panel.get_by_role("link", name="Add", exact=True).click()
    fill_and_save(page, "Dock", "D-1")

    expect(panel.locator("tbody tr")).to_have_count(3)
    expect(panel).to_contain_text("D-1")
    expect(page).to_have_url(f"/example/supplier/{stock['acme'].pk}/")


def test_a_modifier_click_still_opens_the_page(page, admin, sign_in, stock):
    sign_in(admin)
    page.goto("/example/equipment/")

    add = page.locator(".toolbar a[data-record-dialog]").first
    expect(add).to_have_attribute("data-record-dialog", "Add Equipment")

    with page.context.expect_page() as opened:
        add.click(modifiers=["ControlOrMeta"])

    expect(page.locator("dialog.dialog--frame")).to_have_count(0)
    assert "/example/equipment/add/" in opened.value.url

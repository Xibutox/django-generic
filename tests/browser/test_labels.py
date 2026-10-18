"""Labels: ticked on the list, printed from their sheet."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from example.models import Equipment, Supplier

pytestmark = pytest.mark.browser

LIST = "/example/equipment/"


@pytest.fixture
def devices(desk):
    supplier = Supplier.objects.create(name="Nordic Devices")

    return [
        Equipment.objects.create(
            name=f"Device {index}",
            serial_number=f"EQ-{index}",
            kind=Equipment.Kind.LAPTOP,
            supplier=supplier,
        )
        for index in range(3)
    ]


def test_the_ticked_rows_are_printed_with_their_codes(
    page, devices, admin, sign_in
):
    sign_in(admin)
    page.goto(LIST)

    for device in devices[:2]:
        page.locator("#datatable tbody tr", has_text=device.name).locator(
            ".dt-row-check"
        ).check()

    bar = page.locator(".dt-selection-bar")
    bar.locator(".dt-selection-bar__action").select_option("print_labels")
    bar.get_by_role("button", name="Apply").click()

    page.wait_for_url("**/example/equipment/labels/?ids=*")
    labels = page.locator(".print-label")
    expect(labels).to_have_count(2)
    expect(labels.first.locator("svg.print-label__code")).to_be_visible()
    expect(labels.first).to_contain_text("EQ-0")

    # Print opens the browser's dialog: counted, not opened.
    page.evaluate("window.print = () => { window.printed = true; }")
    page.get_by_role("button", name="Print").click()
    assert page.evaluate("window.printed") is True


def test_on_paper_only_the_labels_remain(page, devices, admin, sign_in):
    sign_in(admin)
    page.goto(f"/example/equipment/{devices[0].pk}/label/")
    page.emulate_media(media="print")

    expect(page.locator(".print-label")).to_have_count(1)
    expect(page.locator(".sidebar")).to_be_hidden()
    expect(page.locator(".topbar")).to_be_hidden()
    expect(page.get_by_role("button", name="Print")).to_be_hidden()

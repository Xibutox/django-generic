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


def test_a_records_tab_unfolds_too(page, admin, sign_in, stock):
    sign_in(admin)
    page.goto(f"{LIST}{stock['acme'].pk}/")

    # The supplier's equipment tab: its rows, then their visits.
    panel = page.locator("#related-equipment")
    panel.locator(".dt-outline-toggle").click()

    expect(panel.locator(".dt-outline")).to_be_visible()
    expect(rows(panel, 0)).to_have_count(2)
    unfold(panel, 0, "L-1")
    expect(rows(panel, 1)).to_contain_text("Battery")

    # The page's address is the record's, not the tab's.
    assert "outline=" not in page.url


def comment_rows(page):
    return rows(page, 1)


def author_of(row):
    return row.locator("input").first


def test_comments_are_written_moved_and_opened_in_a_dialog(
    page, admin, sign_in, desk
):
    from example.models import TicketComment

    sign_in(admin)
    page.goto("/example/ticket/?outline=1")
    unfold(page, 0, "SD-1001")
    expect(comment_rows(page)).to_have_count(2)
    page.locator(".dt-outline-edit").click()

    # A long text, in its control.
    first = comment_rows(page).first
    body = first.locator("textarea")
    expect(body).to_have_value("Reproduced on staging.")
    body.fill("Reproduced on staging, twice.")
    body.press("Tab")
    page.wait_for_function(
        "() => !document.querySelector('.outline-table td.is-saving')"
    )
    page.wait_for_timeout(300)
    assert TicketComment.objects.filter(
        body="Reproduced on staging, twice."
    ).exists()

    def order():
        return list(
            TicketComment.objects.filter(
                ticket__reference="SD-1001"
            ).values_list("author", flat=True)
        )

    # Dragged by its handle below the other one.
    second = comment_rows(page).nth(1)
    height = second.bounding_box()["height"]
    first.locator(".outline-row__handle").drag_to(
        second, target_position={"x": 40, "y": height - 6}
    )
    expect(author_of(comment_rows(page).first)).to_have_value("Yanis Bertrand")
    assert order() == ["Yanis Bertrand", "Camille Rousseau"]

    # And back, with the keyboard.
    comment_rows(page).nth(1).focus()
    page.keyboard.press("Alt+ArrowUp")
    expect(author_of(comment_rows(page).first)).to_have_value(
        "Camille Rousseau"
    )
    assert order() == ["Camille Rousseau", "Yanis Bertrand"]

    # Its link opens its whole form over the outline.
    comment_rows(page).first.locator(".outline-row__open").click()
    dialog = page.locator("dialog.dialog--frame")
    expect(dialog).to_be_visible()
    form = page.frame_locator("dialog.dialog--frame iframe")
    author = form.locator("input[name='author'], [data-field='author'] input")
    expect(author.first).to_have_value("Camille Rousseau")
    author.first.fill("Camille R.")
    form.get_by_role("button", name="Save", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(author_of(comment_rows(page).first)).to_have_value("Camille R.")
    assert order()[0] == "Camille R."


def test_a_long_text_is_as_tall_as_it_needs(page, admin, sign_in, desk):
    sign_in(admin)
    page.goto("/example/ticket/?outline=1")
    unfold(page, 0, "SD-1001")
    page.locator(".dt-outline-edit").click()

    body = comment_rows(page).first.locator("textarea")
    expect(body).to_be_visible()

    def lines():
        return body.evaluate(
            "(area) => Math.round((area.clientHeight"
            " - parseFloat(getComputedStyle(area).paddingTop)"
            " - parseFloat(getComputedStyle(area).paddingBottom))"
            " / parseFloat(getComputedStyle(area).lineHeight))"
        )

    # One line written, one more to write on.
    assert lines() == 2

    body.fill("")
    assert lines() == 1

    body.fill("First\nSecond")
    assert lines() == 3


def test_the_rows_alternate_their_colour(page, admin, sign_in, desk):
    sign_in(admin)
    page.goto("/example/ticket/?outline=1")
    unfold(page, 0, "SD-1001")

    striped = page.locator("tr.outline-row.is-stripe")
    expect(striped.first).to_be_attached()
    stripes = page.evaluate(
        "() => Array.from(document.querySelectorAll("
        "'.outline-table tr.tree-row:not(.tree-row--foot)"
        ":not(.tree-row--head)')).map("
        "(row) => row.classList.contains('is-stripe'))"
    )
    assert stripes[:2] == [False, True]
    assert all(a != b for a, b in zip(stripes, stripes[1:]))


def test_a_refused_frame_opens_a_window(
    page, admin, sign_in, desk, monkeypatch, console
):
    """A server or a proxy refusing to be framed, whatever we say."""
    from generic.sites.views import ResourceFormView

    dispatch = ResourceFormView.dispatch

    def refusing(self, request, *args, **kwargs):
        response = dispatch(self, request, *args, **kwargs)
        response["X-Frame-Options"] = "DENY"
        response["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response

    monkeypatch.setattr(ResourceFormView, "dispatch", refusing)
    sign_in(admin)
    page.goto("/example/ticket/?outline=1")
    unfold(page, 0, "SD-1001")
    page.locator(".dt-outline-edit").click()

    with page.expect_popup() as opened:
        comment_rows(page).first.locator(".outline-row__open").click()

    window = opened.value
    expect(page.locator("dialog.dialog--frame")).to_have_count(0)
    author = window.get_by_role("textbox", name="Author", exact=True)
    expect(author).to_have_value("Camille Rousseau")
    author.fill("Camille W.")
    window.get_by_role("button", name="Save", exact=True).click()

    # The window closes itself and the outline shows the change.
    expect(author_of(comment_rows(page).first)).to_have_value("Camille W.")

    # The browser's word on the refused frame is the one error expected.
    console.errors[:] = [
        error for error in console.errors if "frame-ancestors" not in error
    ]

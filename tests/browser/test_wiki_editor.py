"""The wiki's editor: text colour, tables, and tables pasted from
elsewhere."""

from __future__ import annotations

import io

import pytest
from django.core.files.base import ContentFile
from PIL import Image
from playwright.sync_api import expect

from generic.wiki.models import WikiImage, WikiPage

#: A selection copied from Excel: a header merged across two columns
#: twice, a name merged down two rows, an empty cell, Excel's own
#: attributes and comments.
EXCEL = """
<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head>
<style><!-- .xl65 {font-weight:700;} --></style></head><body>
<table border=0 cellpadding=0 cellspacing=0 width=320>
<!--StartFragment-->
 <col width=80 span=4>
 <tr><td colspan=2 class=xl65>Quarter 1</td><td colspan=2>Quarter 2</td></tr>
 <tr><td>Jan</td><td>Feb</td><td>Apr</td><td>May</td></tr>
 <tr><td rowspan=2>Team A</td><td x:num>12</td><td></td><td x:num>9</td></tr>
 <tr><td x:num>7</td><td x:num>3</td><td>&nbsp;</td></tr>
<!--EndFragment-->
</table></body></html>
"""

#: A table copied from Word: headers, paragraphs and a list in cells.
WORD = """
<p class=MsoNormal>Intro</p>
<table class=MsoTableGrid><thead><tr><th><p><b>Name</b></p></th>
<th><p>Role</p></th></tr></thead>
<tbody><tr><td><p>Ada</p><p>Lovelace</p></td>
<td><ul><li>Lead</li><li>Admin</li></ul></td></tr></tbody></table>
"""

PASTE = """([html, text]) => {
  const data = new DataTransfer();
  data.setData("text/html", html);
  data.setData("text/plain", text);
  document.querySelector("#wiki-editor .ql-editor").dispatchEvent(
    new ClipboardEvent("paste", {
      clipboardData: data, bubbles: true, cancelable: true
    })
  );
}"""

ROWS = """table => Array.from(table.rows).map(
  row => Array.from(row.cells).map(cell => cell.textContent.trim())
)"""


@pytest.fixture
def handbook(transactional_db):
    return WikiPage.objects.create(
        title="Handbook",
        slug="handbook",
        content="<p>How the desk works.</p>",
    )


def edit(page):
    page.goto("/wiki/handbook/")
    page.get_by_role("button", name="Edit").click()
    editor = page.locator("#wiki-editor .ql-editor")
    expect(editor).to_contain_text("How the desk works.")
    editor.click()
    page.keyboard.press("Control+End")

    return editor


def save(page):
    page.locator(".wiki__editor-actions").get_by_role(
        "button", name="Save"
    ).click()
    expect(page.locator(".toast")).to_contain_text("The page was saved.")


def test_a_colour_is_kept_on_the_page(page, handbook, admin, sign_in):
    sign_in(admin)
    edit(page)
    page.keyboard.press("Shift+Home")
    page.locator(".ql-picker.ql-color .ql-picker-label").click()
    page.locator('.ql-picker.ql-color [data-value="red"]').click()
    save(page)

    expect(page.locator(".wiki-content .ql-color-red")).to_have_text(
        "How the desk works."
    )
    handbook.refresh_from_db()
    assert 'class="ql-color-red"' in handbook.content


def test_a_table_is_inserted_and_grown(page, handbook, admin, sign_in):
    sign_in(admin)
    editor = edit(page)
    page.keyboard.press("Control+Alt+t")
    page.keyboard.type("A1")
    page.locator(".ql-picker.ql-tableEdit .ql-picker-label").click()
    page.locator('.ql-picker.ql-tableEdit [data-value="columnRight"]').click()

    table = editor.locator("table")
    expect(table).to_have_count(1)
    assert [len(row) for row in table.evaluate(ROWS)] == [4, 4, 4]

    # Inside a table, the shortcut adds no other.
    page.keyboard.press("Control+Alt+t")
    expect(table).to_have_count(1)
    save(page)

    rows = page.locator(".wiki-content table").evaluate(ROWS)
    assert rows[0][0] == "A1"
    assert [len(row) for row in rows] == [4, 4, 4]


def test_merged_cells_pasted_from_excel_stay_in_their_columns(
    page, handbook, admin, sign_in
):
    sign_in(admin)
    editor = edit(page)
    page.evaluate(PASTE, [EXCEL, "Quarter 1\tQuarter 2"])

    expect(editor.locator("table")).to_have_count(1)
    expected = [
        ["Quarter 1", "", "Quarter 2", ""],
        ["Jan", "Feb", "Apr", "May"],
        ["Team A", "12", "", "9"],
        ["", "7", "3", ""],
    ]
    assert editor.locator("table").evaluate(ROWS) == expected
    # The text before the table keeps its line.
    expect(editor.locator("p").first).to_have_text("How the desk works.")
    save(page)

    assert page.locator(".wiki-content table").evaluate(ROWS) == expected


def test_a_table_from_word_stays_one_table(page, handbook, admin, sign_in):
    sign_in(admin)
    editor = edit(page)
    page.keyboard.press("Enter")
    page.evaluate(PASTE, [WORD, "Name\tRole"])

    expect(editor.locator("table")).to_have_count(1)
    assert editor.locator("table").evaluate(ROWS) == [
        ["Name", "Role"],
        ["Ada Lovelace", "Lead Admin"],
    ]
    expect(editor.locator("table strong")).to_have_text("Name")


def test_one_cell_from_a_spreadsheet_is_its_text(
    page, handbook, admin, sign_in
):
    sign_in(admin)
    editor = edit(page)
    page.evaluate(PASTE, ["<table><tr><td x:num>42</td></tr></table>", "42"])

    expect(editor.locator("table")).to_have_count(0)
    expect(editor).to_contain_text("How the desk works.42")


def test_a_table_pasted_in_a_table_is_its_text(page, handbook, admin, sign_in):
    sign_in(admin)
    editor = edit(page)
    page.keyboard.press("Control+Alt+t")
    page.evaluate(PASTE, [EXCEL, "Quarter 1\tQuarter 2\nJan\tFeb"])

    expect(editor.locator("table")).to_have_count(1)
    first = editor.locator("table td").first
    expect(first).to_have_text("Quarter 1 Quarter 2 Jan Feb")


@pytest.fixture
def illustrated(transactional_db, settings, tmp_path):
    """The handbook with an image, then a paragraph to run beside it."""
    settings.MEDIA_ROOT = str(tmp_path)
    buffer = io.BytesIO()
    Image.new("RGB", (240, 160), (40, 120, 200)).save(buffer, "PNG")
    image = WikiImage(original_name="chart.png")
    image.file.save("chart.png", ContentFile(buffer.getvalue()), save=False)
    image.save()

    return WikiPage.objects.create(
        title="Handbook",
        slug="handbook",
        content=(
            "<p>How the desk works.</p>"
            f'<p><img src="{image.get_absolute_url()}"></p>'
            "<p>" + "Text that runs beside the image. " * 10 + "</p>"
        ),
    )


def test_an_image_put_to_the_left_has_the_text_beside_it(
    page, illustrated, admin, sign_in
):
    sign_in(admin)
    page.goto("/wiki/handbook/")
    page.get_by_role("button", name="Edit").click()
    editor = page.locator("#wiki-editor .ql-editor")
    editor.locator("img").click()
    page.locator(".ql-picker.ql-imageFloat .ql-picker-label").click()
    page.locator('.ql-picker.ql-imageFloat [data-value="left"]').click()
    expect(editor.locator("img")).to_have_class("wiki-float-left")
    save(page)

    image = page.locator(".wiki-content img")
    expect(image).to_have_class("wiki-float-left")
    assert image.evaluate("img => getComputedStyle(img).float") == "left"
    illustrated.refresh_from_db()
    assert 'class="wiki-float-left"' in illustrated.content


def test_a_size_and_a_title_from_the_style_menus(
    page, handbook, admin, sign_in
):
    sign_in(admin)
    edit(page)
    page.keyboard.press("Shift+Home")
    page.locator(".ql-picker.ql-size .ql-picker-label").click()
    page.locator(
        '.ql-picker.ql-size .ql-picker-item[data-value="large"]'
    ).click()
    page.locator(".ql-picker.ql-header .ql-picker-label").click()
    page.locator(
        '.ql-picker.ql-header .ql-picker-item[data-value="1"]'
    ).click()
    save(page)

    expect(page.locator(".wiki-content h1 .ql-size-large")).to_have_text(
        "How the desk works."
    )

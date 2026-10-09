"""The wiki's editor: text colour, tables, and tables pasted from
elsewhere."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from generic.wiki.models import WikiPage

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

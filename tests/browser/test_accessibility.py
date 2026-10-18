"""Accessibility: the example's pages checked by axe-core, WCAG 2.1 AA.

axe-core (Deque, MPL-2.0) is vendored for the tests only, in
``vendor/axe.min.js``: no CDN, nothing shipped with the package. It is
evaluated in the page through Playwright, which the page's own
Content-Security-Policy does not apply to, then asked for what breaks
WCAG 2.1 level A and AA: a field without a name, text too pale on its
background, an ARIA role in the wrong place.

A page is checked once its scripts have drawn it - the table's rows,
the form's fields, the calendar's days - in the light theme and the
dark one. A new page type gets a line in ``PAGES``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import expect

AXE = (Path(__file__).parent / "vendor" / "axe.min.js").read_text("utf-8")

#: What is checked: WCAG 2.0 and 2.1, levels A and AA.
STANDARD = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

#: Each page, and what shows it is drawn.
PAGES = [
    ("/", "main"),
    ("/account/", "main form"),
    ("/example/ticket/", "#datatable tbody tr"),
    ("/example/ticket/add/", "form .select2-container"),
    ("/example/ticket/{ticket}/", "main h1"),
    ("/example/ticket/{ticket}/change/", "form .select2-container"),
    ("/example/ticket/{ticket}/delete/", "main form"),
    ("/example/ticket/due/", ".calendar-day"),
    ("/example/ticket/due/?view=list", "main"),
    ("/example/ticket/import/", "main"),
    ("/example/triage/", "main table tbody tr"),
    ("/example/customer/", "#datatable tbody tr"),
    ("/example/team/", "#datatable tbody tr"),
    ("/example/article/", "main"),
    ("/example/article/bom/", "main"),
    ("/generic_teams/team/", "main"),
    ("/wiki/handbook/", "main"),
    ("/wiki/", "main"),
]

#: Tag colours a record may hold: the usual palette, and the extremes.
TAG_COLORS = [
    "#ef4444",
    "#f97316",
    "#f59e0b",
    "#eab308",
    "#84cc16",
    "#22c55e",
    "#14b8a6",
    "#06b6d4",
    "#3b82f6",
    "#6366f1",
    "#a855f7",
    "#ec4899",
    "#78716c",
    "#ffff00",
    "#00ffff",
    "#ffffff",
    "#000000",
]


def violations(page, rules: list[str] | None = None) -> list[dict]:
    """What axe-core finds wrong with the page as it stands."""
    if not page.evaluate("typeof window.axe !== 'undefined'"):
        page.evaluate(AXE)

    options = (
        {"runOnly": {"type": "rule", "values": rules}}
        if rules
        else {"runOnly": {"type": "tag", "values": STANDARD}}
    )

    return page.evaluate(
        """async (options) => {
          const result = await window.axe.run(document, options);

          return result.violations.map((violation) => ({
            id: violation.id,
            impact: violation.impact,
            help: violation.help,
            nodes: violation.nodes.slice(0, 5).map((node) => ({
              target: node.target.join(" "),
              summary: node.failureSummary,
            })),
          }));
        }""",
        options,
    )


def report(found: list[dict]) -> str:
    lines = []

    for violation in found:
        lines.append(
            f"{violation['id']} ({violation['impact']}): {violation['help']}"
        )

        for node in violation["nodes"]:
            summary = " ".join(node["summary"].split())
            lines.append(f"    {node['target']}: {summary}")

    return "\n".join(lines)


def assert_accessible(page, rules: list[str] | None = None) -> None:
    found = violations(page, rules)

    assert not found, f"{page.url}\n{report(found)}"


def use_theme(page, theme: str) -> None:
    """The scheme the browser asks for: the pages follow it (the
    reader's theme is *system*), drawn in it from the start - switching
    afterwards would check colours halfway through their transition."""
    page.emulate_media(color_scheme=theme)


@pytest.fixture
def signed_in(page, desk, admin, sign_in):
    sign_in(admin)

    return page


@pytest.fixture(autouse=True)
def handbook(transactional_db):
    """A wiki page, for the wiki's pages to show."""
    from generic.wiki.models import WikiPage

    return WikiPage.objects.create(
        title="Handbook",
        slug="handbook",
        content="<h2>Tickets</h2><p>How the desk works.</p>",
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("path, drawn", PAGES)
def test_the_page_meets_wcag_aa(signed_in, desk, theme, path, drawn):
    page = signed_in
    ticket = desk["tickets"]["SD-1007"]

    use_theme(page, theme)
    page.goto(path.format(ticket=ticket.pk))
    expect(page.locator(drawn).first).to_be_visible()
    page.wait_for_load_state("networkidle")

    assert_accessible(page)


def test_the_sign_in_page_meets_wcag_aa(page, live_server):
    page.goto("/login/")
    page.get_by_text("Sign in with a password instead").click()
    expect(page.get_by_label("Password")).to_be_visible()

    assert_accessible(page)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_a_tag_of_any_colour_is_readable(signed_in, theme):
    """A tag's colour is the record's: white, black or yellow, its text
    still reads on its background (``--tag-ink``)."""
    page = signed_in
    use_theme(page, theme)
    page.goto("/example/team/")
    expect(page.locator("#datatable tbody tr").first).to_be_visible()
    page.evaluate(
        """(colors) => {
          const box = document.createElement("div");

          box.className = "tag-list";
          box.style.background = "var(--surface-raised)";
          colors.forEach((color) => {
            const tag = document.createElement("span");

            tag.className = "tag";
            tag.textContent = "Tag " + color;
            tag.style.setProperty("--tag-color", color);
            box.appendChild(tag);
          });
          document.querySelector("main").appendChild(box);
        }""",
        TAG_COLORS,
    )

    assert_accessible(page, rules=["color-contrast"])

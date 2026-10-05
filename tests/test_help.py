"""The help page, the licence it shows, and the changelog it reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from generic.help.changelog import parse, read
from generic.help.sources import changelogs, licence

pytestmark = pytest.mark.django_db

HELP = "/help/"
CHANGES = "/help/changes/"

SAMPLE = """# Changelog

Everything before the first release is the preamble.

## [1.1.0] - 2026-09-18

A note about this release.

### Added
- A row of search fields under the column headers, open by
  default and hidden by the button beside Filter.
- Another thing.

### Fixed
- A date column drawn as a link filtered as text.

## 1.0.0 - 2026-01-05

### Added
- The first release.
"""


class TestReadingAChangelog:
    def test_releases_come_out_in_the_order_written(self):
        releases = parse(SAMPLE)

        assert [release.version for release in releases] == ["1.1.0", "1.0.0"]
        assert releases[0].date == "2026-09-18"

    def test_sections_keep_their_items(self):
        added, fixed = parse(SAMPLE)[0].sections

        assert added.name == "Added"
        assert len(added.items) == 2
        assert fixed.items == [
            "A date column drawn as a link filtered as text."
        ]

    def test_an_item_wrapped_over_two_lines_stays_one_item(self):
        # Written at 72 columns like the rest of the repository; showing
        # the second half as a paragraph scattered the sentence.
        first = parse(SAMPLE)[0].sections[0].items[0]

        assert first == (
            "A row of search fields under the column headers, open by "
            "default and hidden by the button beside Filter."
        )

    def test_a_paragraph_stays_with_its_release(self):
        assert parse(SAMPLE)[0].notes == ["A note about this release."]

    def test_a_paragraph_wrapped_over_lines_stays_one(self):
        # A release's introduction, wrapped at the file's width, was
        # drawn one line per paragraph.
        notes = parse(
            "## 1.0.0\n\nThe first release: an admin-like\n"
            "framework for Django.\n\nA second paragraph.\n"
        )[0].notes

        assert notes == [
            "The first release: an admin-like framework for Django.",
            "A second paragraph.",
        ]

    def test_code_in_a_line_is_drawn_as_code_and_nothing_else(self):
        from generic.templatetags.generic_ui import inline_code

        assert inline_code("Declare `auto(Book)` <b>now</b>") == (
            "Declare <code>auto(Book)</code> &lt;b&gt;now&lt;/b&gt;"
        )
        # A backquote cannot smuggle markup in: its content is escaped.
        assert inline_code("`<script>`") == "<code>&lt;script&gt;</code>"

    def test_the_preamble_belongs_to_no_release(self):
        assert all(
            "preamble" not in note
            for release in parse(SAMPLE)
            for note in release.notes
        )

    def test_a_heading_without_brackets_is_read_too(self):
        assert parse(SAMPLE)[1].version == "1.0.0"

    def test_unreleased_is_marked_as_such(self):
        releases = parse("## [Unreleased]\n\n### Added\n- Soon.\n")

        assert releases[0].is_unreleased is True
        assert parse(SAMPLE)[0].is_unreleased is False

    def test_a_file_that_is_not_there_is_not_an_error(self, tmp_path):
        assert read(tmp_path / "nothing.md") == []

    def test_a_file_too_large_to_be_a_changelog_is_refused(self, tmp_path):
        path = tmp_path / "CHANGELOG.md"
        path.write_text("## [1.0.0]\n- x\n" + "x" * 600_000, encoding="utf-8")

        assert read(path) == []


class TestWhatTheProjectShows:
    def test_the_repositorys_changelog_is_found_without_declaring_it(self):
        sources = changelogs()

        assert sources
        assert sources[0].releases

    def test_the_licence_is_read_from_the_project(self):
        found = licence()

        assert found["name"] == "LICENSE"
        assert "BSD 3-Clause License" in found["text"]

    def test_a_declared_licence_wins(self, settings, tmp_path):
        path = tmp_path / "OTHER"
        path.write_text("Public domain.", encoding="utf-8")
        settings.GENERIC = {"LICENSE_FILE": str(path)}

        assert licence()["text"] == "Public domain."

    def test_without_a_file_the_setting_answers(self, settings, tmp_path):
        settings.GENERIC = {
            "LICENSE_FILE": str(tmp_path / "missing"),
            "LICENSE_TEXT": "Ask the vendor.",
        }

        assert licence() == {"name": "", "text": "Ask the vendor."}

    def test_declared_changelogs_replace_the_search(self, settings, tmp_path):
        path = tmp_path / "CHANGELOG.md"
        path.write_text(SAMPLE, encoding="utf-8")
        settings.GENERIC = {"CHANGELOG_FILES": [("Desk", str(path))]}

        sources = changelogs()

        assert [source.label for source in sources] == ["Desk"]
        assert sources[0].releases[0].version == "1.1.0"


class TestThePages:
    def test_the_help_page_shows_the_version_and_the_licence(
        self,
        auth_client,
        settings,
    ):
        settings.GENERIC = {"VERSION": "1.2.3"}

        response = auth_client.get(HELP)
        rendered = response.content.decode()

        assert response.status_code == 200
        assert response.context["version"] == "1.2.3"
        assert "BSD 3-Clause License" in rendered

    def test_the_help_page_shows_the_newest_release(self, auth_client):
        release = auth_client.get(HELP).context["latest_release"]

        assert release["version"]
        assert release["sections"]

    def test_the_changelog_page_lists_every_source(self, auth_client):
        sources = auth_client.get(CHANGES).context["sources"]

        assert sources
        assert sources[0]["releases"][0]["version"]

    def test_both_pages_need_a_signed_in_user(self, client):
        assert client.get(HELP).status_code in (302, 403)
        assert client.get(CHANGES).status_code in (302, 403)

    def test_the_account_menu_offers_them(self, auth_client):
        rendered = auth_client.get("/account/").content.decode()

        assert HELP in rendered
        assert CHANGES in rendered


class TestTheFrame:
    def test_the_application_name_is_in_the_top_bar(self, auth_client):
        rendered = auth_client.get("/account/").content.decode()

        assert "topbar__brand" in rendered
        assert "topbar__title" in rendered

    def test_the_top_bar_offers_the_pin(self, auth_client):
        """The pin sits in the bar, not inside the navigation.

        Floating, the navigation is parked off screen - a pin that
        travelled with it could only be reached once it was already
        open, which is not when it is wanted.
        """
        rendered = auth_client.get("/account/").content.decode()
        bar = rendered.split('<div class="topbar__start">')[1]

        assert "js-sidebar-pin" in bar.split("</header>")[0]
        # And the strip along the edge that brings the panel back.
        assert "js-sidebar-edge" in rendered

    def test_the_pin_carries_both_of_its_labels(self, auth_client):
        """The label names the click, so the server sends both of them.

        Only the page knows which state it is in - it is remembered in
        the browser - so the script swaps between these two rather than
        holding a translated string of its own.
        """
        rendered = auth_client.get("/account/").content.decode()

        assert 'data-label-pin="Keep the navigation open"' in rendered
        assert (
            'data-label-unpin="Let the navigation float over the page"'
            in rendered
        )

    def test_the_version_reaches_the_frame(self, auth_client, settings):
        settings.GENERIC = {"VERSION": "1.2.3"}

        response = auth_client.get("/account/")

        assert response.context["chrome"]["version"] == "1.2.3"

    def test_no_socket_where_nothing_could_answer(
        self, auth_client, monkeypatch
    ):
        """Installed without the ``events`` extra, the pages are not told
        of a socket nobody serves."""
        import importlib

        # The module, not the ``site`` instance generic.sites exports
        # under the same name.
        module = importlib.import_module("generic.sites.site")

        monkeypatch.setattr(module, "events_installed", lambda: False)
        chrome = auth_client.get("/account/").context["chrome"]

        assert chrome["client"]["websocketUrl"] == ""

        monkeypatch.setattr(module, "events_installed", lambda: True)
        chrome = auth_client.get("/account/").context["chrome"]

        assert chrome["client"]["websocketUrl"] == "/ws/events/"


def test_the_repository_ships_a_changelog():
    """The help page has something to read in a fresh checkout."""
    root = Path(__file__).resolve().parent.parent

    assert (root / "CHANGELOG.md").is_file()
    assert (root / "LICENSE").is_file()


def test_the_package_ships_its_own_changelog():
    """Installed from a wheel, the framework has no repository around
    it: its changelog lives in the package, where the page looks."""
    from generic import __version__
    from generic.help.changelog import read
    from generic.help.sources import framework_root

    releases = read(framework_root() / "CHANGELOG.md")

    assert framework_root().name == "generic"
    # The version the package says it is, released.
    assert releases[0].version == __version__
    assert not releases[0].is_unreleased


def test_the_example_is_released_with_the_framework():
    """The example ships with each release of the framework, and says
    so in three places the framework's version does not reach: the
    navigation's footer and the Help page, its API description, and its
    own changelog. They stayed at 1.0.0 through 1.1.0, 1.2.0 and 1.3.0, their
    changes piled under Unreleased. Unreleased entries may wait on top
    of it between releases; the newest release must be this one."""
    from example_project.settings import base
    from generic import __version__

    releases = read(Path(__file__).resolve().parent.parent / "CHANGELOG.md")
    released = [release for release in releases if not release.is_unreleased]

    assert base.GENERIC["VERSION"] == __version__
    assert base.SPECTACULAR_SETTINGS["VERSION"] == __version__
    assert released[0].version == __version__

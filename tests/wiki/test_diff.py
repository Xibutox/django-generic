"""What changed between two versions of a page."""

from __future__ import annotations

import pytest

from generic.wiki.diff import diff, lines_of, words
from generic.wiki.models import Wiki, WikiPage
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PAGES = "/wiki/api/pages/"


def send(client, method: str, url: str, data=None):
    return getattr(client, method)(url, data, content_type="application/json")


class TestLines:
    def test_each_block_is_a_line(self):
        html = (
            "<h1>Title</h1><p>One <strong>bold</strong> word.</p>"
            "<ul><li>First</li><li>Second</li></ul>"
            "<p>Line<br>break</p><hr><p></p>"
        )

        assert lines_of(html) == [
            "Title",
            "One bold word.",
            "First",
            "Second",
            "Line",
            "break",
            "---",
        ]

    def test_a_table_row_is_one_line(self):
        html = "<table><tbody><tr><td>A</td><td>B</td></tr></tbody></table>"

        assert lines_of(html) == ["A | B"]

    def test_an_image_is_named(self):
        assert lines_of('<p><img src="/wiki/images/7/" alt="Plan"></p>') == [
            "[Plan]"
        ]
        assert lines_of('<p><img src="/wiki/images/7/"></p>') == ["[7]"]

    def test_nothing_is_no_line(self):
        assert lines_of(None) == []
        assert lines_of("") == []


class TestDiff:
    def test_lines_put_in_and_taken_out(self):
        result = diff("<p>A</p><p>B</p>", "<p>A</p><p>C</p><p>D</p>")

        assert result["lines"] == [
            {"op": "equal", "text": "A"},
            {"op": "delete", "text": "B"},
            {"op": "insert", "text": "C"},
            {"op": "insert", "text": "D"},
        ]
        assert (result["added"], result["removed"]) == (2, 1)

    def test_a_rewritten_line_says_which_words(self):
        result = diff("<p>The quick fox</p>", "<p>The slow fox</p>")

        assert result["lines"] == [
            {
                "op": "change",
                "parts": [
                    {"op": "equal", "text": "The "},
                    {"op": "delete", "text": "quick"},
                    {"op": "insert", "text": "slow"},
                    {"op": "equal", "text": " fox"},
                ],
            }
        ]

    def test_words_join_their_runs(self):
        assert words("a b", "a b c d") == [
            {"op": "equal", "text": "a b"},
            {"op": "insert", "text": " c d"},
        ]

    def test_long_unchanged_runs_are_folded(self):
        same = "".join(f"<p>Line {index}</p>" for index in range(20))

        result = diff(same + "<p>Old</p>", same + "<p>New</p>")

        assert result["lines"][0] == {"op": "skip", "count": 18}
        assert [line["op"] for line in result["lines"]] == [
            "skip",
            "equal",
            "equal",
            "change",
        ]

    def test_the_same_text_is_all_equal(self):
        result = diff("<p>A</p>", "<p>A</p>")

        assert (result["added"], result["removed"]) == (0, 0)


class TestEndpoint:
    @pytest.fixture
    def page(self, admin_client):
        page = WikiPage.objects.create(
            wiki=Wiki.objects.default(),
            title="Rules",
            slug="rules",
            content="<p>One</p>",
        )

        for text in ("<p>Two</p>", "<p>Three</p>"):
            send(
                admin_client, "patch", f"{PAGES}{page.pk}/", {"content": text}
            )

        return page

    def test_from_a_version_to_the_page(self, admin_client, page):
        oldest = page.revisions.last()

        data = send(
            admin_client, "get", f"{PAGES}{page.pk}/diff/?from={oldest.pk}"
        ).json()

        assert data["lines"] == [
            {
                "op": "change",
                "parts": [
                    {"op": "delete", "text": "One"},
                    {"op": "insert", "text": "Three"},
                ],
            }
        ]
        assert data["before"]["id"] == oldest.pk
        assert data["after"]["id"] is None
        assert data["version"]

    def test_what_a_version_changed(self, admin_client, page):
        newest, oldest = page.revisions.all()

        changed = send(
            admin_client, "get", f"{PAGES}{page.pk}/diff/?to={newest.pk}"
        ).json()
        first = send(
            admin_client, "get", f"{PAGES}{page.pk}/diff/?to={oldest.pk}"
        ).json()

        assert changed["before"]["id"] == oldest.pk
        assert changed["lines"][0]["parts"][1] == {
            "op": "insert",
            "text": "Two",
        }
        # The first version: everything was written then.
        assert first["lines"] == [{"op": "insert", "text": "One"}]

    def test_without_a_version_the_last_change(self, admin_client, page):
        data = send(admin_client, "get", f"{PAGES}{page.pk}/diff/").json()

        assert data["before"]["id"] == page.revisions.first().pk
        assert data["lines"][0]["parts"] == [
            {"op": "delete", "text": "Two"},
            {"op": "insert", "text": "Three"},
        ]

    def test_to_a_text_sent_changing_nothing(self, client, page):
        # A reader may ask: nothing is written.
        client.force_login(UserFactory())

        response = send(
            client,
            "post",
            f"{PAGES}{page.pk}/diff/",
            {"content": "<p>Three</p><p onclick='x()'>Mine</p>"},
        )

        page.refresh_from_db()
        assert response.status_code == 200
        assert response.json()["lines"] == [
            {"op": "equal", "text": "Three"},
            {"op": "insert", "text": "Mine"},
        ]
        assert page.content == "<p>Three</p>"

    @pytest.mark.parametrize("query", ["?from=x", "?from=987654", "?to=0"])
    def test_an_unknown_version_is_not_found(self, admin_client, page, query):
        assert (
            send(
                admin_client, "get", f"{PAGES}{page.pk}/diff/{query}"
            ).status_code
            == 404
        )

    def test_another_page_s_version_is_not_found(self, admin_client, page):
        other = WikiPage.objects.create(
            wiki=page.wiki, title="Other", slug="other"
        )

        assert (
            send(
                admin_client,
                "get",
                f"{PAGES}{other.pk}/diff/?from={page.revisions.first().pk}",
            ).status_code
            == 404
        )

    def test_a_conflict_names_who_saved(self, admin_client, page):
        response = send(
            admin_client,
            "patch",
            f"{PAGES}{page.pk}/",
            {"content": "<p>Mine</p>", "version": "2000-01-01T00:00:00"},
        )

        assert response.status_code == 409
        assert "changed this page" in response.json()["detail"]

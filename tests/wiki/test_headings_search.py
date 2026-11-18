"""A page's headings as anchors and contents; the pages found by their
words, with an excerpt."""

from __future__ import annotations

import pytest

from generic.wiki.headings import table_of_contents, with_anchors
from generic.wiki.models import Wiki, WikiMember, WikiPage
from generic.wiki.search import excerpt, fold, search_pages_of
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class TestAnchors:
    def test_each_heading_gets_an_anchor_from_its_text(self):
        html, contents = with_anchors(
            '<h2>Escalating a ticket</h2><p>x</p><h3 class="ql-align-center">'
            "Who to <strong>call</strong></h3>"
        )

        assert '<h2 id="h-escalating-a-ticket">' in html
        assert '<h3 id="h-who-to-call" class="ql-align-center">' in html
        assert contents == [
            {
                "id": "h-escalating-a-ticket",
                "text": "Escalating a ticket",
                "level": 2,
            },
            {"id": "h-who-to-call", "text": "Who to call", "level": 3},
        ]

    def test_two_headings_alike_get_two_anchors(self):
        _html, contents = with_anchors("<h2>Steps</h2><h2>Steps</h2>")

        assert [entry["id"] for entry in contents] == ["h-steps", "h-steps-2"]

    def test_an_empty_heading_is_left_alone(self):
        html, contents = with_anchors("<h2> </h2>")

        assert html == "<h2> </h2>"
        assert contents == []

    def test_the_cleaning_still_drops_a_pasted_id(self):
        page = WikiPage.objects.create(
            title="Ids", slug="ids", content='<h2 id="main">Taken</h2>'
        )

        assert 'id="main"' not in page.content

    def test_a_short_page_has_no_contents(self):
        _html, contents = with_anchors("<h2>A</h2><h2>B</h2>")

        assert table_of_contents(contents) == []

    def test_contents_are_indented_under_the_highest_level(self):
        _html, contents = with_anchors("<h2>A</h2><h3>B</h3><h2>C</h2>")

        assert [entry["depth"] for entry in table_of_contents(contents)] == [
            0,
            1,
            0,
        ]

    def test_the_page_shows_them(self, admin_client):
        WikiPage.objects.create(
            wiki=Wiki.objects.get(slug="main"),
            title="Long",
            slug="long",
            content="<h2>One</h2><p>a</p><h2>Two</h2><h3>Three</h3>",
        )

        response = admin_client.get("/wiki/main/long/")

        assert b'<h2 id="h-one">One</h2>' in response.content
        assert b'href="#h-three"' in response.content
        assert len(response.context["contents"]) == 3


class TestText:
    def test_a_page_keeps_its_words(self):
        page = WikiPage.objects.create(
            title="T",
            slug="t",
            content="<p>One <strong>bold</strong> word.</p><p>Next</p>",
        )

        assert page.text == "One bold word.\nNext"

    def test_a_save_of_the_content_alone_writes_its_words(self):
        page = WikiPage.objects.create(title="T", slug="t", content="<p>a</p>")
        page.content = "<p>b</p>"
        page.save(update_fields=["content"])

        page.refresh_from_db()
        assert page.text == "b"


class TestExcerpt:
    def test_the_words_found_are_marked(self):
        runs = excerpt("Call the duty manager first.", ["duty"])

        assert runs == [
            ("Call the ", False),
            ("duty", True),
            (" manager first.", False),
        ]

    def test_accents_are_set_aside(self):
        assert fold("Élodie") == "elodie"
        assert ("Été", True) in excerpt("En Été, rien.", ["ete"])

    def test_a_long_text_is_cut_around_the_word(self):
        text = "word " * 100 + "target " + "word " * 100

        runs = excerpt(text, ["target"])

        assert runs[0] == ("… ", False)
        assert runs[-1] == (" …", False)
        assert ("target", True) in runs
        assert sum(len(piece) for piece, _hit in runs) < 220

    def test_a_title_match_shows_the_start(self):
        runs = excerpt("Nothing here matches.", ["absent"])

        assert runs == [("Nothing here matches.", False)]


class TestSearch:
    @pytest.fixture
    def pages(self):
        main = Wiki.objects.get(slug="main")
        other = Wiki.objects.create(name="Other", slug="other")
        secret = Wiki.objects.create(
            name="Secret", slug="secret", access="private"
        )

        return {
            "body": WikiPage.objects.create(
                wiki=main,
                title="Duty",
                slug="duty",
                content="<p>Escalate to the <strong>manager</strong>.</p>",
            ),
            "title": WikiPage.objects.create(
                wiki=other, title="Escalate", slug="escalate"
            ),
            "hidden": WikiPage.objects.create(
                wiki=secret, title="Escalate in secret", slug="s"
            ),
            "secret": secret,
            "other": other,
        }

    def test_the_html_is_not_searched(self, pages, admin_user):
        assert search_pages_of(admin_user, "strong") == []

    def test_every_word_must_be_there(self, pages, admin_user):
        found = search_pages_of(admin_user, "escalate manager")

        assert [entry["page"].slug for entry in found] == ["duty"]

    def test_a_title_match_comes_first(self, pages, admin_user):
        found = search_pages_of(admin_user, "escalate")

        assert [entry["page"].slug for entry in found][-1] == "duty"

    def test_a_wiki_not_read_is_not_searched(self, pages):
        reader = UserFactory()

        found = search_pages_of(reader, "escalate")

        assert "s" not in [entry["page"].slug for entry in found]

        WikiMember.objects.create(wiki=pages["secret"], user=reader)

        found = search_pages_of(reader, "escalate")

        assert "s" in [entry["page"].slug for entry in found]

    def test_one_wiki_only(self, pages, admin_user):
        found = search_pages_of(admin_user, "escalate", wiki=pages["other"])

        assert [entry["page"].slug for entry in found] == ["escalate"]

    def test_a_page_in_the_trash_is_not_found(self, pages, admin_user):
        WikiPage.objects.filter(slug="duty").update(
            deleted_at="2026-01-01T00:00:00Z"
        )

        assert search_pages_of(admin_user, "manager") == []

    def test_the_results_page(self, pages, admin_client):
        response = admin_client.get("/wiki/?q=manager")

        assert response.status_code == 200
        assert response.context["term"] == "manager"
        assert b"<mark>manager</mark>" in response.content

    def test_the_results_page_in_one_wiki(self, pages, admin_client):
        response = admin_client.get("/wiki/?q=escalate&wiki=other")

        assert response.context["scope"] == pages["other"]
        assert [
            entry["page"].slug for entry in response.context["results"]
        ] == ["escalate"]

    def test_a_reader_of_one_wiki_is_not_sent_into_it(self, client):
        # A lone wiki opens straight - but not when searching.
        client.force_login(UserFactory())

        assert client.get("/wiki/?q=x").status_code == 200

    def test_what_a_page_holds_is_escaped(self, admin_client):
        WikiPage.objects.create(
            wiki=Wiki.objects.get(slug="main"),
            title="Code",
            slug="code",
            content="<pre>&lt;script&gt;alert(1)&lt;/script&gt;</pre>",
        )

        response = admin_client.get("/wiki/?q=alert")

        assert b"<script>alert(1)" not in response.content
        assert b"&lt;script&gt;" in response.content

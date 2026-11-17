"""Markdown in and out, a page as a PDF, templates, the history's size."""

from __future__ import annotations

from unittest import mock

import pytest

from generic.wiki import pdf
from generic.wiki.markdown import from_markdown, to_markdown
from generic.wiki.models import Wiki, WikiMember, WikiPage, WikiRevision
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PAGES = "/wiki/api/pages/"


def send(client, method: str, url: str, data=None):
    return getattr(client, method)(url, data, content_type="application/json")


@pytest.fixture
def wiki():
    return Wiki.objects.create(name="Team", slug="team")


@pytest.fixture
def page(wiki):
    return WikiPage.objects.create(
        wiki=wiki,
        title="Plan",
        slug="plan",
        content=(
            "<h2>Steps</h2><ol><li>One</li><li>Two<ul><li>Two a</li></ul>"
            '</li></ol><p>See <a href="/wiki/team/x/">x</a> and '
            "<strong>this</strong>.</p><pre>a &lt; b\n  c</pre>"
            "<table><tr><th>A</th><th>B</th></tr>"
            "<tr><td>1</td><td>2</td></tr></table>"
        ),
    )


class TestToMarkdown:
    def test_the_editor_s_blocks(self, page):
        text = to_markdown(page.content, page.title)

        assert text.startswith("# Plan\n\n## Steps\n\n1. One\n2. Two\n")
        assert "   - Two a" in text
        assert "See [x](/wiki/team/x/) and **this**." in text
        assert "```\na < b\n  c\n```" in text
        assert "| A | B |\n| --- | --- |\n| 1 | 2 |" in text

    def test_text_never_reads_as_html(self):
        assert to_markdown("<p>&lt;script&gt;</p>") == "&lt;script>\n"

    def test_downloaded(self, admin_client, page):
        response = admin_client.get("/wiki/team/plan/export.md")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/markdown")
        assert 'filename="plan.md"' in response["Content-Disposition"]
        assert response.content.decode().startswith("# Plan")

    def test_not_from_a_wiki_one_cannot_read(self, client, wiki, page):
        wiki.access = "private"
        wiki.save()
        client.force_login(UserFactory())

        response = client.get("/wiki/team/plan/export.md")

        assert response.status_code == 404


class TestFromMarkdown:
    def test_the_first_heading_is_the_title(self):
        title, html = from_markdown("# Hello\n\nWorld *now*.")

        assert title == "Hello"
        assert html == "<p>World <em>now</em>.</p>"

    def test_blocks(self):
        _title, html = from_markdown(
            "## Two\n\n- a\n- b\n  - c\n\n1. x\n\n> q\n\n```\n<b>\n```"
            "\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n---"
        )

        assert "<h2>Two</h2>" in html
        assert "<ul><li>a</li><li>b<ul><li>c</li></ul></li></ul>" in html
        assert "<ol><li>x</li></ol>" in html
        assert "<blockquote><p>q</p></blockquote>" in html
        assert "<pre>&lt;b&gt;</pre>" in html
        assert "<th>A</th>" in html and "<td>2</td>" in html
        assert html.endswith("<hr>")

    def test_html_in_the_file_stays_text(self):
        _title, html = from_markdown("<script>alert(1)</script>")

        assert "<script>" not in html

    def test_a_javascript_link_is_cleaned_once_saved(self, wiki):
        _title, html = from_markdown("[x](javascript:alert(1))")
        page = WikiPage.objects.create(wiki=wiki, title="X", content=html)

        assert "javascript" not in page.content

    def test_imported_as_a_page(self, admin_client, wiki):
        response = send(
            admin_client,
            "post",
            f"{PAGES}import/",
            {"markdown": "# Notes\n\nHi.", "name": "x.md", "wiki": wiki.pk},
        )

        assert response.status_code == 201
        page = WikiPage.objects.get(pk=response.json()["id"])
        assert (page.wiki, page.title, page.content) == (
            wiki,
            "Notes",
            "<p>Hi.</p>",
        )

    def test_titled_by_its_file_without_a_heading(self, admin_client, wiki):
        response = send(
            admin_client,
            "post",
            f"{PAGES}import/",
            {"markdown": "Hi.", "name": "team-notes.md", "wiki": wiki.pk},
        )

        assert response.json()["title"] == "team notes"

    def test_empty_is_refused(self, admin_client, wiki):
        response = send(
            admin_client,
            "post",
            f"{PAGES}import/",
            {"markdown": " ", "wiki": wiki.pk},
        )

        assert response.status_code == 400

    def test_only_where_one_adds_pages(self, client, wiki):
        wiki.access = "private"
        wiki.save()
        reader = UserFactory()
        WikiMember.objects.create(wiki=wiki, user=reader, role="reader")
        client.force_login(reader)

        response = send(
            client,
            "post",
            f"{PAGES}import/",
            {"markdown": "Hi.", "wiki": wiki.pk},
        )

        assert response.status_code == 403
        assert not WikiPage.objects.filter(wiki=wiki).exists()


class TestPagePdf:
    def test_the_page_alone(self, admin_client, page):
        with mock.patch.object(
            pdf, "render", return_value=b"%PDF-1.4"
        ) as render:
            response = admin_client.get("/wiki/team/plan/export.pdf")

        assert response.status_code == 200
        assert 'filename="plan.pdf"' in response["Content-Disposition"]
        assert render.call_args.kwargs["page"] == page

    def test_written(self, wiki, page):
        content = pdf.render(wiki, page=page)

        assert content.startswith(b"%PDF")

    def test_a_page_of_another_wiki_is_not_found(self, admin_client, page):
        Wiki.objects.create(name="Other", slug="other")

        response = admin_client.get("/wiki/other/plan/export.pdf")

        assert response.status_code == 404


class TestTemplates:
    def test_offered_to_a_new_page_of_its_wiki(self, admin_client, page):
        page.is_template = True
        page.save()
        other = Wiki.objects.create(name="Other", slug="other")
        WikiPage.objects.create(
            wiki=other, title="Elsewhere", slug="e", is_template=True
        )

        config = admin_client.get("/wiki/team/plan/").context["wiki_config"]

        assert config["templates"] == [{"id": page.pk, "title": "Plan"}]

    def test_set_from_the_editor(self, admin_client, page):
        send(
            admin_client, "patch", f"{PAGES}{page.pk}/", {"is_template": True}
        )

        page.refresh_from_db()
        assert page.is_template


class TestHistorySize:
    def test_a_setting(self, settings, page):
        settings.GENERIC = {**settings.GENERIC, "WIKI_MAX_REVISIONS": 3}

        for index in range(6):
            page.content = f"<p>{index}</p>"
            WikiRevision.keep(page)

        assert page.revisions.count() == 3

    def test_none_keeps_every_version(self, settings, page):
        settings.GENERIC = {**settings.GENERIC, "WIKI_MAX_REVISIONS": None}

        for index in range(60):
            page.content = f"<p>{index}</p>"
            WikiRevision.keep(page)

        assert page.revisions.count() == 60

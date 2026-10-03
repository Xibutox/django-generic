"""A wiki as a PDF: its pages in the menu's order, its images drawn,
its files named, nothing fetched."""

from __future__ import annotations

import io

import pytest
from django.core.files.base import ContentFile
from PIL import Image

from generic.wiki import pdf
from generic.wiki.models import Wiki, WikiFile, WikiImage, WikiPage

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)

    return tmp_path


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), (40, 120, 200)).save(buffer, "PNG")

    return buffer.getvalue()


@pytest.fixture
def handbook() -> dict:
    wiki = Wiki.objects.create(
        name="Qualité — procédures",
        slug="quality",
        description="Les procédures “à jour”.",
    )
    image = WikiImage(original_name="chart.png")
    image.file.save("chart.png", ContentFile(png()), save=False)
    image.save()
    attachment = WikiFile(original_name="plan.pdf", size=2048)
    attachment.file.save("plan.pdf", ContentFile(b"%PDF-1.4"), save=False)
    attachment.save()
    second = WikiPage.objects.create(
        wiki=wiki, title="Second", slug="second", position=2
    )
    first = WikiPage.objects.create(
        wiki=wiki,
        title="First",
        slug="first",
        position=1,
        content=(
            '<h2 class="ql-align-center">Hello</h2>'
            '<p>See <a href="/wiki/quality/second/">the next one</a>.</p>'
            f'<p><img src="{image.get_absolute_url()}"></p>'
            '<p><img src="https://elsewhere.test/x.png" alt="far"></p>'
            f'<p class="wiki-file"><a href="{attachment.get_absolute_url()}">'
            "plan.pdf</a></p>"
            "<ul><li>one</li></ul><pre>code</pre>"
        ),
    )
    child = WikiPage.objects.create(
        wiki=wiki, title="Child", slug="child", parent=first
    )

    return {
        "wiki": wiki,
        "first": first,
        "second": second,
        "child": child,
        "image": image,
        "file": attachment,
    }


class TestOrder:
    def test_a_page_then_its_subpages_then_the_next(self, handbook):
        assert [
            (page.slug, depth)
            for page, depth in pdf.ordered_pages(handbook["wiki"])
        ] == [("first", 0), ("child", 1), ("second", 0)]


class TestPageHtml:
    def rewrite(self, html: str, images: dict | None = None) -> str:
        parser = pdf.PageHTML(
            base_url="https://desk.test/", images=images or {}
        )
        parser.feed(html)
        parser.close()

        return parser.html()

    def test_an_uploaded_image_is_embedded(self, handbook):
        image = handbook["image"]
        data = pdf.image_data([image.pk])

        html = self.rewrite(f'<img src="{image.get_absolute_url()}">', data)

        assert data[image.pk].startswith("data:image/png;base64,")
        assert f'src="{data[image.pk]}"' in html

    def test_an_image_on_the_web_is_named_never_fetched(self):
        html = self.rewrite('<img src="https://far.test/x.png" alt="far">')

        assert "far.test" not in html
        assert "Image: far" in html
        assert "<img" not in html

    def test_a_file_block_names_the_file(self):
        html = self.rewrite(
            '<p class="wiki-file"><a href="/wiki/files/3/">plan.pdf</a></p>'
        )

        assert html == "<p><i>File: plan.pdf</i></p>"

    def test_links_become_absolute_and_alignment_stays(self):
        html = self.rewrite(
            '<p class="ql-align-right"><a href="/wiki/a/b/">b</a></p>'
        )

        assert html == (
            '<p align="right"><a href="https://desk.test/wiki/a/b/">b</a></p>'
        )

    def test_headings_are_not_sections(self):
        html = self.rewrite("<h2>Part</h2>")

        assert "<h2" not in html
        assert "<b>Part</b>" in html


class TestRender:
    def test_a_wiki_is_a_pdf(self, handbook):
        content = pdf.render(handbook["wiki"], base_url="https://desk.test/")

        assert content.startswith(b"%PDF")

    def test_without_a_unicode_font_latin1_is_enough(
        self, handbook, monkeypatch
    ):
        monkeypatch.setattr(pdf, "FONT_CANDIDATES", ())

        assert pdf.find_fonts() is None
        assert pdf.render(handbook["wiki"]).startswith(b"%PDF")

    def test_typography_has_latin1_stand_ins(self):
        assert pdf.latin1("“OK” — œ 5€") == ('"OK" - oe 5EUR')

    def test_an_empty_wiki_is_a_cover(self, db):
        wiki = Wiki.objects.create(name="Empty", slug="empty")

        assert pdf.render(wiki).startswith(b"%PDF")

    def test_the_fonts_can_be_named(self, settings, tmp_path):
        font = tmp_path / "mine.ttf"
        font.write_bytes(b"")
        settings.GENERIC = {
            **getattr(settings, "GENERIC", {}),
            "WIKI_PDF_FONTS": {"regular": font},
        }

        assert pdf.find_fonts() == {"regular": str(font)}


class TestView:
    def test_a_reader_downloads_it(self, auth_client, handbook):
        response = auth_client.get("/wiki/quality/export.pdf")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response["Content-Disposition"] == (
            'attachment; filename="quality.pdf"'
        )
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response.content.startswith(b"%PDF")

    def test_an_anonymous_visitor_is_sent_to_sign_in(self, client, handbook):
        response = client.get("/wiki/quality/export.pdf")

        assert response.status_code == 302
        assert response.url.startswith("/login/")

    def test_an_unknown_wiki_is_not_found(self, auth_client, db):
        assert auth_client.get("/wiki/nothing/export.pdf").status_code == 404

    def test_the_page_offers_it(self, auth_client, handbook):
        response = auth_client.get("/wiki/quality/first/")

        assert response.context["pdf_url"] == "/wiki/quality/export.pdf"
        assert b"/wiki/quality/export.pdf" in response.content

    def test_nothing_is_offered_without_fpdf2(
        self, auth_client, handbook, monkeypatch
    ):
        monkeypatch.setattr(pdf, "FPDF", None)

        response = auth_client.get("/wiki/quality/first/")

        assert response.context["pdf_url"] == ""
        assert auth_client.get("/wiki/quality/export.pdf").status_code == 404

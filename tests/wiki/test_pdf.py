"""A wiki as a PDF: its pages in the menu's order, its images drawn,
its files named, nothing fetched."""

from __future__ import annotations

import io
from unittest import mock

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


def png(size: tuple[int, int] = (40, 20)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (40, 120, 200)).save(buffer, "PNG")

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
    def rewrite(
        self, html: str, images: dict | None = None, **room: float
    ) -> str:
        parser = pdf.PageHTML(
            base_url="https://desk.test/", images=images or {}, **room
        )
        parser.feed(html)
        parser.close()

        return parser.html()

    def test_an_uploaded_image_is_embedded(self, handbook):
        image = handbook["image"]
        data = pdf.image_data([image.pk])

        html = self.rewrite(f'<img src="{image.get_absolute_url()}">', data)

        source, wide, high = data[image.pk]
        assert source.startswith("data:image/png;base64,")
        assert (wide, high) == (40, 20)
        assert f'src="{source}" width="30.00" height="15.00"' in html

    def test_an_image_beside_the_text_goes_before_its_block(self, handbook):
        image = handbook["image"]
        data = pdf.image_data([image.pk])
        parser = pdf.PageHTML(
            base_url="", images=data, max_width=500, max_height=700
        )
        parser.feed(
            "<p>Intro</p>"
            f'<p><img src="{image.get_absolute_url()}" '
            'class="wiki-float-right" width="2000">Beside</p>'
            "<p>After</p>"
        )
        parser.close()

        assert parser.pieces() == [
            "<p>Intro</p>",
            0,
            "<p>Beside</p>",
            "<p>After</p>",
        ]
        source, width, height, side = parser.floats[0]
        assert source == data[image.pk][0]
        # At most half the room, as on the page.
        assert (width, height, side) == (250, 125, "right")

    def test_an_image_beside_the_text_in_a_table_stays_in_it(self, handbook):
        image = handbook["image"]
        data = pdf.image_data([image.pk])
        parser = pdf.PageHTML(base_url="", images=data)
        parser.feed(
            f'<table><tr><td><img src="{image.get_absolute_url()}" '
            'class="wiki-float-left"></td></tr></table>'
        )
        parser.close()

        assert not parser.floats
        assert "<img" in parser.html()

    def test_a_wide_image_is_shrunk_to_the_page_width(self):
        parser = pdf.PageHTML(
            base_url="", images={}, max_width=500, max_height=700
        )

        assert parser.size("", 4000, 1000) == (500, 125)

    def test_a_tall_image_is_shrunk_to_the_page_height(self):
        parser = pdf.PageHTML(
            base_url="", images={}, max_width=500, max_height=700
        )

        assert parser.size("", 1000, 4000) == (175, 700)

    def test_the_editor_width_is_kept_when_it_fits(self):
        parser = pdf.PageHTML(
            base_url="", images={}, max_width=500, max_height=700
        )

        assert parser.size("200", 1000, 500) == (150, 75)
        assert parser.size("2000", 1000, 500) == (500, 250)

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

    def test_a_text_colour_is_printed(self):
        html = self.rewrite(
            '<p><span class="ql-color-red">a</span>'
            '<strong class="ql-color-blue">b</strong></p>'
        )

        assert html == (
            '<p><font color="#c22826">a</font>'
            '<b><font color="#096acb">b</font></b></p>'
        )

    def test_a_text_colour_survives_the_render(self, handbook):
        handbook["second"].content = (
            '<p><span class="ql-color-green">green</span></p>'
        )
        handbook["second"].save()

        content = pdf.render(handbook["wiki"], base_url="https://desk.test/")

        assert content.startswith(b"%PDF")

    def test_indentation_is_kept_as_levels(self):
        html = self.rewrite(
            '<p class="ql-indent-2">a</p><ul><li class="ql-indent-1">b</li>'
            '</ul><h2 class="ql-indent-1">c</h2>'
        )

        assert '<p data-indent="2">a</p>' in html
        assert '<li data-indent="1">b</li>' in html
        assert '<p data-indent="1"><font size=' in html

    def test_a_tab_is_four_spaces_that_stay(self):
        html = self.rewrite("<p>a\tb</p>")

        assert html == "<p>a\u00a0\u00a0\u00a0\u00a0b</p>"

    def test_a_text_size_is_printed(self):
        html = self.rewrite(
            '<p><span class="ql-size-large">a</span>'
            '<strong class="ql-size-small">b</strong></p>'
        )

        assert html == (
            '<p><font size="14.9">a</font>'
            '<b><font size="8.8">b</font></b></p>'
        )

    def test_an_indented_line_starts_further_right(self):
        document = pdf.WikiDocument(wiki_name="W", unicode=False)
        document.add_page()
        document.set_font("helvetica", "", 11)
        indents = []
        new_paragraph = pdf.WikiHTML._new_paragraph

        def record(html, *args, **kwargs):
            indents.append(kwargs.get("indent", 0))

            return new_paragraph(html, *args, **kwargs)

        with mock.patch.object(pdf.WikiHTML, "_new_paragraph", record):
            document.write_html(
                '<p>flush</p><p data-indent="2">deep</p><p>flush</p>'
            )

        assert indents == [0, 2 * pdf.INDENT_STEP, 0]

    def test_a_table_is_framed_across_the_text(self):
        html = self.rewrite("<table><tr><td>a</td></tr></table>")

        assert html.startswith(
            '<table border="1" width="100%" cellpadding="1.5">'
        )

    def test_a_cell_with_one_format_keeps_it(self):
        html = self.rewrite(
            "<table><tr><td><strong>Total</strong></td></tr></table>"
        )

        assert "<td><b>Total</b></td>" in html

    def test_a_cell_with_mixed_formats_is_its_text(self):
        html = self.rewrite(
            "<table><tr><td><strong>Total</strong> <em>(EUR)</em><br>"
            "x<sub>2</sub></td></tr></table>"
        )

        assert "<td>Total (EUR) x2</td>" in html

    def test_a_table_with_formatted_cells_is_drawn(self, handbook):
        handbook["second"].content = (
            "<table><tbody><tr><td><strong>Total</strong> 12</td>"
            '<td>a <span class="ql-color-red">b</span> <em>c</em></td></tr>'
            "</tbody></table>"
        )
        handbook["second"].save()

        content = pdf.render(handbook["wiki"], base_url="https://desk.test/")

        assert content.startswith(b"%PDF")

    def test_a_table_too_tall_for_the_paper_is_written_as_text(self, handbook):
        words = " ".join(f"word{index}" for index in range(150))
        handbook["second"].content = (
            "<p>Before</p><table><tbody><tr>"
            + "".join(f"<td>H{index}</td>" for index in range(12))
            + "</tr><tr>"
            + "".join(f"<td>{words}</td>" for _ in range(12))
            + "</tr></tbody></table><p>After</p>"
        )
        handbook["second"].save()

        content = pdf.render(handbook["wiki"], base_url="https://desk.test/")

        assert content.startswith(b"%PDF")

    def test_a_table_as_text_is_a_line_per_row(self):
        parser = pdf.PageHTML(
            base_url="https://desk.test/", images={}, tables_as_text=True
        )
        parser.feed(
            "<table><tbody><tr><td><b>a</b></td><td>b</td></tr>"
            "<tr><td>c</td><td></td></tr></tbody></table>"
        )
        parser.close()

        assert parser.html() == "<p><b>a</b> | b</p><p>c | </p>"

    def test_a_table_with_empty_cells_is_drawn(self, handbook):
        handbook["second"].content = (
            "<table><tbody><tr><td>a</td><td></td></tr>"
            "<tr><td></td><td></td></tr></tbody></table>"
        )
        handbook["second"].save()

        content = pdf.render(handbook["wiki"], base_url="https://desk.test/")

        assert content.startswith(b"%PDF")

    def test_headings_are_not_sections(self):
        html = self.rewrite("<h2>Part</h2>")

        assert "<h2" not in html
        assert "<b>Part</b>" in html


class TestRender:
    def test_a_wiki_is_a_pdf(self, handbook):
        content = pdf.render(handbook["wiki"], base_url="https://desk.test/")

        assert content.startswith(b"%PDF")

    def test_landscape_turns_the_paper(self, handbook):
        portrait = pdf.render(handbook["wiki"])
        landscape = pdf.render(handbook["wiki"], orientation="landscape")

        assert b"/MediaBox [0 0 595.28 841.89]" in portrait
        assert b"/MediaBox [0 0 841.89 595.28]" in landscape

    def test_an_unknown_orientation_is_refused(self, handbook):
        with pytest.raises(ValueError):
            pdf.render(handbook["wiki"], orientation="sideways")

    def test_the_text_runs_beside_an_image(self, handbook):
        url = handbook["image"].get_absolute_url()
        words = "Words beside the image. " * 30
        handbook["second"].content = (
            f'<p><img src="{url}" class="wiki-float-left" width="200"></p>'
            f"<p>{words}</p>"
            f'<p><img src="{url}" class="wiki-float-right">{words}</p>'
            "<p>After.</p>"
        )
        handbook["second"].save()
        drawn = []
        image = pdf.WikiDocument.image
        margins = []
        write_html = pdf.WikiDocument.write_html

        def spy(document, *args, **kwargs):
            drawn.append((kwargs["x"], kwargs.get("y"), kwargs["w"]))

            return image(document, *args, **kwargs)

        def write(document, html, **kwargs):
            if "Words beside" in html or "After." in html:
                margins.append((document.l_margin, document.r_margin))

            return write_html(document, html, **kwargs)

        with (
            mock.patch.object(pdf.WikiDocument, "image", spy),
            mock.patch.object(pdf.WikiDocument, "write_html", write),
        ):
            pdf.render(handbook["wiki"])

        (left_x, _, left_w), (right_x, _, right_w) = drawn[-2:]
        # The text beside the left image starts after it, the text
        # beside the right one stops before it, the last line is back
        # between the page's own margins.
        assert margins[0][0] == pytest.approx(left_x + left_w + pdf.FLOAT_GAP)
        assert margins[1][1] > 18 + right_w
        assert margins[-1] == (18, 18)

    def test_an_indented_image_starts_further_right(self, handbook):
        url = handbook["image"].get_absolute_url()
        handbook["second"].content = (
            f'<p class="ql-indent-2"><img src="{url}"></p>'
        )
        handbook["second"].save()
        drawn = []
        image = pdf.WikiDocument.image

        def spy(document, *args, **kwargs):
            drawn.append(kwargs["x"])

            return image(document, *args, **kwargs)

        with mock.patch.object(pdf.WikiDocument, "image", spy):
            pdf.render(handbook["wiki"])

        assert drawn[-1] == pytest.approx(18 + 2 * pdf.INDENT_STEP)

    @pytest.mark.parametrize("orientation", pdf.ORIENTATIONS)
    def test_a_large_image_stays_on_the_paper(self, handbook, orientation):
        wiki = handbook["wiki"]
        huge = WikiImage(original_name="huge.png")
        huge.file.save("huge.png", ContentFile(png((5000, 7000))), save=False)
        huge.save()
        WikiPage.objects.create(
            wiki=wiki,
            title="Huge",
            slug="huge",
            position=3,
            content=f'<p><img src="{huge.get_absolute_url()}"></p>',
        )
        drawn = []
        image = pdf.WikiDocument.image

        def spy(document, *args, **kwargs):
            info = image(document, *args, **kwargs)
            drawn.append((document, info.rendered_width, info.rendered_height))

            return info

        with mock.patch.object(pdf.WikiDocument, "image", spy):
            pdf.render(wiki, orientation=orientation)

        assert drawn
        for document, width, height in drawn:
            assert width <= document.epw + 0.01
            assert height <= document.eph + 0.01

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

    def test_landscape_is_asked_in_the_address(self, auth_client, handbook):
        landscape = auth_client.get(
            "/wiki/quality/export.pdf?orientation=landscape"
        )
        other = auth_client.get("/wiki/quality/export.pdf?orientation=x")

        assert b"/MediaBox [0 0 841.89 595.28]" in landscape.content
        assert b"/MediaBox [0 0 595.28 841.89]" in other.content

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
        assert b"/wiki/quality/export.pdf?orientation=landscape" in (
            response.content
        )

    def test_nothing_is_offered_without_fpdf2(
        self, auth_client, handbook, monkeypatch
    ):
        monkeypatch.setattr(pdf, "FPDF", None)

        response = auth_client.get("/wiki/quality/first/")

        assert response.context["pdf_url"] == ""
        assert auth_client.get("/wiki/quality/export.pdf").status_code == 404

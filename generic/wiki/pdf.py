"""A whole wiki as one PDF: its pages in the menu's order.

Written with fpdf2 - pure Python, installed by pip alone on Linux,
macOS and Windows, no system library to add - from the pages' cleaned
HTML. A cover, a table of contents, then every page, a subpage after
its parent; the images uploaded into a page are drawn where the page
shows them, never wider or taller than the paper, and the files
attached to it are listed by name. Portrait or landscape, A4.

Nothing is fetched: an image on the web, outside the wiki, is named
rather than downloaded, so writing a PDF never makes the server call
an address a page holds.
"""

from __future__ import annotations

import base64
import re
from copy import deepcopy
from html import escape
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from django.template.defaultfilters import filesizeformat
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext

from generic.conf import generic_settings
from generic.sites.files import is_stored
from generic.wiki.models import WikiImage, WikiPage, _address_pattern
from generic.wiki.sanitize import (
    COLOR_TAGS,
    TEXT_COLORS,
    TEXT_SIZES,
    clean_html,
)

try:  # The wiki extra; without it, no PDF is offered.
    from fpdf import FPDF
    from fpdf.errors import FPDFException
    from fpdf.fonts import FontFace, TextStyle
    from fpdf.html import HTML2FPDF
    from fpdf.outline import TableOfContents
except ImportError:  # pragma: no cover - the extra is installed in tests
    FPDF = None
    FPDFException = Exception
    HTML2FPDF = object


def available() -> bool:
    """Whether a wiki can be written as a PDF here."""
    return FPDF is not None


#: TrueType fonts where systems usually keep them, best first: any
#: character a page holds is then drawn, not only Latin-1.
FONT_CANDIDATES: tuple[dict[str, str], ...] = (
    {
        "regular": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "italic": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "bold_italic": (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"
        ),
        "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    },
    {
        "regular": (
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        ),
        "bold": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "italic": (
            "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"
        ),
        "bold_italic": (
            "/usr/share/fonts/truetype/liberation/"
            "LiberationSans-BoldItalic.ttf"
        ),
        "mono": (
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"
        ),
    },
    {
        "regular": "C:/Windows/Fonts/arial.ttf",
        "bold": "C:/Windows/Fonts/arialbd.ttf",
        "italic": "C:/Windows/Fonts/ariali.ttf",
        "bold_italic": "C:/Windows/Fonts/arialbi.ttf",
        "mono": "C:/Windows/Fonts/consola.ttf",
    },
    {
        "regular": "/System/Library/Fonts/Supplemental/Arial.ttf",
        "bold": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "italic": "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
        "bold_italic": (
            "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf"
        ),
        "mono": "/System/Library/Fonts/Supplemental/Courier New.ttf",
    },
)

#: Typography the PDF's own fonts lack, said with what they have.
LATIN1_STAND_INS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": ",",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
    "\u2022": "-",
    "\u0152": "OE",
    "\u0153": "oe",
    "\u20ac": "EUR",
    "\u00a0": " ",
    "\u202f": " ",
}

#: Sizes, in points, of a page's own headings - smaller than the
#: pages' titles, which make the table of contents.
HEADING_SIZES = {"h1": 15, "h2": 14, "h3": 12.5, "h4": 11.5}

#: Sizes of the pages' titles, by their depth in the menu.
TITLE_SIZES = (20, 17, 15, 13.5)

#: The page orientations a PDF is written in, the first by default.
ORIENTATIONS = ("portrait", "landscape")

#: Points per CSS pixel: an image is drawn at the size a screen shows.
POINTS_PER_PIXEL = 0.75

ALIGN_CLASS = re.compile(r"\bql-align-(center|right|justify)\b")
COLOR_CLASS = re.compile(r"\bql-color-([a-z]+)\b")
SIZE_CLASS = re.compile(r"\bql-size-([a-z]+)\b")
INDENT_CLASS = re.compile(r"\bql-indent-([1-8])\b")

#: Millimetres a level of the editor's indentation moves a line: the
#: page's 2em, at the text's size.
INDENT_STEP = 8

#: Size of the text, in points; a resized run is a share of it.
TEXT_SIZE = 11

#: A tab, as the PDF draws it: four spaces that do not collapse.
TAB = "\u00a0" * 4

#: A cell fpdf2 can draw: one run of text, the same format throughout -
#: or one image. Text partly bold, a word in another colour, is refused
#: by its table renderer ("Unsupported nested HTML tags inside <td>").
_RUN_TAGS = r"(?:b|i|u|s|sub|sup|code|font|a)"
DRAWABLE_CELL = re.compile(
    rf"(?:<{_RUN_TAGS}\b[^>]*>)*[^<]*(?:</{_RUN_TAGS}>)*|<img\b[^>]*>"
)
TAG = re.compile(r"<[^>]+>")

TABLE_TAGS = ("table", "thead", "tbody", "tfoot", "tr", "td", "th")

FLOAT_CLASS = re.compile(r"\bwiki-float-(left|right)\b")

#: Millimetres between an image beside the text and the text, or the
#: next image beside it.
FLOAT_GAP = 4

#: The narrowest room, in millimetres, text is written in beside an
#: image; narrower, it goes below.
MIN_BESIDE = 30


class Mark(str):
    """A place in a page's HTML that writes nothing: the end of a
    top-level block; with ``image``, where an image beside the text
    goes, before the block that holds it; with ``row``, a line of
    images side by side; with ``clear``, a heading, which starts below
    the images beside the text."""

    image: int | None = None
    row: int | None = None
    clear = False

    def __new__(
        cls,
        image: int | None = None,
        row: int | None = None,
        clear: bool = False,
    ) -> "Mark":
        mark = super().__new__(cls, "")
        mark.image = image
        mark.row = row
        mark.clear = clear

        return mark


def find_fonts() -> dict[str, str] | None:
    """The fonts to write with: ``WIKI_PDF_FONTS``, or the first set
    found on this system, or ``None`` for the PDF's own fonts."""
    configured = generic_settings.WIKI_PDF_FONTS

    if configured:
        return {key: str(path) for key, path in configured.items() if path}

    for candidate in FONT_CANDIDATES:
        if Path(candidate["regular"]).is_file():
            return {
                key: path
                for key, path in candidate.items()
                if Path(path).is_file()
            }

    return None


def latin1(text: str) -> str:
    """``text`` as the PDF's own fonts can draw it."""
    for character, stand_in in LATIN1_STAND_INS.items():
        text = text.replace(character, stand_in)

    return text.encode("latin-1", "replace").decode("latin-1")


def ordered_pages(wiki: Any) -> list[tuple[WikiPage, int]]:
    """The wiki's pages as the menu shows them, each with its depth: a
    page, then its subpages, siblings by position and title."""
    pages = list(
        WikiPage.objects.filter(wiki=wiki).order_by("position", "title")
    )
    children: dict[Any, list[WikiPage]] = {}
    ids = {page.pk for page in pages}

    for page in pages:
        # A parent outside the wiki would hide a page: shown at the top.
        parent = page.parent_id if page.parent_id in ids else None
        children.setdefault(parent, []).append(page)

    ordered: list[tuple[WikiPage, int]] = []
    seen: set[Any] = set()

    def walk(parent: Any, depth: int) -> None:
        for page in children.get(parent, []):
            # A loop in the data must not hang the export.
            if page.pk in seen:
                continue

            seen.add(page.pk)
            ordered.append((page, depth))
            walk(page.pk, depth + 1)

    walk(None, 0)

    return ordered


class PageHTML(HTMLParser):
    """A page's cleaned HTML, rewritten for fpdf2's HTML renderer.

    The editor's alignment classes become ``align``, its text colours
    ``<font color>``, headings become
    bold lines (only the pages' titles go to the table of contents),
    uploaded images become data the PDF embeds, an image on the web
    its name, a file block its name, and relative links absolute.
    """

    BLOCKS = ("p", "h1", "h2", "h3", "h4", "blockquote", "pre")

    def __init__(
        self,
        *,
        base_url: str,
        images: dict[int, tuple[str, int, int]],
        max_width: float = 0,
        max_height: float = 0,
        tables_as_text: bool = False,
    ) -> None:
        super().__init__(convert_charrefs=True)
        # Each row of a table a line of text, its cells side by side.
        self.tables_as_text = tables_as_text
        self.row_has_cell = False
        self.base_url = base_url.rstrip("/")
        self.images = images
        # The room an image has, in points; 0: no limit.
        self.max_width = max_width
        self.max_height = max_height
        self.image_pattern = re.compile(_address_pattern("image") + "$")
        self.out: list[str] = []
        self.closing: list[str] = []
        self.in_file_block = False
        # Where each open table cell starts in ``out``.
        self.cells: list[int] = []
        # The images beside the text: data, width and height in points,
        # side; where the open top-level block starts; tables open.
        self.floats: list[tuple[str, float, float, str]] = []
        self.block_start: int | None = None
        self.tables = 0
        # The lines of images side by side, each image's data, width
        # and height in points; the open top-level block's tag, whether
        # it has text, its images in the line.
        self.rows: list[list[tuple[str, float, float]]] = []
        self.block_tag = ""
        self.block_text = False
        self.block_images: list[tuple[str, int, int, str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attributes = {name: value or "" for name, value in attrs}
        align = ALIGN_CLASS.search(attributes.get("class", ""))
        align_attribute = f' align="{align.group(1)}"' if align else ""
        indent = INDENT_CLASS.search(attributes.get("class", ""))
        # Read by WikiHTML: the paragraph's left margin, in levels.
        align_attribute += (
            f' data-indent="{indent.group(1)}"' if indent else ""
        )

        if not self.closing:
            if tag in HEADING_SIZES:
                self.out.append(Mark(clear=True))

            self.block_start = len(self.out)
            self.block_tag = tag
            self.block_text = False
            self.block_images = []

        if tag == "table":
            self.tables += 1

        if self.tables_as_text and tag in TABLE_TAGS:
            self.table_as_text(tag)
        elif tag in HEADING_SIZES:
            self.out.append(
                f"<p{align_attribute}>"
                f'<font size="{HEADING_SIZES[tag]}"><b>'
            )
            self.closing.append("</b></font></p>")
        elif tag == "p" and "wiki-file" in attributes.get("class", ""):
            self.in_file_block = True
            self.out.append("<p><i>")
            self.closing.append("</i></p>")
        elif tag == "p":
            self.out.append(f"<p{align_attribute}>")
            self.closing.append("</p>")
        elif tag == "a":
            href = attributes.get("href", "")

            if self.in_file_block:
                # A file in the page: its name, and where to get it.
                self.out.append(gettext("File:") + " ")
                self.closing.append("")
            elif href:
                self.out.append(f'<a href="{escape(self.absolute(href))}">')
                self.closing.append("</a>")
            else:
                self.closing.append("")
        elif tag == "img":
            self.out.append(self.image(attributes))
        elif tag in ("br", "hr"):
            self.out.append(f"<{tag}>")
        elif tag in ("strong", "b"):
            self.out.append("<b>")
            self.closing.append("</b>")
        elif tag in ("em", "i"):
            self.out.append("<i>")
            self.closing.append("</i>")
        elif tag == "blockquote":
            self.out.append(f"<blockquote{align_attribute}>")
            self.closing.append("</blockquote>")
        elif tag in ("u", "s", "sub", "sup", "code", "pre"):
            self.out.append(f"<{tag}>")
            self.closing.append(f"</{tag}>")
        elif tag == "table":
            # Every cell framed, as the page draws it, and the text's
            # width: fpdf2 draws a single line over a bare table.
            self.out.append(
                '<table border="1" width="100%" cellpadding="1.5">'
            )
            self.closing.append("</table>")
        elif tag == "li":
            self.out.append(f"<li{align_attribute}>")
            self.closing.append("</li>")
        elif tag in ("ul", "ol", "thead", "tbody", "tr"):
            self.out.append(f"<{tag}>")
            self.closing.append(f"</{tag}>")
        elif tag in ("td", "th"):
            self.cells.append(len(self.out) + 1)
            span = attributes.get("colspan")
            self.out.append(
                f'<{tag} colspan="{int(span)}">'
                if span and span.isdigit()
                else f"<{tag}>"
            )
            self.closing.append(f"</{tag}>")
        else:
            # A span and whatever else: its text, without the tag.
            self.closing.append("")

        color = COLOR_CLASS.search(attributes.get("class", ""))
        size = SIZE_CLASS.search(attributes.get("class", ""))

        if tag in COLOR_TAGS and size and size.group(1) in TEXT_SIZES:
            points = round(TEXT_SIZE * TEXT_SIZES[size.group(1)], 1)
            self.out.append(f'<font size="{points}">')
            self.closing[-1] = "</font>" + self.closing[-1]

        if tag in COLOR_TAGS and color and color.group(1) in TEXT_COLORS:
            self.out.append(f'<font color="{TEXT_COLORS[color.group(1)]}">')
            self.closing[-1] = "</font>" + self.closing[-1]

    def handle_endtag(self, tag: str) -> None:
        if tag in ("img", "br", "hr"):
            return

        if tag == "table":
            self.tables = max(self.tables - 1, 0)

        if self.tables_as_text and tag in TABLE_TAGS:
            if self.closing:
                self.out.append(self.closing.pop())

            if not self.closing:
                self.end_block()

            return

        if tag in ("td", "th") and self.cells:
            self.plain_cell(self.cells.pop())

        if self.closing:
            self.out.append(self.closing.pop())

            if not self.closing:
                self.end_block()

        if tag == "p":
            self.in_file_block = False

    def end_block(self) -> None:
        """The end of a top-level block: a paragraph of images alone,
        two or more, becomes a line of them, each at most its share of
        the text's width, as on the page."""
        images = self.block_images

        if (
            self.block_tag == "p"
            and len(images) > 1
            and not self.block_text
            and self.block_start is not None
        ):
            room = self.max_width
            self.max_width = room / len(images) if room else 0
            row = [
                (data, *self.size(asked, wide, high))
                for data, wide, high, asked in images
            ]
            self.max_width = room
            self.out[self.block_start :] = [Mark(row=len(self.rows))]
            self.rows.append(row)

        self.block_images = []
        self.out.append(Mark())

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.block_text = True

        self.out.append(escape(data, quote=False).replace("\t", TAB))

    def table_as_text(self, tag: str) -> None:
        """A table's tag, when the table is written as lines of text."""
        if tag == "tr":
            self.row_has_cell = False
            self.out.append("<p>")
            self.closing.append("</p>")
        elif tag in ("td", "th"):
            if self.row_has_cell:
                self.out.append(" | ")

            self.row_has_cell = True
            self.closing.append("")
        else:
            self.closing.append("")

    def plain_cell(self, start: int) -> None:
        """The cell begun at ``out[start]`` as fpdf2 can draw it: kept
        when its text has one format, else its text alone - a cell
        pasted from a spreadsheet, partly bold, is not worth a PDF that
        cannot be written."""
        content = "".join(self.out[start:])

        if DRAWABLE_CELL.fullmatch(content):
            return

        text = TAG.sub("", content.replace("<br>", " "))
        self.out[start:] = [" ".join(text.split())]

    def absolute(self, href: str) -> str:
        if href.startswith("/") and not href.startswith("//"):
            return self.base_url + href

        return href

    def image(self, attributes: dict[str, str]) -> str:
        source = attributes.get("src", "")
        match = self.image_pattern.match(source)
        found = self.images.get(int(match.group("image"))) if match else None

        if found is None:
            # Never fetched: the page says which image it showed.
            label = attributes.get("alt") or source

            return "<i>[{}]</i>".format(
                escape(gettext("Image: %(name)s") % {"name": label})
            )

        data, pixels_wide, pixels_high = found
        side = FLOAT_CLASS.search(attributes.get("class", ""))

        if side and not self.tables and self.block_start is not None:
            # Beside the text: at most half its width, its gap
            # included, as on the page; drawn by write_beside(), before
            # the block holding it.
            room = self.max_width
            self.max_width = room / 2 - FLOAT_GAP * 72 / 25.4 if room else 0
            width, height = self.size(
                attributes.get("width", ""), pixels_wide, pixels_high
            )
            self.max_width = room
            self.floats.append((data, width, height, side.group(1)))
            self.out.insert(self.block_start, Mark(len(self.floats) - 1))
            self.block_start += 1

            return ""

        if not self.tables and self.block_start is not None:
            self.block_images.append(
                (data, pixels_wide, pixels_high, attributes.get("width", ""))
            )

        width, height = self.size(
            attributes.get("width", ""), pixels_wide, pixels_high
        )

        return f'<img src="{data}" width="{width:.2f}" height="{height:.2f}">'

    def size(
        self, asked: str, pixels_wide: int, pixels_high: int
    ) -> tuple[float, float]:
        """An image's size in points: the width the editor gave it, or
        its own, shrunk to the room the page has, its shape kept."""
        ratio = pixels_high / pixels_wide if pixels_wide else 1
        width = (
            int(asked) if asked.isdigit() and int(asked) else pixels_wide
        ) * POINTS_PER_PIXEL

        if self.max_width and width > self.max_width:
            width = self.max_width

        if self.max_height and width * ratio > self.max_height:
            width = self.max_height / ratio

        return width, width * ratio

    def html(self) -> str:
        return "".join(self.out + list(reversed(self.closing)))

    def pieces(self) -> list[str]:
        """The page as its top-level blocks' HTML, with a ``Mark`` for
        each image beside the text, and each line of images, where it
        goes."""
        found: list[str] = []
        current: list[str] = []

        for part in self.out + list(reversed(self.closing)):
            if isinstance(part, Mark):
                if current:
                    found.append("".join(current))
                    current = []

                if part.image is not None or part.row is not None:
                    found.append(part)
                elif part.clear:
                    found.append(part)
            else:
                current.append(part)

        if current:
            found.append("".join(current))

        return found


def image_data(ids: Iterable[int]) -> dict[int, tuple[str, int, int]]:
    """The uploaded images ``ids`` as data addresses the PDF embeds,
    each with its width and height in pixels as a screen shows it;
    the data scaled down to what a page needs."""
    from PIL import Image

    found = {}

    for image in WikiImage.objects.filter(pk__in=set(ids)):
        if not is_stored(image.file):
            continue

        try:
            with image.file.open("rb") as stream:
                picture = Image.open(stream)
                picture.load()
        except (OSError, ValueError):
            # Not an image after all, or no longer readable: named.
            continue

        size = picture.size
        # Wider than the page, at print resolution, is weight for
        # nothing; an animation keeps its first frame.
        picture.thumbnail((1600, 1600))

        if picture.mode not in ("RGB", "RGBA", "L"):
            picture = picture.convert("RGBA")

        buffer = BytesIO()
        picture.save(buffer, format="PNG")
        data = "data:image/png;base64," + base64.b64encode(
            buffer.getvalue()
        ).decode("ascii")
        found[image.pk] = (data, *size)

    return found


class WikiHTML(HTML2FPDF):  # type: ignore
    """fpdf2's HTML renderer, with the editor's indentation: a paragraph,
    heading, quote or list item's ``data-indent`` levels move it right,
    as on the page."""

    #: How far right the open block's images start, in millimetres.
    wiki_indent: float = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        level = dict(attrs).get("data-indent") or ""
        style = self.tag_styles.get(tag)
        margin = getattr(style, "l_margin", None)

        if tag == "img" and self.wiki_indent and not self.table_row:
            # fpdf2 draws an image where the cursor is: at the margin.
            self.pdf.set_x(self.pdf.l_margin + self.wiki_indent)

        if tag in ("p", "li", "blockquote"):
            self.wiki_indent = (
                int(level) * INDENT_STEP if level.isdigit() else 0
            )

        if not level.isdigit() or not isinstance(margin, (int, float)):
            super().handle_starttag(tag, attrs)
            return

        self.tag_styles[tag] = style.replace(
            l_margin=margin + int(level) * INDENT_STEP
        )

        try:
            super().handle_starttag(tag, attrs)
        finally:
            self.tag_styles[tag] = style

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "li", "blockquote"):
            self.wiki_indent = 0

        super().handle_endtag(tag)


class WikiDocument(FPDF if FPDF is not None else object):  # type: ignore
    """The PDF: a footer with the wiki's name and the page number."""

    HTML2FPDF_CLASS = WikiHTML

    def __init__(
        self, *, wiki_name: str, unicode: bool, orientation: str = "portrait"
    ) -> None:
        super().__init__(orientation=orientation[0].upper(), format="A4")
        self.wiki_name = wiki_name
        self.unicode = unicode
        self.wiki_family = "helvetica"
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 18, 18)

    def say(self, value: str) -> str:
        """``value`` as this document's fonts can draw it."""
        return value if self.unicode else latin1(value)

    def footer(self) -> None:
        if self.page_no() == 1:
            return

        self.set_y(-12)
        self.set_font(self.wiki_family, "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, self.say(self.wiki_name), align="L")
        self.set_x(self.l_margin)
        self.cell(0, 6, f"{self.page_no()} / {{nb}}", align="R")
        self.set_text_color(0, 0, 0)


def write_page(pdf: Any, body: str, as_text: Any, **options: Any) -> None:
    """A page's HTML written into ``pdf``; with its tables as lines of
    text if fpdf2 cannot draw them as tables.

    fpdf2's tables refuse some of what a page may hold - a row taller
    than the paper, as a wide table pasted from a spreadsheet makes, or
    cells it cannot lay out - and one page must not stop the whole
    wiki's PDF. Only a page with a table is copied first: the copy is
    the document so far.
    """
    if "<table" not in body:
        pdf.write_html(body, warn_on_tags_not_matching=False, **options)
        return

    before = deepcopy(vars(pdf))

    try:
        pdf.write_html(body, warn_on_tags_not_matching=False, **options)
    except (ValueError, NotImplementedError, FPDFException):
        vars(pdf).clear()
        vars(pdf).update(before)
        pdf.write_html(as_text(), warn_on_tags_not_matching=False, **options)


def write_beside(
    pdf: Any,
    pieces: list[str],
    as_text: list[str],
    floats: list[tuple[str, float, float, str]],
    rows: list[list[tuple[str, float, float]]] | None = None,
    **options: Any,
) -> None:
    """A page holding images beside the text, or lines of images,
    written block by block.

    fpdf2 does not wrap text round an image, nor put images side by
    side: each image beside the text is drawn on its side - next to the
    ones already there, as the page floats them, or below them when the
    room is gone - and the blocks after it are written in the room left
    beside them, margins moved. A line of images is drawn side by side,
    in the room the text has. A heading starts below them all, as on
    the page.
    """
    margins = (pdf.l_margin, pdf.r_margin)
    # The images beside the text: left, right, bottom, side.
    beside: list[tuple[float, float, float, str]] = []
    page = pdf.page
    after_image = False

    def room() -> tuple[float, float]:
        """Where the text has room, left and right, beside the images
        still beside it."""
        nonlocal page

        if pdf.page != page:
            beside.clear()
            page = pdf.page

        beside[:] = [image for image in beside if image[2] > pdf.y]
        left = max(
            [margins[0]]
            + [image[1] + FLOAT_GAP for image in beside if image[3] == "left"]
        )
        right = min(
            [pdf.w - margins[1]]
            + [image[0] - FLOAT_GAP for image in beside if image[3] != "left"]
        )

        return left, right

    def make_room(width: float) -> tuple[float, float]:
        """Down past the images beside the text until ``width`` fits."""
        left, right = room()

        while beside and right - left < width:
            pdf.set_y(min(image[2] for image in beside) + FLOAT_GAP / 2)
            left, right = room()

        return left, right

    def to_text_room(left: float, right: float) -> None:
        pdf.set_left_margin(left)
        pdf.set_right_margin(pdf.w - right)
        pdf.set_x(left)

    def new_page_for(height: float) -> None:
        if pdf.will_page_break(height):
            to_text_room(margins[0], pdf.w - margins[1])
            pdf.add_page()

    def clear() -> None:
        room()

        if beside:
            pdf.set_y(max(image[2] for image in beside) + FLOAT_GAP / 2)
            beside.clear()

        to_text_room(margins[0], pdf.w - margins[1])

    for piece, text_piece in zip(pieces, as_text):
        if isinstance(piece, Mark) and piece.clear:
            clear()
            after_image = False
        elif isinstance(piece, Mark) and piece.image is not None:
            data, width, height, side = floats[piece.image]
            width, height = width / pdf.k, height / pdf.k
            new_page_for(height)
            left, right = make_room(width)
            x = left if side == "left" else right - width
            pdf.image(data, x=x, y=pdf.y, w=width, h=height)
            beside.append((x, x + width, pdf.y + height, side))
            after_image = True
        elif isinstance(piece, Mark) and piece.row is not None:
            images = (rows or [])[piece.row]
            left, right = make_room(MIN_BESIDE)
            # Each at most its share of the room, as on the page.
            share = (right - left) / len(images)
            sizes = []

            for _data, width, height in images:
                width, height = width / pdf.k, height / pdf.k
                scale = min(1, share / width) if width else 1
                sizes.append((width * scale, height * scale))

            tallest = max(height for _width, height in sizes)
            new_page_for(tallest)
            left, _right = room()
            top = pdf.y

            for (data, _width, _height), (width, height) in zip(images, sizes):
                # On one line, their bottoms level, as the page has them.
                pdf.image(
                    data, x=left, y=top + tallest - height, w=width, h=height
                )
                left += width

            pdf.set_y(top + tallest + FLOAT_GAP / 2)
            after_image = False
        elif after_image and not TAG.sub("", piece).strip():
            # The paragraph that held only the image: the text beside
            # it starts level with its top.
            after_image = False
        elif piece.strip():
            after_image = False
            to_text_room(*make_room(MIN_BESIDE))
            write_page(pdf, piece, lambda: str(text_piece), **options)

    # What follows the page starts below its images.
    clear()


def render(
    wiki: Any, *, base_url: str = "", orientation: str = "portrait"
) -> bytes:
    """``wiki`` as a PDF: a cover, a table of contents, its pages, on
    A4 paper in ``orientation``, ``"portrait"`` or ``"landscape"``."""
    if FPDF is None:  # pragma: no cover - the extra is installed in tests
        raise RuntimeError("fpdf2 is needed to write a wiki as a PDF.")

    if orientation not in ORIENTATIONS:
        raise ValueError(f"Unknown orientation: {orientation!r}.")

    fonts = find_fonts()
    pdf = WikiDocument(
        wiki_name=wiki.name,
        unicode=fonts is not None,
        orientation=orientation,
    )
    family = "helvetica"
    mono = "courier"

    if fonts:
        family = "wiki"
        regular = fonts["regular"]
        styles = {
            "": regular,
            "B": fonts.get("bold", regular),
            "I": fonts.get("italic", regular),
            "BI": fonts.get("bold_italic", fonts.get("bold", regular)),
        }

        for style, path in styles.items():
            pdf.add_font(family, style, path)

        if fonts.get("mono"):
            mono = "wikimono"
            pdf.add_font(mono, "", fonts["mono"])
            pdf.add_font(mono, "B", fonts["mono"])
            pdf.add_font(mono, "I", fonts["mono"])
            pdf.add_font(mono, "BI", fonts["mono"])
        else:
            mono = family

    pdf.wiki_family = family
    pdf.set_title(wiki.name)
    pdf.set_creator("django-generic")
    text = pdf.say
    pages = ordered_pages(wiki)

    # The cover.
    pdf.add_page()
    pdf.set_y(90)
    pdf.set_font(family, "B", 28)
    pdf.multi_cell(
        0, 12, text(wiki.name), align="C", new_x="LMARGIN", new_y="NEXT"
    )

    if wiki.description:
        pdf.ln(4)
        pdf.set_font(family, "", 12)
        pdf.multi_cell(
            0,
            7,
            text(wiki.description),
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    pdf.ln(10)
    pdf.set_font(family, "", 10)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(
        0,
        6,
        text(
            gettext("%(count)s pages - %(date)s")
            % {
                "count": len(pages),
                "date": date_format(
                    timezone.localtime(), "DATETIME_FORMAT", use_l10n=True
                ),
            }
        ),
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)

    if not pages:
        pdf.ln(20)
        pdf.set_font(family, "I", 11)
        pdf.multi_cell(
            0,
            6,
            text(gettext("This wiki has no page yet.")),
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )

        return bytes(pdf.output())

    # The table of contents: the pages' titles, a level per depth.
    contents = TableOfContents(
        text_style=TextStyle(font_family=family, font_size_pt=10)
    )

    def draw_contents(document: Any, outline: list) -> None:
        document.set_x(document.l_margin)
        document.set_font(family, "B", 16)
        document.cell(
            0, 10, text(gettext("Contents")), new_x="LMARGIN", new_y="NEXT"
        )
        document.ln(4)
        contents.render_toc(document, outline)

    pdf.add_page()
    pdf.insert_toc_placeholder(
        draw_contents, pages=1 + len(pages) // 40, allow_extra_pages=True
    )

    tag_styles = {
        "a": FontFace(color="#1d4ed8", emphasis="UNDERLINE"),
        "code": FontFace(family=mono),
        "pre": TextStyle(font_family=mono, t_margin=3, b_margin=3),
        "blockquote": TextStyle(
            color="#4b5563", l_margin=6, t_margin=3, b_margin=3
        ),
    }
    ids = []
    image_pattern = re.compile(_address_pattern("image"))

    for page, _depth in pages:
        ids += [
            int(match.group("image"))
            for match in image_pattern.finditer(page.content or "")
        ]

    images = image_data(ids)

    for index, (page, depth) in enumerate(pages):
        if index:
            pdf.add_page()

        size = TITLE_SIZES[min(depth, len(TITLE_SIZES) - 1)]
        pdf.start_section(text(page.title), level=depth)
        pdf.set_font(family, "B", size)
        pdf.multi_cell(
            0, size * 0.5, text(page.title), new_x="LMARGIN", new_y="NEXT"
        )
        pdf.ln(3)

        content = clean_html(page.content)

        def parsed(tables_as_text: bool = False) -> PageHTML:
            # An image fits the paper: the text's width, a page's height.
            parser = PageHTML(
                base_url=base_url,
                images=images,
                max_width=pdf.epw * pdf.k,
                max_height=(pdf.eph - 2) * pdf.k,
                tables_as_text=tables_as_text,
            )
            parser.feed(content)
            parser.close()

            return parser

        parser = parsed()
        body = text(parser.html())
        options = {
            "font_family": family,
            "tag_styles": tag_styles,
            # Lines between the rows too, not only the columns.
            "table_line_separators": True,
        }

        pdf.set_font(family, "", 11)

        if parser.floats or parser.rows:
            pieces = [
                piece if isinstance(piece, Mark) else text(piece)
                for piece in parser.pieces()
            ]
            as_text = [
                piece if isinstance(piece, Mark) else text(piece)
                for piece in parsed(tables_as_text=True).pieces()
            ]

            if len(as_text) != len(pieces):
                as_text = pieces

            write_beside(
                pdf, pieces, as_text, parser.floats, parser.rows, **options
            )
        elif body.strip():
            write_page(
                pdf,
                body,
                lambda: text(parsed(tables_as_text=True).html()),
                **options,
            )
        else:
            pdf.set_font(family, "I", 10)
            pdf.multi_cell(
                0,
                6,
                text(gettext("This page is still empty.")),
                new_x="LMARGIN",
                new_y="NEXT",
            )

        files = [
            attachment
            for attachment in page.attachments()
            if attachment["kind"] == "file"
        ]

        if files:
            # The heading stays with the list.
            if pdf.will_page_break(24):
                pdf.add_page()

            pdf.ln(4)
            pdf.set_font(family, "B", 10)
            pdf.cell(
                0,
                6,
                text(gettext("Attached files")),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_font(family, "", 10)

            for attachment in files:
                pdf.multi_cell(
                    0,
                    5.5,
                    text(
                        "- {} ({})".format(
                            attachment["name"],
                            filesizeformat(attachment["size"] or 0),
                        )
                    ),
                    new_x="LMARGIN",
                    new_y="NEXT",
                )

    return bytes(pdf.output())

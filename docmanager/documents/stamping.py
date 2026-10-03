"""An approved PDF, stamped: a line at the foot of every page saying
which document it is, which version, who approved it and when.

Drawn by ``fpdf2`` (the wiki's PDF export already needs it) on a page of
the same size, laid over each page by ``pypdf`` - both pure Python, both
pip only (``docmanager/requirements.txt``). Without them, or for a file
``pypdf`` cannot read, nothing is stamped: the version is published
unstamped. A Word file is not converted to PDF - that takes LibreOffice
or Word itself.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

#: Points from the page's edges, and the size of the stamp's text.
MARGIN = 28
SIZE = 7


def latin(line: str) -> str:
    """What the PDF's built-in font can draw: Latin-1, the rest a ``?``."""
    return line.encode("latin-1", "replace").decode("latin-1")


def overlay(width: float, height: float, lines: list[str]) -> bytes:
    from fpdf import FPDF

    page = FPDF(unit="pt", format=(width, height))
    page.set_auto_page_break(False)
    page.add_page()
    page.set_font("helvetica", size=SIZE)
    page.set_text_color(90, 90, 90)
    top = height - MARGIN - SIZE * 1.4 * (len(lines) - 1)

    for index, line in enumerate(lines):
        page.set_xy(MARGIN, top + index * SIZE * 1.4)
        page.cell(width - 2 * MARGIN, SIZE, latin(line), align="C")

    return bytes(page.output())


def stamp(data: bytes, lines: list[str]) -> bytes | None:
    """``data``, a PDF, with ``lines`` at the foot of every page - or
    ``None`` when it cannot be done."""
    try:
        from fpdf import FPDF  # noqa: F401
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return None

    try:
        reader = PdfReader(io.BytesIO(data))
        writer = PdfWriter()
        drawn: dict[tuple[float, float], object] = {}

        for page in reader.pages:
            size = (float(page.mediabox.width), float(page.mediabox.height))

            if size not in drawn:
                drawn[size] = PdfReader(
                    io.BytesIO(overlay(*size, lines))
                ).pages[0]

            page.merge_page(drawn[size])
            writer.add_page(page)

        output = io.BytesIO()
        writer.write(output)
    except Exception:  # noqa: BLE001 - an unreadable PDF stays unstamped
        logger.warning("The PDF could not be stamped.", exc_info=True)

        return None

    return output.getvalue()


__all__ = ["stamp"]

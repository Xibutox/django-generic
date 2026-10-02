"""Small but real files for the demonstration: Word, PDF and text.

Written by hand rather than by a library, so the seed needs nothing the
example does not already install. Each opens in its usual application.
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" \
ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="{main}"/>
</Types>"""

WORD_MAIN = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document.main+xml"
)
WORD_TEMPLATE = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.template.main+xml"
)

RELATIONSHIPS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships \
xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" \
Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/\
officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document \
xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>{paragraphs}</w:body>
</w:document>"""


def paragraph(text: str, bold: bool = False) -> str:
    style = "<w:rPr><w:b/></w:rPr>" if bold else ""

    return (
        f'<w:p><w:r>{style}<w:t xml:space="preserve">'
        f"{escape(text)}</w:t></w:r></w:p>"
    )


def docx(title: str, lines: list[str], template: bool = False) -> bytes:
    """A Word document - or template, ``.dotx`` - of a title and lines."""
    buffer = io.BytesIO()
    body = paragraph(title, bold=True) + "".join(map(paragraph, lines))

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            CONTENT_TYPES.format(
                main=WORD_TEMPLATE if template else WORD_MAIN
            ),
        )
        archive.writestr("_rels/.rels", RELATIONSHIPS)
        archive.writestr("word/document.xml", DOCUMENT.format(paragraphs=body))

    return buffer.getvalue()


def pdf(title: str, lines: list[str]) -> bytes:
    """A one-page PDF of a title and lines, in Helvetica."""

    def text(value: str) -> str:
        return (
            value.encode("latin-1", "replace")
            .decode("latin-1")
            .replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )

    rows = [f"BT /F1 18 Tf 72 760 Td ({text(title)}) Tj ET"]
    rows += [
        f"BT /F1 11 Tf 72 {730 - 16 * index} Td ({text(line)}) Tj ET"
        for index, line in enumerate(lines)
    ]
    stream = "\n".join(rows).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = []

    for number, body in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")

    start = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode())
    output.write(b"0000000000 65535 f \n")

    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode())

    output.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{start}\n%%EOF\n".encode()
    )

    return output.getvalue()


def text(title: str, lines: list[str]) -> bytes:
    return "\n".join([title, "=" * len(title), "", *lines, ""]).encode()


def make(name: str, title: str, lines: list[str]) -> bytes:
    """The content of ``name``, by its extension."""
    if name.endswith(".docx"):
        return docx(title, lines)

    if name.endswith(".dotx"):
        return docx(title, lines, template=True)

    if name.endswith(".pdf"):
        return pdf(title, lines)

    return text(title, lines)

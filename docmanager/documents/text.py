"""The text of a file, for the search, the preview and the comparison.

Read once, when a version is recorded, and kept beside it: searching a
clause then costs a database query, never opening every file.

* Word (``.docx``, ``.dotx``), PowerPoint (``.pptx``) and Excel
  (``.xlsx``) files are zip archives of XML: read with the standard
  library, nothing to install.
* PDF files need ``pypdf`` (``docmanager/requirements.txt``, pure
  Python). Without it, or for a scanned PDF - pictures of text, no text
  at all - nothing is read; recognising the pictures (OCR) is not done.
* Text files (``.txt``, ``.md``, ``.csv``...) are read as they are.

Anything else, or a file that cannot be read, has no text: the
document is still found by its title, number and description.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

#: Kept per version, at most: a book's worth, enough for any search.
MAX_LENGTH = 1_000_000

#: Files larger than this are not opened to be read.
MAX_FILE_SIZE = 50 * 1024 * 1024

TEXT_FORMATS = {"TXT", "MD", "CSV", "TSV", "JSON", "XML", "HTML", "HTM"}
WORD_FORMATS = {"DOCX", "DOTX", "DOCM"}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def format_of(name: str) -> str:
    return PurePosixPath(name or "").suffix.lstrip(".").upper()


def tidy(text: str) -> str:
    """Spaces and blank lines folded, the length kept to the limit."""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    return text.strip()[:MAX_LENGTH]


def read_xml(archive: zipfile.ZipFile, name: str) -> Any:
    with archive.open(name) as handle:
        # Office XML has no DTD; the parser resolves no entity anyway.
        return ElementTree.parse(handle).getroot()  # noqa: S314


def word_paragraphs(data: bytes) -> list[str]:
    """A Word file's paragraphs - the body's, tables' included."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = read_xml(archive, "word/document.xml")

    paragraphs = []

    for node in root.iter(f"{W}p"):
        pieces = []

        for run in node.iter():
            if run.tag == f"{W}t" and run.text:
                pieces.append(run.text)
            elif run.tag == f"{W}tab":
                pieces.append("\t")
            elif run.tag in (f"{W}br", f"{W}cr"):
                pieces.append("\n")

        paragraphs.append("".join(pieces))

    return paragraphs


def powerpoint_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        slides = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=lambda name: int(re.sub(r"\D", "", name)),
        )
        texts = [
            " ".join(
                node.text
                for node in read_xml(archive, name).iter(f"{A}t")
                if node.text
            )
            for name in slides
        ]

    return "\n\n".join(texts)


def excel_text(data: bytes) -> str:
    """The words of a workbook: its shared strings and inline ones."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        words = []

        if "xl/sharedStrings.xml" in names:
            root = read_xml(archive, "xl/sharedStrings.xml")
            words += [
                "".join(node.text or "" for node in item.iter(f"{S}t"))
                for item in root.iter(f"{S}si")
            ]

        for name in names:
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
                words += [
                    node.text
                    for node in read_xml(archive, name).iter(f"{S}t")
                    if node.text
                ]

    return "\n".join(words)


def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    reader = PdfReader(io.BytesIO(data))

    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def plain_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    return ""


def text_of(data: bytes, name: str) -> str:
    """What ``data``, a file called ``name``, says - or ``""``."""
    kind = format_of(name)

    try:
        if kind in WORD_FORMATS:
            text = "\n".join(word_paragraphs(data))
        elif kind == "PPTX":
            text = powerpoint_text(data)
        elif kind == "XLSX":
            text = excel_text(data)
        elif kind == "PDF":
            text = pdf_text(data)
        elif kind in TEXT_FORMATS:
            text = plain_text(data)
        else:
            return ""
    except Exception:  # noqa: BLE001 - a broken file has no text
        logger.info("No text read from %s.", name, exc_info=True)

        return ""

    return tidy(text)


def extract(stored: Any, name: str = "") -> str:
    """The text of a stored file - a ``FieldFile`` - or ``""``."""
    if not stored:
        return ""

    try:
        if stored.size > MAX_FILE_SIZE:
            return ""

        with stored.open("rb") as handle:
            data = handle.read()
    except OSError:
        return ""

    return text_of(data, name or stored.name)


__all__ = ["extract", "text_of", "word_paragraphs"]

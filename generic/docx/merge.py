"""Word files put together: several documents, one template, one file.

The documents are appended, in the order given, to a new document made
from the template - a ``.docx``, or a ``.dotx`` Word template - so the
result keeps the template's styles, page set-up, headers and footers.
A template whose body holds a paragraph reading ``{{ documents }}``
receives them there, between its own text; any other template receives
them after its text. With no template, the first document is the base.

Everything happens in memory, on python-docx and docxcompose (the
framework's ``docx`` extra), and nothing is stored::

    from generic.docx import docx_response, merge_docx

    content = merge_docx(
        [version.file for version in versions],
        template=letterhead.file,
    )
    return docx_response(content, "report.docx")
"""

from __future__ import annotations

import io
import re
import zipfile
from os import PathLike, fspath
from pathlib import PurePath
from typing import IO, Any, Iterable, Union

from django.http import HttpResponse
from django.utils.translation import gettext

#: What a merged file is sent as.
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document"
)

#: The main part of a document, and of a template: the only difference
#: between a .docx and a .dotx python-docx cares about.
DOCUMENT_MAIN = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document.main+xml"
)
TEMPLATE_MAIN = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.template.main+xml"
)

#: The paragraph of a template where the documents go.
PLACEHOLDER = "{{ documents }}"

#: Every part of one file unpacked, at most: a few megabytes on disk
#: may claim gigabytes once inflated, and python-docx reads it all.
MAX_UNPACKED_SIZE = 256 * 1024 * 1024

#: Something a document can be read from: its bytes, a path, an open
#: file, an upload or a model's file field.
Source = Union[bytes, str, PathLike, IO[bytes], Any]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxMergeError(ValueError):
    """A file that cannot be merged; the message names it, for people."""


def source_name(source: Source) -> str:
    """The file name of ``source``, without its folders."""
    if isinstance(source, (str, PathLike)):
        name = fspath(source)
    else:
        name = getattr(source, "name", "") or ""

    return PurePath(str(name).replace("\\", "/")).name


def read_source(source: Source) -> bytes:
    """The bytes of ``source``, from the start, whatever it is."""
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)

    if isinstance(source, (str, PathLike)):
        with open(source, "rb") as handle:
            return handle.read()

    # A model's file field: opened from its storage, and closed again.
    if hasattr(source, "storage") and hasattr(source, "open"):
        if not source:
            raise DocxMergeError(gettext("A document has no file."))

        with source.open("rb") as handle:
            return handle.read()

    if hasattr(source, "seek"):
        source.seek(0)

    return source.read()


def as_document_package(data: bytes, name: str) -> bytes:
    """``data`` as a package python-docx opens as a document.

    A Word template differs from a document by the content type of its
    main part alone, which python-docx refuses: renamed in
    ``[Content_Types].xml``, the template is a document. A file that is
    no Word file, a macro-enabled one, or one that would inflate beyond
    :data:`MAX_UNPACKED_SIZE` is refused with a sentence naming it.
    """
    label = name or gettext("a file")

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise DocxMergeError(
            gettext(
                "%(name)s is not a Word file (.docx or .dotx). An older "
                ".doc file has to be saved as .docx first."
            )
            % {"name": label}
        ) from None

    with archive:
        if sum(info.file_size for info in archive.infolist()) > (
            MAX_UNPACKED_SIZE
        ):
            raise DocxMergeError(
                gettext("%(name)s is too large once unpacked.")
                % {"name": label}
            )

        try:
            types = archive.read("[Content_Types].xml").decode("utf-8")
        except (KeyError, UnicodeDecodeError):
            types = ""

        if DOCUMENT_MAIN in types:
            return data

        if TEMPLATE_MAIN not in types:
            raise DocxMergeError(
                gettext(
                    "%(name)s is not a Word file (.docx or .dotx); a file "
                    "with macros (.docm, .dotm) is not accepted either."
                )
                % {"name": label}
            )

        # Rewritten part by part, the content types renamed: the rest is
        # copied as it was, compression included.
        output = io.BytesIO()

        with zipfile.ZipFile(output, "w") as copy:
            for info in archive.infolist():
                content = archive.read(info)

                if info.filename == "[Content_Types].xml":
                    content = types.replace(
                        TEMPLATE_MAIN, DOCUMENT_MAIN
                    ).encode("utf-8")

                copy.writestr(info, content)

    return output.getvalue()


def open_document(source: Source) -> Any:
    """``source`` read into a python-docx ``Document``."""
    from docx import Document

    name = source_name(source)
    data = as_document_package(read_source(source), name)

    try:
        return Document(io.BytesIO(data))
    except Exception:
        # A package that says it is a document and is not one: broken
        # XML, a missing part. What python-docx says helps nobody here.
        raise DocxMergeError(
            gettext("%(name)s could not be read as a Word file.")
            % {"name": name or gettext("a file")}
        ) from None


#: What an empty-looking paragraph may still hold: a picture, a shape,
#: a break, a field.
CONTENT_TAGS = tuple(
    f"{W}{tag}"
    for tag in ("drawing", "pict", "object", "br", "fldSimple", "fldChar")
)


def text_of(element: Any) -> str:
    """The text of a paragraph, its runs' text put together.

    Not ``itertext()``: python-docx gives its elements a ``text`` of
    their own, which lxml reads once per level.
    """
    return "".join(node.text or "" for node in element.iter(f"{W}t"))


def is_blank(element: Any) -> bool:
    """Whether a body element is an empty paragraph and nothing else."""
    if element.tag != f"{W}p" or text_of(element).strip():
        return False

    return element.find(f"{W}pPr/{W}sectPr") is None and not any(
        True for _found in element.iter(*CONTENT_TAGS)
    )


def body_elements(document: Any) -> list[Any]:
    """The body's blocks, without the last section's properties."""
    return [
        element
        for element in document.element.body
        if element.tag != f"{W}sectPr"
    ]


def find_placeholder(document: Any, placeholder: str) -> Any:
    """The body paragraph reading ``placeholder``, or ``None``."""
    wanted = re.sub(r"\s+", "", placeholder)

    for element in body_elements(document):
        if element.tag != f"{W}p":
            continue

        text = re.sub(r"\s+", "", text_of(element))

        if text == wanted:
            return element

    return None


def page_break() -> Any:
    """A paragraph holding nothing but a page break."""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    return parse_xml(
        f'<w:p {nsdecls("w")}><w:r><w:br w:type="page"/></w:r></w:p>'
    )


def merge_docx(
    documents: Iterable[Source],
    template: Source | None = None,
    *,
    page_breaks: bool = True,
    placeholder: str = PLACEHOLDER,
) -> bytes:
    """The ``documents`` put together into one ``.docx``, as bytes.

    ``documents`` are taken in order: bytes, paths, open files, uploads
    or model file fields, each a ``.docx`` or a ``.dotx``. ``template``,
    when given, is the document the result is made from (see the
    module's description). ``page_breaks`` starts each document on a
    new page. Raises :class:`DocxMergeError` for a file that cannot be
    merged, and ``ImportError`` when the ``docx`` extra is missing.
    """
    from docxcompose.composer import Composer

    sources = list(documents)

    if not sources:
        raise DocxMergeError(gettext("Choose at least one document."))

    parts = [open_document(source) for source in sources]
    anchor = None

    if template is None:
        base = parts.pop(0)
        follows_text = True
    else:
        base = open_document(template)
        anchor = find_placeholder(base, placeholder)

        if anchor is None:
            # A template with no text of its own - one empty paragraph,
            # what Word saves - receives the documents from the top.
            blocks = body_elements(base)

            if all(is_blank(element) for element in blocks):
                for element in blocks:
                    element.getparent().remove(element)

                follows_text = False
            else:
                follows_text = True
        else:
            follows_text = False

    if page_breaks:
        for position, part in enumerate(parts):
            if position or follows_text:
                part.element.body.insert(0, page_break())

    composer = Composer(base)

    if anchor is not None:
        # Each inserted where the placeholder stands, last first, so
        # they end up in order; then the placeholder goes.
        index = list(base.element.body).index(anchor)

        for part in reversed(parts):
            composer.insert(index, part)

        anchor.getparent().remove(anchor)
    else:
        for part in parts:
            composer.append(part)

    output = io.BytesIO()
    composer.save(output)

    return output.getvalue()


def docx_name(name: str, default: str = "merged.docx") -> str:
    """A safe file name ending in ``.docx``: no folders, no quotes."""
    name = PurePath(str(name or "").replace("\\", "/")).name
    name = re.sub(r'[\x00-\x1f"<>:|?*/]+', "", name).strip(" .")

    if not name:
        return default

    if name.lower().endswith((".docx", ".dotx")):
        name = name[:-5]

    return f"{name[:200]}.docx"


def docx_response(content: bytes, name: str = "merged.docx") -> HttpResponse:
    """``content`` sent as a ``.docx`` to download, named ``name``."""
    from django.utils.http import content_disposition_header

    response = HttpResponse(content, content_type=DOCX_CONTENT_TYPE)
    response["Content-Disposition"] = content_disposition_header(
        True, docx_name(name)
    )
    response["X-Content-Type-Options"] = "nosniff"

    return response

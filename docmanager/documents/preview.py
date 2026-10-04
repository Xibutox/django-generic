"""A document seen without being downloaded: its *Preview* page.

What the reader may read - the working file for its authors and those a
review asks, the published version for everyone else
(``versions.sees_drafts``) - shown in the page:

* a PDF in the browser's own viewer, served from the page's ``file``
  address with ``Content-Disposition: inline``;
* a picture, as a picture;
* a Word file as HTML, by ``mammoth`` (pip only) - its paragraphs,
  read with the standard library (``text.py``), without it. The HTML is
  cleaned (``nh3``, the wiki's): no script, no style, no picture, links
  to the web only;
* a text file as text.

Anything else is downloaded. Each preview is in the access log.
"""

from __future__ import annotations

import io
import posixpath
from dataclasses import dataclass, field
from typing import Any

from django.http import FileResponse, Http404

from documents import text, versions
from documents.models import Document, DocumentVersion
from generic.access import record

#: The most of a text file shown; the rest is in the download.
MAX_TEXT = 200_000

IMAGES = {
    "PNG": "image/png",
    "JPG": "image/jpeg",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}

#: What may remain of a Word file turned into HTML.
TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "strong",
    "em",
    "u",
    "s",
    "sup",
    "sub",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "br",
    "a",
    "blockquote",
}
ATTRIBUTES = {
    "a": {"href"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}


@dataclass
class Shown:
    """What the page shows, and of which version."""

    kind: str = "none"
    version: DocumentVersion | None = None
    name: str = ""
    published: bool = False
    html: str = ""
    text: str = ""
    paragraphs: list[str] = field(default_factory=list)


def readable(user: Any, document: Document) -> tuple[Any, Any, str]:
    """``(version, stored file, name)`` the reader may read - or Nones:
    a reader who writes nothing, of a document never published."""
    if versions.sees_drafts(user, document):
        version = document.versions.filter(number=document.version).first()

        if version is None or not document.file:
            return None, None, ""

        return version, document.file, version.file_name

    version = document.published_version

    if version is None:
        return None, None, ""

    stored = version.stamped or version.file
    name = (
        posixpath.basename(version.stamped.name)
        if version.stamped
        else version.file_name
    )

    return version, stored, name


def word_html(data: bytes) -> str:
    """A Word file as clean HTML, or ``""`` without ``mammoth``."""
    try:
        import mammoth
        import nh3
    except ImportError:
        return ""

    result = mammoth.convert_to_html(
        io.BytesIO(data),
        # Pictures are left out: only the text is previewed.
        convert_image=mammoth.images.img_element(lambda image: {}),
    )

    return nh3.clean(
        result.value,
        tags=TAGS,
        attributes=ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
    )


def previewable(kind: str) -> bool:
    """Whether a file of this format (``"PDF"``, ``"DOCX"``) is shown in
    the page - anything else is only downloaded."""
    kind = (kind or "").upper()

    return (
        kind == "PDF"
        or kind in IMAGES
        or kind in text.WORD_FORMATS
        or kind in text.TEXT_FORMATS
    )


def shown(request: Any, document: Document) -> Shown:
    """What the preview page draws for ``request``'s reader."""
    version, stored, name = readable(request.user, document)

    return draw(request, document, version, stored, name)


def shown_version(request: Any, version: DocumentVersion) -> Shown:
    """What one version's preview page draws: that version's own file,
    for whoever may download it."""
    if not version.file:
        return Shown()

    return draw(request, version, version, version.file, version.file_name)


def draw(
    request: Any, about: Any, version: Any, stored: Any, name: str
) -> Shown:
    """``stored`` as the page shows it, the look written in ``about``'s
    access log."""
    if version is None:
        return Shown()

    kind = text.format_of(name)
    result = Shown(version=version, name=name, published=version.is_published)

    if kind == "PDF":
        result.kind = "pdf"
    elif kind in IMAGES:
        result.kind = "image"
    elif kind in text.WORD_FORMATS:
        data = read(stored)
        result.kind = "html"
        result.html = word_html(data)

        if not result.html:
            result.kind = "paragraphs"
            result.paragraphs = [
                line for line in text.word_paragraphs(data) if line.strip()
            ]
    elif kind in text.TEXT_FORMATS:
        result.kind = "text"
        result.text = text.plain_text(read(stored)[:MAX_TEXT])
    else:
        result.kind = "download"

    record(
        request,
        about,
        action="viewed",
        detail=f"preview {version.label}"[:255],
    )

    return result


def read(stored: Any) -> bytes:
    try:
        with stored.open("rb") as handle:
            return handle.read()
    except OSError:
        return b""


def file_response(request: Any, document: Document) -> Any:
    """The previewed PDF or picture, shown in the page - never anything
    else: whatever else a file is, it is downloaded."""
    version, stored, name = readable(request.user, document)

    return inline(version, stored, name)


def version_file_response(request: Any, version: DocumentVersion) -> Any:
    """One version's own PDF or picture, shown in its preview page."""
    if not version.file:
        raise Http404

    return inline(version, version.file, version.file_name)


def inline(version: Any, stored: Any, name: str) -> Any:
    kind = text.format_of(name)

    if version is None or (kind != "PDF" and kind not in IMAGES):
        raise Http404

    try:
        handle = stored.open("rb")
    except OSError:
        raise Http404 from None

    if kind == "PDF" and handle.read(5) != b"%PDF-":
        handle.close()
        raise Http404

    handle.seek(0)
    response = FileResponse(
        handle,
        as_attachment=False,
        filename=name,
        content_type=IMAGES.get(kind, "application/pdf"),
    )
    response["X-Content-Type-Options"] = "nosniff"
    # Drawn in the preview page's frame, from this site only.
    response["X-Frame-Options"] = "SAMEORIGIN"

    return response


__all__ = [
    "file_response",
    "previewable",
    "readable",
    "shown",
    "shown_version",
    "version_file_response",
]

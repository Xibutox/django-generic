"""Versions: every file a document has had, kept with its story.

One function writes them all, whichever page the file came from - the
document's form, the *Versions* tab, *Restore* - so the numbering and
the file's description are the same everywhere.

Each version is numbered twice. ``number`` counts every file sent, 1,
2, 3... and never changes. ``label`` says what it is: ``0.1``, ``0.2``
while the document is a draft, ``1.0`` once approved (:func:`publish`)
- then ``1.1``, ``1.2`` for the next draft, and ``2.0`` at the next
approval. The approved version is the *published* one: whoever may not
change documents reads that one, never a draft, while the authors work
on the next (:func:`sees_drafts`).
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import PurePosixPath
from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext

from documents import stamping, text
from documents.models import Document, DocumentVersion, ReviewTask

#: The documents' permission that makes one an author: who holds it
#: reads the drafts.
AUTHOR_PERMISSION = "documents.change_document"


def describe(stored: Any) -> dict[str, Any]:
    """Size, type and SHA-256 of a file already in the storage."""
    digest = hashlib.sha256()
    size = 0

    with stored.open("rb") as handle:
        for chunk in handle.chunks():
            digest.update(chunk)
            size += len(chunk)

    content_type, _encoding = mimetypes.guess_type(stored.name)

    return {
        "file_size": size,
        "content_type": content_type or "application/octet-stream",
        "checksum": digest.hexdigest(),
    }


def next_number(document: Document) -> int:
    # The document's row is locked by the caller: two uploads at once
    # still get two numbers.
    latest = document.versions.aggregate(latest=Max("number"))["latest"]

    return (latest or 0) + 1


def parse(label: str) -> tuple[int, int]:
    """``(1, 2)`` for ``"1.2"``; ``(0, 0)`` for nothing readable."""
    major, _dot, minor = (label or "").partition(".")

    try:
        return int(major), int(minor or 0)
    except ValueError:
        return 0, 0


def draft_label(document: Document, besides: Any = None) -> str:
    """The label of the next draft: ``0.1`` first, one more after a
    draft, ``.1`` after a published version."""
    previous = document.versions.exclude(pk=getattr(besides, "pk", None))
    latest = previous.order_by("-number").first()

    if latest is None:
        return "0.1"

    major, minor = parse(latest.label)

    return f"{major}.{1 if latest.is_published else minor + 1}"


def sees_all_drafts(user: Any) -> bool:
    """Whether ``user`` reads every draft they may see: the authors."""
    return bool(
        getattr(user, "is_authenticated", False)
        and user.has_perm(AUTHOR_PERMISSION)
    )


def sees_drafts(user: Any, document: Document) -> bool:
    """Whether ``user`` reads ``document``'s working file - an author,
    or someone a review asks about it. Everyone else reads its published
    version only."""
    if sees_all_drafts(user):
        return True

    return bool(
        getattr(user, "is_authenticated", False)
        and ReviewTask.objects.filter(
            document=document, assignee=user.pk
        ).exists()
    )


def original_name(upload: Any, stored: Any) -> str:
    """The name the file had on its sender's disk."""
    return PurePosixPath(getattr(upload, "name", "") or stored.name).name


@transaction.atomic
def record_version(
    document: Document,
    *,
    user: Any,
    comment: str = "",
    file_name: str = "",
) -> DocumentVersion:
    """A new version holding the document's current file.

    Called once the document is saved with its new file: the version
    points at the same stored file, which is never copied.
    """
    document = Document.objects.select_for_update().get(pk=document.pk)
    name = file_name or PurePosixPath(document.file.name).name
    version = DocumentVersion.objects.create(
        document=document,
        number=next_number(document),
        label=draft_label(document),
        file=document.file.name,
        file_name=name,
        comment=comment,
        created_by=user if getattr(user, "pk", None) else None,
        content=text.extract(document.file, name),
        **describe(document.file),
    )
    follow(document, version)

    return version


def follow(document: Document, version: DocumentVersion) -> None:
    """Make ``version`` the document's current file."""
    document.file = version.file.name
    document.version = version.number
    document.version_label = version.label
    document.file_size = version.file_size
    document.content = version.content
    document.save(
        update_fields=(
            "file",
            "version",
            "version_label",
            "file_size",
            "file_format",
            "content",
            "updated_at",
        )
    )


@transaction.atomic
def complete(version: DocumentVersion, *, upload: Any) -> DocumentVersion:
    """A version sent on its own - the *Versions* tab's form - described
    and made the document's current file."""
    document = Document.objects.select_for_update().get(pk=version.document_id)
    version.file_name = original_name(upload, version.file)
    version.label = draft_label(document, besides=version)
    version.content = text.extract(version.file, version.file_name)

    for name, value in describe(version.file).items():
        setattr(version, name, value)

    version.save(
        update_fields=(
            "file_name",
            "label",
            "content",
            "file_size",
            "file_format",
            "content_type",
            "checksum",
        )
    )
    follow(document, version)

    return version


@transaction.atomic
def restore(version: DocumentVersion, *, user: Any) -> DocumentVersion:
    """An old version's file, current again - as a new version."""
    document = Document.objects.select_for_update().get(pk=version.document_id)
    restored = DocumentVersion.objects.create(
        document=document,
        number=next_number(document),
        label=draft_label(document),
        file=version.file.name,
        file_name=version.file_name,
        file_size=version.file_size,
        content_type=version.content_type,
        checksum=version.checksum,
        content=version.content,
        comment=gettext("Restored from version %(number)s.")
        % {"number": version.label or version.number},
        created_by=user if getattr(user, "pk", None) else None,
    )
    follow(document, restored)

    return restored


def add_months(day: Any, months: int) -> Any:
    """``day``, ``months`` later - the 31st becoming the month's last."""
    import calendar

    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    last = calendar.monthrange(year, month)[1]

    return day.replace(year=year, month=month, day=min(day.day, last))


@transaction.atomic
def publish(
    document: Document,
    *,
    user: Any = None,
    approvers: list[str] | None = None,
) -> DocumentVersion | None:
    """Approve the document's current version: the next major label
    (``0.3`` becomes ``1.0``, ``1.2`` becomes ``2.0``), the published
    one from now on, a PDF stamped with who approved it - and, when its
    type says how often, its next review date. ``None`` for a document
    without a file; the published version itself when it already is."""
    document = Document.objects.select_for_update().get(pk=document.pk)
    version = document.versions.filter(number=document.version).first()

    if version is None:
        return None

    if version.is_published:
        return version

    major, _minor = parse(version.label)
    version.label = f"{major + 1}.0"
    version.published_at = timezone.now()
    version.published_by = user if getattr(user, "pk", None) else None
    names = approvers if approvers is not None else [name_of(user)]
    stamped = stamp(document, version, [name for name in names if name])

    if stamped is not None:
        stem = PurePosixPath(version.file_name).stem or "document"
        version.stamped.save(
            f"{stem}-{version.label}.pdf", ContentFile(stamped), save=False
        )

    version.save(
        update_fields=("label", "published_at", "published_by", "stamped")
    )

    document.published_version = version
    document.published_label = version.label
    document.published_at = version.published_at
    document.published_file = (version.stamped or version.file).name
    document.version_label = version.label
    fields = [
        "published_version",
        "published_label",
        "published_at",
        "published_file",
        "version_label",
        "updated_at",
    ]
    kind = document.document_type

    if kind is not None and kind.review_months:
        document.review_on = add_months(
            timezone.localdate(), kind.review_months
        )
        fields.append("review_on")

    document.save(update_fields=fields)

    return version


def name_of(user: Any) -> str:
    if not getattr(user, "pk", None):
        return ""

    return user.get_full_name() or user.get_username()


def stamp(
    document: Document, version: DocumentVersion, approvers: list[str]
) -> bytes | None:
    """The approved PDF with a line on every page saying what it is -
    or ``None``: not a PDF, or the libraries are missing."""
    if version.file_format != "PDF":
        return None

    lines = [
        " - ".join(
            part
            for part in (
                document.code or document.reference,
                gettext("version %(label)s") % {"label": version.label},
                gettext("approved on %(date)s")
                % {
                    "date": date_format(
                        timezone.localtime(version.published_at),
                        "SHORT_DATE_FORMAT",
                    )
                },
                (
                    gettext("by %(names)s") % {"names": ", ".join(approvers)}
                    if approvers
                    else ""
                ),
            )
            if part
        ),
        gettext(
            "Uncontrolled once printed or downloaded: the current "
            "version is in the document manager."
        ),
    ]

    try:
        with version.file.open("rb") as handle:
            return stamping.stamp(handle.read(), lines)
    except OSError:
        return None


def fill_text(everything: bool = False) -> int:
    """Read the text of the versions without any - every version, with
    ``everything`` - and give each document its current version's.
    Returns how many versions were read."""
    queryset = DocumentVersion.objects.select_related("document")

    if not everything:
        queryset = queryset.filter(content="")

    count = 0

    for version in queryset.iterator():
        content = text.extract(version.file, version.file_name)

        if not content:
            continue

        DocumentVersion.objects.filter(pk=version.pk).update(content=content)
        Document.objects.filter(
            pk=version.document_id, version=version.number
        ).update(content=content)
        count += 1

    return count

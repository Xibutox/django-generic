"""Versions: every file a document has had, kept with its story.

One function writes them all, whichever page the file came from - the
document's form, the *Versions* tab, *Restore* - so the numbering and
the file's description are the same everywhere.
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import PurePosixPath
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext

from documents.models import Document, DocumentVersion


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
    version = DocumentVersion.objects.create(
        document=document,
        number=next_number(document),
        file=document.file.name,
        file_name=file_name or PurePosixPath(document.file.name).name,
        comment=comment,
        created_by=user if getattr(user, "pk", None) else None,
        **describe(document.file),
    )
    follow(document, version)

    return version


def follow(document: Document, version: DocumentVersion) -> None:
    """Make ``version`` the document's current file."""
    document.file = version.file.name
    document.version = version.number
    document.file_size = version.file_size
    document.save(
        update_fields=(
            "file",
            "version",
            "file_size",
            "file_format",
            "updated_at",
        )
    )


@transaction.atomic
def complete(version: DocumentVersion, *, upload: Any) -> DocumentVersion:
    """A version sent on its own - the *Versions* tab's form - described
    and made the document's current file."""
    document = Document.objects.select_for_update().get(pk=version.document_id)
    version.file_name = original_name(upload, version.file)

    for name, value in describe(version.file).items():
        setattr(version, name, value)

    version.save(
        update_fields=(
            "file_name",
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
        file=version.file.name,
        file_name=version.file_name,
        file_size=version.file_size,
        content_type=version.content_type,
        checksum=version.checksum,
        comment=gettext("Restored from version %(number)s.")
        % {"number": version.number},
        created_by=user if getattr(user, "pk", None) else None,
    )
    follow(document, restored)

    return restored

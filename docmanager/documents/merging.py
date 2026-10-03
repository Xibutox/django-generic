"""The *Merge Word files* page: documents and versions chosen, put in
order, and merged with a template into one ``.docx`` - downloaded, or
kept as a new document.

What the page offers and what it accepts come from the resources' own
querysets, so a reader merges only the files of their teams, whatever
keys a form sends. The merging itself is :mod:`documents.merge`.

A choice travels as a key: ``d12`` for document 12's current file,
``v40`` for version 40. The list's and the versions' *Merge into Word*
actions open the page with theirs already chosen
(``?items=d12,d15,v40``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from django.core.files.base import ContentFile
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils.translation import gettext

from documents import versions
from documents.merge import DocxMergeError, docx_name, docx_response
from documents.models import Document, DocumentVersion, Folder

#: What merges: Word documents and Word templates.
WORD_FORMATS = ("DOCX", "DOTX")

#: Files merged at once, at most.
MAX_ITEMS = 50

#: Documents offered in the page's lists, at most.
MAX_CHOICES = 500


@dataclass(frozen=True)
class Item:
    """One file to merge: a document's current one, or a version."""

    key: str
    label: str
    detail: str
    file: Any

    def as_json(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label, "detail": self.detail}


def resource_of(model: type) -> Any:
    from generic.sites import site

    return site.get_resource(model)


def reachable_documents(request: Any) -> Any:
    """The reader's Word documents: their teams' only."""
    return (
        resource_of(Document)
        .get_queryset(request)
        .filter(file_format__in=WORD_FORMATS)
        .select_related("folder__team")
    )


def reachable_versions(request: Any) -> Any:
    """The reader's Word versions, or none without the right to see
    versions at all."""
    resource = resource_of(DocumentVersion)

    if not resource.has_view_permission(request):
        return DocumentVersion.objects.none()

    return (
        resource.get_queryset(request)
        .filter(file_format__in=WORD_FORMATS)
        .select_related("document")
    )


def document_item(document: Document) -> Item:
    return Item(
        key=f"d{document.pk}",
        label=str(document),
        detail=gettext("%(folder)s, version %(number)s, %(format)s")
        % {
            "folder": document.folder,
            "number": document.version,
            "format": document.file_format,
        },
        file=document.file,
    )


def version_item(version: DocumentVersion) -> Item:
    return Item(
        key=f"v{version.pk}",
        label=gettext("%(document)s, version %(number)s")
        % {"document": version.document, "number": version.number},
        detail=version.file_name,
        file=version.file,
    )


def parse_keys(raw: Iterable[str]) -> list[tuple[str, int]]:
    """``["d12", "v40"]`` as ``[("d", 12), ("v", 40)]``; anything else
    is left out."""
    keys = []

    for value in raw:
        for key in str(value).split(","):
            key = key.strip()

            if key[:1] in ("d", "v") and key[1:].isdigit():
                keys.append((key[0], int(key[1:])))

    return keys


def resolve(request: Any, raw: Iterable[str]) -> tuple[list[Item], int]:
    """The items ``raw`` names, in its order, and how many of them the
    reader may not reach (or do not exist, or are not Word files)."""
    keys = parse_keys(raw)
    wanted_documents = {pk for kind, pk in keys if kind == "d"}
    wanted_versions = {pk for kind, pk in keys if kind == "v"}
    documents = {
        document.pk: document
        for document in reachable_documents(request).filter(
            pk__in=wanted_documents
        )
    }
    found_versions = {
        version.pk: version
        for version in reachable_versions(request).filter(
            pk__in=wanted_versions
        )
    }
    items = []
    missing = 0

    for kind, pk in keys:
        if kind == "d" and pk in documents:
            items.append(document_item(documents[pk]))
        elif kind == "v" and pk in found_versions:
            items.append(version_item(found_versions[pk]))
        else:
            missing += 1

    return items, missing


def key_of(value: Any) -> int:
    """A key sent by the form; ``0``, which nothing has, when it is not
    a number."""
    value = str(value)

    return int(value) if value.isdigit() else 0


def may_save(request: Any) -> bool:
    return resource_of(Document).has_add_permission(request)


def page_context(request: Any, data: Any, error: str = "") -> dict:
    """What the page's template needs, the reader's choices kept."""
    chosen, missing = resolve(request, data.getlist("items"))
    documents = list(reachable_documents(request)[:MAX_CHOICES])
    templates = sorted(
        documents, key=lambda document: document.file_format != "DOTX"
    )
    folders = (
        resource_of(Folder).get_queryset(request).select_related("team")
        if may_save(request)
        else Folder.objects.none()
    )

    if missing and not error:
        error = gettext(
            "%(count)s chosen file(s) are not Word files, or not "
            "yours to see: they were left out."
        ) % {"count": missing}

    return {
        "merge_config": {
            "items": [item.as_json() for item in chosen],
            "choices": [document_item(d).as_json() for d in documents],
            "maxItems": MAX_ITEMS,
        },
        "templates": templates,
        "folders": folders,
        "values": {
            "template": data.get("template", ""),
            "name": data.get("name", ""),
            "folder": data.get("folder", ""),
            "title": data.get("title", ""),
            # Ticked when the page opens; then as the reader left it.
            "page_breaks": request.method == "GET"
            or bool(data.get("page_breaks")),
        },
        "error": error,
        "placeholder": "{{ documents }}",
    }


def merge(request: Any) -> Any:
    """The POST: the merged file, downloaded or kept; or the page again
    with what went wrong."""
    data = request.POST
    items, missing = resolve(request, data.getlist("items"))
    template = None

    def again(message: str) -> dict:
        return page_context(request, data, message)

    if missing:
        return again(
            gettext(
                "%(count)s chosen file(s) are not Word files, or not "
                "yours to see."
            )
            % {"count": missing}
        )

    if not items:
        return again(gettext("Choose at least one document."))

    if len(items) > MAX_ITEMS:
        return again(
            gettext("At most %(count)s files can be merged at once.")
            % {"count": MAX_ITEMS}
        )

    if data.get("template"):
        template = (
            reachable_documents(request)
            .filter(pk=key_of(data["template"]))
            .first()
        )

        if template is None:
            return again(gettext("This template is not available."))

    try:
        content = merge_files(items, template, data.get("page_breaks"))
    except DocxMergeError as error:
        return again(str(error))

    name = docx_name(data.get("name", ""))

    if not data.get("folder"):
        return docx_response(content, name)

    folder = (
        resource_of(Folder)
        .get_queryset(request)
        .filter(pk=key_of(data["folder"]))
        if may_save(request)
        else Folder.objects.none()
    ).first()

    if folder is None:
        return again(gettext("This folder is not available."))

    document = keep(
        request,
        content,
        name=name,
        folder=folder,
        title=data.get("title", "").strip() or name[:-5],
        items=items,
    )

    return HttpResponseRedirect(
        resource_of(Document).get_detail_url(document.pk)
    )


def merge_files(
    items: list[Item], template: Document | None, page_breaks: Any
) -> bytes:
    from documents.merge import merge_docx

    return merge_docx(
        [item.file for item in items],
        template=template.file if template is not None else None,
        page_breaks=bool(page_breaks),
    )


@transaction.atomic
def keep(
    request: Any,
    content: bytes,
    *,
    name: str,
    folder: Folder,
    title: str,
    items: list[Item],
) -> Document:
    """The merged file kept as a new document, at version 1, its note
    naming what it was made of."""
    document = Document(
        title=title[:200],
        folder=folder,
        created_by=request.user,
        description=gettext("Merged from: %(files)s")
        % {"files": ", ".join(item.label for item in items)},
    )
    document.file.save(name, ContentFile(content), save=False)
    document.save()
    versions.record_version(
        document,
        user=request.user,
        comment=gettext("Merged from %(count)s file(s).")
        % {"count": len(items)},
        file_name=name,
    )

    return document

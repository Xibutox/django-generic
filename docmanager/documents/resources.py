"""The document manager's screens.

Each resource names the path to its team (``team_field``): lists,
pages, searches, downloads and the choices of every form show a reader
their own teams' folders and documents only (docs/teams.md). The rest
is declared like any django-generic screen (docs/ for each part).
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from documents import versions
from documents.models import Document, DocumentVersion, Folder, Tag
from generic.sites import (
    Chart,
    ModelResource,
    RelatedTable,
    TagStyle,
    action,
    display,
    register,
    site,
)

GROUP = _("Documents")

STATUS_COLORS = {
    Document.Status.DRAFT: "#64748b",
    Document.Status.REVIEW: "#d97706",
    Document.Status.APPROVED: "#16a34a",
    Document.Status.OBSOLETE: "#991b1b",
}


def human_size(size: int) -> str:
    """``"1.4 MB"`` for 1 468 006 bytes."""
    if size < 1024:
        return f"{size} B"

    for unit in ("KB", "MB", "GB"):
        size /= 1024

        if size < 1024 or unit == "GB":
            break

    return f"{size:.1f} {unit}"


@register(Folder)
class FolderResource(ModelResource):
    icon = "folder"
    group = GROUP
    order = 1
    description = _("Where each team files its documents.")

    team_field = "team"

    list_display = ("name", "team", "document_count", "description")
    search_fields = ("name", "team__name")
    tag_fields = {"team": TagStyle(color="color")}
    fieldsets = ((None, {"fields": (("name", "team"), "description")}),)
    related_tables = (RelatedTable("documents"),)

    @display(description=_("Documents"))
    def document_count(self, folder: Folder) -> int:
        return folder.documents.count()


@register(Tag)
class TagResource(ModelResource):
    icon = "sell"
    group = GROUP
    order = 3
    list_display = ("name", "color")
    search_fields = ("name",)
    tag_fields = {"name": TagStyle(color="color")}
    form_overrides = {"color": {"widget": "color"}}


@register(Document)
class DocumentResource(ModelResource):
    icon = "description"
    group = GROUP
    order = 0
    description = _("Every document, with each version of its file.")

    team_field = "folder__team"

    list_display = (
        "reference",
        "title",
        "folder",
        "folder__team",
        "status",
        "tags",
        "file_format",
        "version",
        "updated_at",
    )
    search_fields = ("reference", "title", "description", "folder__name")
    ordering = ("-updated_at", "-pk")
    tag_fields = {
        "status": TagStyle(colors=STATUS_COLORS),
        "tags": TagStyle(color="color"),
    }
    presets = {
        _("To review"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "any_of",
                        "value": [Document.Status.REVIEW],
                    }
                ],
            },
        },
    }
    actions = ("approve", "delete_selected")

    fieldsets = (
        (None, {"fields": ("title", ("folder", "status"), "tags")}),
        (
            _("File"),
            {
                "fields": ("file", "version_note"),
                "description": _(
                    "Replacing the file keeps the old one as a version."
                ),
            },
        ),
        (_("Description"), {"fields": ("description",)}),
    )
    form_extra_fields = {
        "version_note": serializers.CharField(
            label=_("Change note"),
            help_text=_("What changed in the file, and why."),
            required=False,
            allow_blank=True,
        )
    }
    form_overrides = {"description": {"rows": 4}}

    detail_stats = ("version", "file_format", "size", "updated_at")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "folder",
                    "status",
                    "tags",
                    "file",
                    "description",
                )
            },
        ),
        (
            _("Record"),
            {"fields": ("reference", "created_by", "created_at")},
        ),
    )
    readonly_fields = ("reference", "created_by", "created_at")
    related_tables = (
        RelatedTable("versions", description=_("Newest first.")),
    )

    charts = (
        Chart(
            "by_status",
            title=_("By status"),
            type="donut",
            group_by="status",
        ),
        Chart(
            "by_team",
            title=_("By team"),
            type="bar",
            group_by="folder__team",
            split_by="status",
            stacked=True,
        ),
    )
    list_charts = ("by_status", "by_team")

    @display(description=_("Format"))
    def file_format(self, document: Document) -> str:
        return document.format

    @display(description=_("Size"))
    def size(self, document: Document) -> str:
        return human_size(document.file_size)

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        upload = serializer.validated_data.get("file")
        note = serializer.extra_values.get("version_note", "")
        stamp = {} if change else {"created_by": request.user}
        document = serializer.save(**stamp)

        # A file sent is a new version; a form saved without one only
        # changed what is said about the document.
        if upload:
            versions.record_version(
                document,
                user=request.user,
                comment=note,
                file_name=versions.original_name(upload, document.file),
            )
            document.refresh_from_db()

        return document

    def get_download_name(self, request: Any, obj: Any, field: str) -> str:
        current = obj.versions.filter(number=obj.version).first()

        return current.file_name if current else ""

    @action(
        description=_("Approve"),
        icon="verified",
        permissions=("change",),
        confirm=_("Approve the selected documents?"),
    )
    def approve(self, request: Any, queryset: Any) -> str:
        count = 0

        # One by one rather than update(): each keeps its history entry
        # and tells whoever watches it.
        for document in queryset.exclude(status=Document.Status.APPROVED):
            document.status = Document.Status.APPROVED
            document.save(update_fields=("status", "updated_at"))
            count += 1

        return gettext("%(count)s approved.") % {"count": count}


@register(DocumentVersion)
class DocumentVersionResource(ModelResource):
    icon = "history"
    group = GROUP
    order = 2
    label_plural = _("versions")
    description = _("Every file sent, in every document.")

    team_field = "document__folder__team"

    list_display = (
        "document",
        "number",
        "file",
        "comment",
        "created_by",
        "created_at",
        "file_format",
        "size",
    )
    search_fields = ("document__reference", "document__title", "comment")
    ordering = ("-created_at", "-number")
    fields = ("document", "file", "comment")
    form_overrides = {"comment": {"rows": 3}}
    detail_stats = ("number", "file_format", "size")
    detail_fieldsets = (
        (None, {"fields": ("document", "file", "comment")}),
        (
            _("File"),
            {
                "fields": (
                    "file_name",
                    "content_type",
                    "checksum",
                    "created_by",
                    "created_at",
                )
            },
        ),
    )
    readonly_fields = (
        "number",
        "file_name",
        "content_type",
        "checksum",
        "created_by",
        "created_at",
    )
    actions = ("restore",)
    # A version is what was sent: the document's history says the rest.
    history = False

    @display(description=_("Format"))
    def file_format(self, version: DocumentVersion) -> str:
        return version.format

    @display(description=_("Size"), ordering="file_size")
    def size(self, version: DocumentVersion) -> str:
        return human_size(version.file_size)

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        # Never rewritten: a correction is a new version.
        return False

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        upload = serializer.validated_data["file"]
        document = serializer.validated_data["document"]
        version = serializer.save(
            number=versions.next_number(document),
            created_by=request.user,
        )

        return versions.complete(version, upload=upload)

    def get_download_name(self, request: Any, obj: Any, field: str) -> str:
        return obj.file_name

    @action(
        description=_("Restore"),
        icon="restore",
        permissions=("add",),
        confirm=_("Make this version the document's file again?"),
    )
    def restore(self, request: Any, queryset: Any) -> dict:
        chosen = list(queryset[:2])

        if len(chosen) != 1:
            return {
                "message": gettext("Choose one version to restore."),
                "level": "warning",
            }

        restored = versions.restore(chosen[0], user=request.user)

        return {
            "message": gettext("%(document)s is at version %(number)s.")
            % {"document": restored.document, "number": restored.number},
            "level": "success",
        }


site.add_shortcut(
    _("Documents in review"),
    url='/documents/document/?filters={"match":"all","conditions":'
    '[{"column":"status","operator":"any_of","value":["review"]}]}',
    icon="rate_review",
    description=_("Waiting for someone to approve them."),
    count=lambda request: site.get_resource(Document)
    .get_queryset(request)
    .filter(status=Document.Status.REVIEW)
    .count(),
    permission="documents.view_document",
)

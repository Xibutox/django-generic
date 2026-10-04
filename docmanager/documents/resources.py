"""The document manager's screens.

Each resource names the path to its team (``team_field``): lists,
pages, searches, downloads and the choices of every form show a reader
their own teams' folders and documents only (docs/teams.md). The rest
is declared like any django-generic screen (docs/ for each part).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Exists,
    OuterRef,
    Q,
    QuerySet,
    Value,
    When,
)
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from documents import codification, merging, preview, versions, workflows
from documents.models import (
    Codification,
    Comment,
    Document,
    DocumentType,
    DocumentVersion,
    Folder,
    Review,
    ReviewStep,
    ReviewTask,
    StepKind,
    Tag,
    TeamWiki,
    Workflow,
    WorkflowStep,
)
from generic.delivery import NotificationLevel
from generic.sites import (
    Chart,
    ModelResource,
    RelatedTable,
    StackedInline,
    TagStyle,
    action,
    display,
    page,
    register,
    site,
)
from generic.teams import sees_every_team, teams_of

GROUP = _("Documents")
REVIEWS = _("Reviews")
SETTINGS = _("Settings")

#: The format column, holding Word files only - a preset of the lists.
WORD_FILES = {
    "filters": {
        "match": "all",
        "conditions": [
            {
                "column": "file_format",
                "operator": "equals",
                "value": list(merging.WORD_FORMATS),
            }
        ],
    },
}


def condition(column: str, operator: str, value: Any = None) -> dict:
    entry = {"column": column, "operator": operator}

    if value is not None:
        entry["value"] = value

    return entry


def matching(*conditions: dict, match: str = "all") -> dict:
    return {"filters": {"match": match, "conditions": list(conditions)}}


class LiveDocuments:
    """A resource of what hangs on a document - its versions, reviews,
    tasks, comments - showing none of a document in the trash."""

    #: The path from the model to its document.
    document_path = "document"

    def get_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_queryset(request)  # type: ignore[misc]
            .filter(**{f"{self.document_path}__deleted_at__isnull": True})
        )


def widened(queryset: QuerySet, scoped: QuerySet, extra: Q) -> QuerySet:
    """``scoped`` - the reader's teams' rows - and the rows ``extra``
    adds: what someone asked of the reader, outside their teams."""
    return queryset.filter(
        Q(pk__in=scoped.values("pk"))
        | Q(pk__in=queryset.model._default_manager.filter(extra).values("pk"))
    )


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

    list_display = ("path", "team", "document_count", "description")
    list_display_links = ("path",)
    search_fields = ("name", "path", "team__name")
    ordering = ("team__name", "path")
    tag_fields = {"team": TagStyle(color="color")}
    fieldsets = (
        (None, {"fields": (("name", "team"), "parent", "description")}),
    )
    detail_fieldsets = (
        (None, {"fields": ("name", "team", "parent", "path", "description")}),
    )
    related_tables = (
        RelatedTable(
            "children",
            icon="folder",
            description=_("The folders inside it."),
        ),
        RelatedTable("documents"),
    )

    @display(description=_("Documents"))
    def document_count(self, folder: Folder) -> int:
        return folder.documents.filter(deleted_at__isnull=True).count()

    def get_form_serializer_class(self) -> Any:
        if getattr(self, "_folder_serializer", None) is None:
            self._folder_serializer = unique_name_serializer(
                super().get_form_serializer_class()
            )

        return self._folder_serializer

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        parent = serializer.validated_data.get("parent")
        team = serializer.validated_data.get("team")
        folder = serializer.instance

        if parent is not None:
            if team is not None and parent.team_id != team.pk:
                raise serializers.ValidationError(
                    {
                        "parent": [
                            gettext("A folder is in a folder of its own team.")
                        ]
                    }
                )

            if folder is not None and (
                parent.pk == folder.pk
                or folder.pk in [above.pk for above in parent.ancestors()]
            ):
                raise serializers.ValidationError(
                    {
                        "parent": [
                            gettext(
                                "A folder cannot be put inside itself, nor "
                                "inside one of its own folders."
                            )
                        ]
                    }
                )

        before = folder.team_id if folder is not None else None
        saved = serializer.save()

        # Moved to another team: the folders inside it follow.
        if before is not None and saved.team_id != before:
            Folder.objects.filter(
                pk__in=[child.pk for child in saved.descendants()]
            ).update(team=saved.team_id)

        return saved


def unique_name_serializer(base: Any) -> Any:
    """``base`` checking a folder's name is free where it goes - in place
    of the validators DRF writes from the model's conditional unique
    constraints, which a partial update without ``parent`` breaks (a
    KeyError in DRF 3.16)."""

    class FolderSerializer(base):
        class Meta(base.Meta):
            validators: list = []

        def validate(self, attrs: dict) -> dict:
            attrs = super().validate(attrs)
            folder = self.instance

            def value(name: str) -> Any:
                if name in attrs:
                    return attrs[name]

                return getattr(folder, name, None)

            parent = value("parent")
            others = Folder.objects.filter(name=value("name"))

            if parent is not None:
                others = others.filter(parent=parent)
            else:
                others = others.filter(team=value("team"), parent__isnull=True)

            if folder is not None:
                others = others.exclude(pk=folder.pk)

            if others.exists():
                raise serializers.ValidationError(
                    {
                        "name": [
                            gettext("A folder of this name is already there.")
                        ]
                    }
                )

            return attrs

    FolderSerializer.__name__ = base.__name__

    return FolderSerializer


@register(TeamWiki)
class TeamWikiResource(ModelResource):
    icon = "auto_stories"
    group = _("People")
    order = 5
    label_plural = _("team wikis")
    description = _(
        "Who reads and who writes each wiki: a wiki of no team is "
        "everyone's; editing teams write in it, and nobody else."
    )

    list_display = ("wiki", "team", "editing_teams", "page_count")
    search_fields = ("wiki__name", "team__name")
    tag_fields = {
        "team": TagStyle(color="color"),
        "editing_teams": TagStyle(color="color"),
    }
    fields = ("wiki", "team", "editing_teams")
    history = False

    def get_queryset(self, request: Any) -> QuerySet:
        user = getattr(request, "user", None)
        queryset = super().get_queryset(request)

        if sees_every_team(user):
            return queryset

        # A wiki's row is its readers' team's, and its editors'.
        mine = teams_of(user).values("pk")

        return queryset.filter(
            Q(team__in=mine)
            | Q(
                wiki__in=TeamWiki.objects.filter(
                    editing_teams__in=mine
                ).values("wiki")
            )
        )

    @display(description=_("Pages"))
    def page_count(self, link: TeamWiki) -> int:
        return link.wiki.pages.count()


@register(Tag)
class TagResource(ModelResource):
    icon = "sell"
    group = GROUP
    order = 3
    list_display = ("name", "color")
    search_fields = ("name",)
    tag_fields = {"name": TagStyle(color="color")}
    form_overrides = {"color": {"widget": "color"}}


@register(DocumentType)
class DocumentTypeResource(ModelResource):
    icon = "category"
    group = SETTINGS
    order = 1
    label_plural = _("document types")
    description = _("Kinds of document, and the code their numbers carry.")

    list_display = (
        "name",
        "code",
        "review_months",
        "review_workflow",
        "document_count",
        "description",
    )
    search_fields = ("name", "code")
    tag_fields = {"name": TagStyle(color="color")}
    fieldsets = (
        (None, {"fields": (("name", "code"), "color", "description")}),
        (
            _("Periodic review"),
            {
                "fields": (("review_months", "review_workflow"),),
                "description": _(
                    "Documents of this type are read again every so many "
                    "months after their approval: their authors and team "
                    "leaders are reminded beforehand, and on the day the "
                    "workflow starts on its own."
                ),
            },
        ),
    )
    form_overrides = {"color": {"widget": "color"}}

    @display(description=_("Documents"))
    def document_count(self, kind: DocumentType) -> int:
        return kind.documents.count()


@register(Codification)
class CodificationResource(ModelResource):
    icon = "pin"
    group = SETTINGS
    order = 2
    label_plural = _("codifications")
    description = _(
        "How each team numbers its documents - with a file or not yet."
    )

    team_field = "team"

    list_display = ("team", "code", "pattern", "on_create", "next_number")
    search_fields = ("team__name", "code", "pattern")
    tag_fields = {"team": TagStyle(color="color")}
    fieldsets = (
        (None, {"fields": (("team", "code"), "pattern", "on_create")}),
    )
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "team",
                    "code",
                    "pattern",
                    "on_create",
                    "next_number",
                )
            },
        ),
    )
    readonly_fields = ("next_number",)

    @display(description=_("Next number"))
    def next_number(self, rules: Codification) -> str:
        try:
            return codification.next_number(rules)
        except Exception:
            return "-"


@register(Document)
class DocumentResource(ModelResource):
    icon = "description"
    group = GROUP
    order = 0
    description = _("Every document, with each version of its file.")

    team_field = "folder__team"
    # Deleted into a trash for GENERIC["TRASH_DAYS"] days; who opens
    # and downloads what is logged (generic.trash, generic.access).
    trash = True
    access_log = True

    list_display = (
        "code",
        "reference",
        "title",
        "shortcuts",
        "document_type",
        "folder",
        "folder__team",
        "status",
        "tags",
        "file_format",
        "version_label",
        "published_label",
        "checked_out_by",
        "review_on",
        "updated_at",
    )
    # There when asked for, in the column selector: the list opens on
    # what tells one document from another.
    list_display_hidden = (
        "reference",
        "published_label",
        "checked_out_by",
        "review_on",
    )
    search_fields = (
        "code",
        "reference",
        "title",
        "description",
        "folder__path",
        "document_type__name",
        "document_type__code",
        "file_format",
        # What the file says: a clause, a name, a figure (text.py).
        "content",
    )
    ordering = ("-updated_at", "-pk")
    tag_fields = {
        "status": TagStyle(colors=STATUS_COLORS),
        "tags": TagStyle(color="color"),
        "document_type": TagStyle(color="color"),
    }
    presets = {
        _("To review"): matching(
            condition("status", "any_of", [Document.Status.REVIEW])
        ),
        _("Word files"): WORD_FILES,
        _("Without a file"): matching(condition("file_format", "empty")),
        _("Not numbered"): matching(condition("code", "empty")),
        _("Never published"): matching(condition("published_label", "empty")),
        _("Checked out"): matching(condition("checked_out_by", "not_empty")),
        _("Due for a review"): matching(
            condition("review_on", "older_than_days", 0),
            condition("review_on", "next_days", 30),
            match="any",
        ),
    }
    actions = (
        "send_for_review",
        "approve",
        "codify",
        "check_out",
        "check_in",
        "make_obsolete",
        "merge_word",
        "delete_selected",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    ("folder", "document_type"),
                    ("status", "review_on"),
                    "tags",
                )
            },
        ),
        (
            _("File"),
            {
                "fields": ("file", "version_note"),
                "description": _(
                    "Replacing the file keeps the old one as a version. "
                    "A document may have none yet: numbered first, "
                    "written later."
                ),
            },
        ),
        (
            _("Number"),
            {
                "fields": ("codify",),
                "description": _(
                    "Given once, by the team's codification, and never "
                    "changed."
                ),
            },
        ),
        (_("Description"), {"fields": ("description", "related")}),
    )
    form_extra_fields = {
        "version_note": serializers.CharField(
            label=_("Change note"),
            help_text=_("What changed in the file, and why."),
            required=False,
            allow_blank=True,
        ),
        "codify": serializers.BooleanField(
            label=_("Give it its number now"),
            help_text=_(
                "Some teams number every new document anyway. Without "
                "a file too."
            ),
            required=False,
            default=False,
        ),
    }
    form_overrides = {"description": {"rows": 4}}

    detail_stats = ("version_label", "file_format", "size", "open_tasks")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "code",
                    "document_type",
                    "folder",
                    "status",
                    "tags",
                    "file",
                    "review_on",
                    "checked_out_by",
                    "related",
                    "description",
                )
            },
        ),
        (
            _("Published version"),
            {
                "fields": (
                    "published_label",
                    "published_file",
                    "published_at",
                ),
                "description": _(
                    "The last approved version: what readers who change "
                    "nothing read, while the authors work on the next."
                ),
            },
        ),
        (
            _("Record"),
            {
                "fields": (
                    "reference",
                    "codified_at",
                    "checked_out_at",
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    readonly_fields = ("reference", "created_by", "created_at")
    related_tables = (
        RelatedTable("versions", description=_("Newest first.")),
        RelatedTable(
            "reviews",
            icon="rule",
            description=_("Each circuit the document went through."),
        ),
        RelatedTable(
            "comments",
            icon="forum",
            allow_add=True,
            description=_("What its readers had to say."),
        ),
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

    def scope_to_teams(self, request: Any, queryset: QuerySet) -> QuerySet:
        # Whoever is asked to review a document reads it, in their team
        # or not: a review never stops at a door.
        user = getattr(request, "user", None)

        return widened(
            queryset,
            super().scope_to_teams(request, queryset),
            Q(reviews__tasks__assignee=getattr(user, "pk", None)),
        )

    def get_list_queryset(self, request: Any) -> QuerySet:
        # Which file each row's reader reads: the working one for its
        # authors and whoever a review asks, the published one for
        # everyone else (preview.readable, for the whole page at once).
        user = getattr(request, "user", None)
        has_file = ~Q(file="")

        if versions.sees_all_drafts(user):
            drafts: Any = has_file
        else:
            drafts = has_file & Exists(
                ReviewTask.objects.filter(
                    document=OuterRef("pk"),
                    assignee=getattr(user, "pk", None),
                )
            )

        return (
            super()
            .get_list_queryset(request)
            .annotate(
                reads=Case(
                    When(drafts, then=Value("file")),
                    When(
                        published_version__isnull=False,
                        then=Value("published_file"),
                    ),
                    default=Value(""),
                    output_field=CharField(),
                )
            )
        )

    @display(description=_("File"), icons=True)
    def shortcuts(self, document: Document) -> list[dict]:
        field = getattr(document, "reads", "")

        if not field:
            return []

        return [
            {
                "icon": "visibility",
                "label": gettext("Preview"),
                "url": self.get_page_url("preview", document),
            },
            {
                "icon": "download",
                "label": gettext("Download"),
                "url": self.get_file_url(document.pk, field),
            },
        ]

    @display(description=_("Size"))
    def size(self, document: Document) -> str:
        return human_size(document.file_size)

    @display(description=_("Tasks to do"))
    def open_tasks(self, document: Document) -> int:
        return ReviewTask.objects.filter(
            review__document=document, status=ReviewTask.Status.PENDING
        ).count()

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        upload = serializer.validated_data.get("file")
        note = serializer.extra_values.get("version_note", "")
        number = serializer.extra_values.get("codify", False)
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
            tell_checked_out(document, request.user)

        if not document.code and (
            number
            or (not change and codification.numbered_on_create(document))
        ):
            codification.codify(document)
            document.refresh_from_db()

        return document

    def get_download_name(self, request: Any, obj: Any, field: str) -> str:
        if field == "published_file":
            published = obj.published_version

            if published is None:
                return ""

            if published.stamped:
                return published.stamped.name.rsplit("/", 1)[-1]

            return published.file_name

        current = obj.versions.filter(number=obj.version).first()

        return current.file_name if current else ""

    def may_download(self, request: Any, obj: Any, field: str) -> bool:
        # The working file is its authors' - and of whoever a review
        # asks; everyone else reads the published version.
        if field == "file":
            return versions.sees_drafts(request.user, obj)

        return True

    def delete_model(self, request: Any, obj: Any) -> None:
        from generic.trash import in_trash

        # Into the trash: nobody is asked about it any more.
        if not in_trash(request):
            workflows.close_for(obj, user=request.user)

        super().delete_model(request, obj)

    @page(
        title=_("Preview"),
        detail=True,
        icon="visibility",
        row_menu=True,
        template="documents/preview.html",
    )
    def preview(self, request: Any, document: Document) -> dict:
        return {
            "shown": preview.shown(request, document),
            "file_url": self.get_page_url("preview-file", document),
        }

    @page(title=_("Previewed file"), detail=True, button=False)
    def preview_file(self, request: Any, document: Document) -> Any:
        return preview.file_response(request, document)

    @action(
        description=_("Approve"),
        icon="verified",
        permissions=("change",),
        confirm=_("Approve the selected documents?"),
    )
    def approve(self, request: Any, queryset: Any) -> str:
        count = 0

        # One by one rather than update(): each keeps its history entry
        # and tells whoever watches it. Its current version becomes the
        # published one - a draft sent after the last approval too.
        for document in queryset:
            published = document.published_version_id
            changed = document.status != Document.Status.APPROVED

            if changed:
                document.status = Document.Status.APPROVED
                document.save(update_fields=("status", "updated_at"))

            version = versions.publish(document, user=request.user)
            changed |= version is not None and version.pk != published
            count += changed

        return gettext("%(count)s approved.") % {"count": count}

    @action(
        description=_("Send for review"),
        icon="rule",
        permissions=("view",),
    )
    def send_for_review(self, request: Any, queryset: Any) -> dict:
        chosen = list(queryset.values_list("pk", flat=True)[:2])

        if len(chosen) != 1:
            return {
                "message": gettext("Choose one document to send for review."),
                "level": "warning",
            }

        reviews = site.get_resource(Review)

        if not reviews.has_add_permission(request):
            return {
                "message": gettext("You may not start a review."),
                "level": "error",
            }

        return {"redirect": f"{reviews.get_add_url()}?document={chosen[0]}"}

    @action(
        description=_("Codify"),
        icon="pin",
        permissions=("change",),
        confirm=_(
            "Give the selected documents their numbers? A number is "
            "never changed."
        ),
    )
    def codify(self, request: Any, queryset: Any) -> dict:
        numbers = [
            codification.codify(document)
            for document in queryset.filter(code__isnull=True).select_related(
                "folder__team"
            )
        ]

        if not numbers:
            return {
                "message": gettext("They are numbered already."),
                "level": "info",
            }

        return {
            "message": gettext("Numbered: %(numbers)s.")
            % {"numbers": ", ".join(numbers)},
            "level": "success",
        }

    @action(
        description=_("Check out"),
        icon="edit_document",
        permissions=("change",),
    )
    def check_out(self, request: Any, queryset: Any) -> dict:
        taken = 0
        held = []

        for document in queryset:
            if document.checked_out_by_id not in (None, request.user.pk):
                held.append(str(document))
                continue

            document.checked_out_by = request.user
            document.checked_out_at = timezone.now()
            document.save(
                update_fields=(
                    "checked_out_by",
                    "checked_out_at",
                    "updated_at",
                )
            )
            taken += 1

        message = gettext(
            "%(count)s checked out: the others see you are working on it."
        ) % {"count": taken}

        if held:
            message += " " + gettext(
                "Already checked out by someone else: %(documents)s."
            ) % {"documents": ", ".join(held)}

        return {"message": message, "level": "warning" if held else "success"}

    @action(
        description=_("Check in"),
        icon="assignment_turned_in",
        permissions=("change",),
    )
    def check_in(self, request: Any, queryset: Any) -> str:
        count = 0

        # Anyone may give a document back: a check-out is a notice,
        # never a lock someone on holiday keeps.
        for document in queryset.filter(checked_out_by__isnull=False):
            holder = document.checked_out_by
            document.checked_out_by = None
            document.checked_out_at = None
            document.save(
                update_fields=(
                    "checked_out_by",
                    "checked_out_at",
                    "updated_at",
                )
            )
            count += 1

            if holder.pk != request.user.pk:
                workflows.tell(
                    [holder],
                    lambda document=document: (
                        gettext("%(document)s was checked in")
                        % {"document": document},
                        gettext("%(who)s checked it in for you.")
                        % {"who": workflows.name_of(request.user)},
                        NotificationLevel.INFO,
                    ),
                    url=self.get_detail_url(document.pk),
                    about=document,
                )

        return gettext("%(count)s checked in.") % {"count": count}

    @action(
        description=_("Make obsolete"),
        icon="block",
        permissions=("change",),
        confirm=_("Mark the selected documents obsolete? They stay here."),
        variant="danger",
    )
    def make_obsolete(self, request: Any, queryset: Any) -> str:
        count = 0

        for document in queryset.exclude(status=Document.Status.OBSOLETE):
            document.status = Document.Status.OBSOLETE
            document.save(update_fields=("status", "updated_at"))
            count += 1

        return gettext("%(count)s made obsolete.") % {"count": count}

    @action(
        description=_("Merge into Word"),
        icon="merge_type",
        permissions=("view",),
    )
    def merge_word(self, request: Any, queryset: Any) -> dict:
        return merge_page_for(queryset, "d")

    @page(
        title=_("Merge Word files"),
        icon="merge_type",
        description=_(
            "Documents and versions put together into one Word file, "
            "with a template."
        ),
        navigation=True,
        methods=("get", "post"),
        template="documents/merge.html",
    )
    def merge(self, request: Any) -> Any:
        if request.method == "POST":
            return merging.merge(request)

        return merging.page_context(request, request.GET)


@register(DocumentVersion)
class DocumentVersionResource(LiveDocuments, ModelResource):
    icon = "history"
    group = GROUP
    order = 2
    label_plural = _("versions")
    description = _("Every file sent, in every document.")

    team_field = "document__folder__team"
    access_log = True

    list_display = (
        "document",
        "label",
        "file",
        "comment",
        "published_at",
        "created_by",
        "created_at",
        "file_format",
        "size",
    )
    search_fields = (
        "document__reference",
        "document__title",
        "comment",
        "file_name",
        "file_format",
        "content",
    )
    ordering = ("-created_at", "-number")
    fields = ("document", "file", "comment")
    form_overrides = {"comment": {"rows": 3}}
    detail_stats = ("label", "file_format", "size")
    detail_fieldsets = (
        (None, {"fields": ("document", "file", "comment")}),
        (
            _("Approval"),
            {"fields": ("published_at", "published_by", "stamped")},
        ),
        (
            _("File"),
            {
                "fields": (
                    "number",
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
        "label",
        "file_name",
        "content_type",
        "checksum",
        "created_by",
        "created_at",
    )
    presets = {
        _("Word files"): WORD_FILES,
        _("Published"): matching(condition("published_at", "not_empty")),
    }
    actions = ("restore", "merge_word")
    # A version is what was sent: the document's history says the rest.
    history = False

    @display(description=_("Size"), ordering="file_size")
    def size(self, version: DocumentVersion) -> str:
        return human_size(version.file_size)

    def get_queryset(self, request: Any) -> QuerySet:
        queryset = super().get_queryset(request)
        user = getattr(request, "user", None)

        if versions.sees_all_drafts(user):
            return queryset

        # Readers read published versions - and the drafts of what a
        # review asks them about.
        return queryset.filter(
            Q(published_at__isnull=False)
            | Q(document__tasks__assignee=getattr(user, "pk", None))
        ).distinct()

    def may_download(self, request: Any, obj: Any, field: str) -> bool:
        return obj.is_published or versions.sees_drafts(
            request.user, obj.document
        )

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
        version = versions.complete(version, upload=upload)
        tell_checked_out(version.document, request.user)

        return version

    def get_download_name(self, request: Any, obj: Any, field: str) -> str:
        if field == "stamped" and obj.stamped:
            return obj.stamped.name.rsplit("/", 1)[-1]

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
            % {"document": restored.document, "number": restored.label},
            "level": "success",
        }

    @action(
        description=_("Merge into Word"),
        icon="merge_type",
        permissions=("view",),
    )
    def merge_word(self, request: Any, queryset: Any) -> dict:
        return merge_page_for(queryset, "v")


def tell_checked_out(document: Document, user: Any) -> None:
    """A new version of a document someone else checked out: they are
    told, nobody is stopped."""
    holder = document.checked_out_by

    if holder is None or holder.pk == getattr(user, "pk", None):
        return

    workflows.tell(
        [holder],
        lambda: (
            gettext("New version of %(document)s") % {"document": document},
            gettext(
                "%(who)s sent version %(number)s while you had it "
                "checked out."
            )
            % {"who": workflows.name_of(user), "number": document.version},
            NotificationLevel.WARNING,
        ),
        url=site.get_resource(Document).get_detail_url(document.pk),
        about=document,
    )


@register(Comment)
class CommentResource(LiveDocuments, ModelResource):
    icon = "forum"
    group = GROUP
    order = 4
    show_in_navigation = False

    team_field = "document__folder__team"

    list_display = ("body", "author", "created_at")
    search_fields = ("body",)
    fields = ("document", "body")
    form_overrides = {"body": {"rows": 3}}
    detail_fieldsets = ((None, {"fields": ("document", "body", "author")}),)
    history = False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        # One's own words only; nobody rewrites another's.
        allowed = super().has_change_permission(request, obj)

        return allowed and (obj is None or obj.author_id == request.user.pk)

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        return serializer.save(**({} if change else {"author": request.user}))


# -- reviews ------------------------------------------------------------------

REVIEW_COLORS = {
    Review.Status.PREPARING: "#64748b",
    Review.Status.IN_PROGRESS: "#d97706",
    Review.Status.APPROVED: "#16a34a",
    Review.Status.REJECTED: "#dc2626",
    Review.Status.CANCELLED: "#991b1b",
}
STEP_COLORS = {
    ReviewStep.Status.WAITING: "#64748b",
    ReviewStep.Status.ACTIVE: "#d97706",
    ReviewStep.Status.DONE: "#16a34a",
    ReviewStep.Status.REJECTED: "#dc2626",
    ReviewStep.Status.SKIPPED: "#94a3b8",
}
TASK_COLORS = {
    ReviewTask.Status.PENDING: "#d97706",
    ReviewTask.Status.APPROVED: "#16a34a",
    ReviewTask.Status.REJECTED: "#dc2626",
    ReviewTask.Status.DELEGATED: "#7c3aed",
    ReviewTask.Status.SKIPPED: "#94a3b8",
}
KIND_COLORS = {
    StepKind.REVIEW: "#0891b2",
    StepKind.APPROVAL: "#16a34a",
    StepKind.ACKNOWLEDGEMENT: "#7c3aed",
}

STEP_LAYOUT = (
    ("position", "name"),
    ("kind", "rule"),
    "users",
    "groups",
    ("team_leaders", "team_members"),
    "days",
)


def people_of(step: Any) -> str:
    """``Alice, Legal reviewers (role), the team's leaders``."""
    names = [
        user.get_full_name() or user.get_username()
        for user in step.users.all()
    ]
    names += [
        gettext("%(group)s (role)") % {"group": group}
        for group in step.groups.all()
    ]

    if step.team_leaders:
        names.append(gettext("the team's leaders"))

    if step.team_members:
        names.append(gettext("the team's members"))

    return ", ".join(names) or "-"


class WorkflowStepInline(StackedInline):
    model = WorkflowStep
    fields = (
        "position",
        "name",
        "kind",
        "rule",
        "users",
        "groups",
        "team_leaders",
        "team_members",
        "days",
    )
    extra = 0


@register(Workflow)
class WorkflowResource(ModelResource):
    icon = "account_tree"
    group = REVIEWS
    order = 3
    description = _(
        "Review circuits: steps of reviewing, approving or reading, "
        "each asking people, roles or the team's leaders. Anyone may "
        "draw their own."
    )

    list_display = ("name", "team", "steps_summary", "is_active", "created_by")
    search_fields = ("name", "description")
    tag_fields = {"team": TagStyle(color="color")}
    scope_relations = True
    fieldsets = (
        (None, {"fields": (("name", "team"), "is_active", "description")}),
    )
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "team",
                    "is_active",
                    "description",
                    "steps_summary",
                    "created_by",
                )
            },
        ),
    )
    readonly_fields = ("created_by",)
    inlines = (WorkflowStepInline,)
    related_tables = (RelatedTable("reviews", icon="rule"),)

    def get_queryset(self, request: Any) -> QuerySet:
        user = getattr(request, "user", None)
        queryset = super().get_queryset(request)

        if sees_every_team(user):
            return queryset

        # Everyone's, their teams', and their own.
        return queryset.filter(
            Q(team__isnull=True)
            | Q(team__in=teams_of(user).values("pk"))
            | Q(created_by=getattr(user, "pk", None))
        )

    def get_relation_queryset(self, request: Any) -> QuerySet:
        return self.get_queryset(request).filter(is_active=True)

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        return serializer.save(
            **({} if change else {"created_by": request.user})
        )

    @display(description=_("Steps"))
    def steps_summary(self, workflow: Workflow) -> str:
        return " > ".join(
            f"{step.name} ({step.get_kind_display()})"
            for step in workflow.steps.all()
        )


class ReviewStepInline(StackedInline):
    model = ReviewStep
    fields = WorkflowStepInline.fields
    extra = 0
    verbose_name_plural = _("Steps")
    description = _(
        "Copied from the workflow when one is chosen; add, change or "
        "remove them until the review starts. After, its Steps tab."
    )

    def has_add_permission(self, request: Any, obj: Any = None) -> bool:
        return preparing(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return preparing(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return preparing(obj) and super().has_delete_permission(request, obj)


def preparing(review: Any) -> bool:
    return review is None or review.status == Review.Status.PREPARING


def answer(error: workflows.WorkflowError) -> dict:
    return {"message": str(error), "level": "error"}


@register(Review)
class ReviewResource(LiveDocuments, ModelResource):
    icon = "rule"
    group = REVIEWS
    order = 1
    description = _("Documents going through a review circuit.")

    team_field = "document__folder__team"

    list_display = (
        "document",
        "workflow",
        "status",
        "current_step",
        "progress",
        "started_by",
        "started_at",
        "finished_at",
    )
    search_fields = ("document__title", "document__code", "message")
    ordering = ("-created_at", "-pk")
    tag_fields = {"status": TagStyle(colors=REVIEW_COLORS)}
    presets = {
        _("In progress"): matching(
            condition("status", "any_of", [Review.Status.IN_PROGRESS])
        ),
    }
    actions = ("start_review", "skip_step", "remind", "cancel_review")

    fieldsets = (
        (None, {"fields": ("document", "workflow", "message", "start")}),
    )
    form_extra_fields = {
        "start": serializers.BooleanField(
            label=_("Start now"),
            help_text=_(
                "Untick to prepare it first: its steps may be changed "
                "until it starts."
            ),
            required=False,
            default=True,
        )
    }
    form_overrides = {"message": {"rows": 3}}
    inlines = (ReviewStepInline,)

    detail_stats = ("status", "progress", "version")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "document",
                    "workflow",
                    "current_step",
                    "message",
                    "started_by",
                    "started_at",
                    "finished_at",
                )
            },
        ),
    )
    readonly_fields = ("started_by", "started_at", "finished_at")
    related_tables = (
        RelatedTable("steps", icon="format_list_numbered"),
        RelatedTable("tasks", icon="task_alt"),
    )
    charts = (
        Chart(
            "by_status",
            title=_("Reviews by status"),
            type="donut",
            group_by="status",
        ),
    )
    list_charts = ("by_status",)

    def scope_to_teams(self, request: Any, queryset: QuerySet) -> QuerySet:
        user = getattr(request, "user", None)
        key = getattr(user, "pk", None)

        return widened(
            queryset,
            super().scope_to_teams(request, queryset),
            Q(tasks__assignee=key) | Q(started_by=key),
        )

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        # Its form is for preparing it; once started, its steps tab and
        # its actions steer it.
        allowed = super().has_change_permission(request, obj)

        return allowed and preparing(obj)

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        start = serializer.extra_values.get("start", False)
        review = serializer.save(
            **({} if change else {"started_by": request.user})
        )

        if not change and review.workflow_id and not review.steps.exists():
            workflows.copy_steps(review, review.workflow.steps.all())

        if start:
            # Once the steps drawn in the form are saved too.
            user = request.user
            transaction.on_commit(lambda: start_quietly(review, user))

        return review

    @display(description=_("Current step"))
    def current_step(self, review: Review) -> str:
        step = review.steps.filter(status=ReviewStep.Status.ACTIVE).first()

        return str(step.name) if step else "-"

    @display(description=_("Progress"))
    def progress(self, review: Review) -> str:
        steps = list(review.steps.values_list("status", flat=True))
        over = [
            status
            for status in steps
            if status
            in (
                ReviewStep.Status.DONE,
                ReviewStep.Status.SKIPPED,
                ReviewStep.Status.REJECTED,
            )
        ]

        return f"{len(over)}/{len(steps)}"

    def steered(self, request: Any, queryset: Any, run: Any) -> dict:
        done, refused = 0, []

        for review in queryset:
            try:
                run(review, user=request.user)
                done += 1
            except workflows.WorkflowError as error:
                refused.append(f"{review.document}: {error}")

        if refused:
            return {
                "message": " ".join(
                    [gettext("%(count)s done.") % {"count": done}, *refused]
                ),
                "level": "warning" if done else "error",
            }

        return {
            "message": gettext("%(count)s done.") % {"count": done},
            "level": "success",
        }

    @action(description=_("Start"), icon="play_arrow", permissions=("view",))
    def start_review(self, request: Any, queryset: Any) -> dict:
        def run(review: Review, user: Any) -> None:
            if not workflows.may_steer(user, review):
                raise workflows.WorkflowError(
                    gettext("Only whoever prepared it may start it.")
                )

            workflows.start(review, user=user)

        return self.steered(request, queryset, run)

    @action(
        description=_("Skip the current step"),
        icon="skip_next",
        permissions=("view",),
        confirm=_("Close the current step without waiting, and go on?"),
    )
    def skip_step(self, request: Any, queryset: Any) -> dict:
        return self.steered(request, queryset, workflows.skip_step)

    @action(
        description=_("Remind"), icon="notifications", permissions=("view",)
    )
    def remind(self, request: Any, queryset: Any) -> dict:
        count = workflows.remind(
            ReviewTask.objects.filter(
                review__in=queryset, status=ReviewTask.Status.PENDING
            ).select_related("review__document", "step", "assignee")
        )

        return {
            "message": gettext("%(count)s people reminded.")
            % {"count": count},
            "level": "success" if count else "info",
        }

    @action(
        description=_("Cancel the review"),
        icon="cancel",
        permissions=("view",),
        confirm=_("Cancel the selected reviews? The document stays."),
        variant="danger",
    )
    def cancel_review(self, request: Any, queryset: Any) -> dict:
        return self.steered(request, queryset, workflows.cancel)


def start_quietly(review: Review, user: Any) -> None:
    """Start a review just saved; one that cannot start yet - no step -
    stays prepared, and its page says why when *Start* is asked."""
    try:
        workflows.start(review, user=user)
    except workflows.WorkflowError:
        pass


@register(ReviewStep)
class ReviewStepResource(LiveDocuments, ModelResource):
    icon = "format_list_numbered"
    group = REVIEWS
    order = 4
    show_in_navigation = False
    label_plural = _("review steps")
    document_path = "review__document"

    team_field = "review__document__folder__team"

    list_display = (
        "position",
        "name",
        "kind",
        "rule",
        "people",
        "status",
        "due_on",
        "finished_at",
    )
    search_fields = ("name",)
    ordering = ("position", "pk")
    tag_fields = {
        "status": TagStyle(colors=STEP_COLORS),
        "kind": TagStyle(colors=KIND_COLORS),
    }
    fieldsets = ((None, {"fields": ("review", *STEP_LAYOUT)}),)
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "review",
                    "name",
                    "kind",
                    "rule",
                    "people",
                    "status",
                    "due_on",
                    "started_at",
                    "finished_at",
                )
            },
        ),
    )
    related_tables = (RelatedTable("tasks", icon="task_alt"),)
    history = False

    def scope_to_teams(self, request: Any, queryset: QuerySet) -> QuerySet:
        user = getattr(request, "user", None)
        key = getattr(user, "pk", None)

        return widened(
            queryset,
            super().scope_to_teams(request, queryset),
            Q(review__tasks__assignee=key) | Q(review__started_by=key),
        )

    @display(description=_("Asks"))
    def people(self, step: ReviewStep) -> str:
        return people_of(step)

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        allowed = super().has_change_permission(request, obj)

        if obj is None or not allowed:
            return allowed

        return (
            obj.status in (ReviewStep.Status.WAITING, ReviewStep.Status.ACTIVE)
            and obj.review.is_open
            and workflows.may_steer(request.user, obj.review)
        )

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        allowed = super().has_delete_permission(request, obj)

        if obj is None or not allowed:
            return allowed

        return obj.status == ReviewStep.Status.WAITING and (
            obj.review.status == Review.Status.PREPARING
            or workflows.may_steer(request.user, obj.review)
        )

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        review = serializer.validated_data.get("review") or (
            serializer.instance.review
        )

        if not review.is_open:
            raise serializers.ValidationError(
                {"review": [gettext("This review is already over.")]}
            )

        if review.status != Review.Status.PREPARING and not (
            workflows.may_steer(request.user, review)
        ):
            raise serializers.ValidationError(
                {
                    "review": [
                        gettext(
                            "Only whoever started the review, the team's "
                            "leaders and the managers may change its steps."
                        )
                    ]
                }
            )

        step = serializer.save()

        if step.status == ReviewStep.Status.ACTIVE:
            transaction.on_commit(lambda: workflows.refresh(step))

        return step


@register(ReviewTask)
class ReviewTaskResource(LiveDocuments, ModelResource):
    icon = "task_alt"
    group = REVIEWS
    order = 0
    label_plural = _("tasks")
    description = _(
        "What is asked of each person: review, approve, read. Yours "
        "are under My tasks."
    )

    team_field = "document__folder__team"

    list_display = (
        "document",
        "step__name",
        "step__kind",
        "assignee",
        "status",
        "due_on",
        "created_at",
        "decided_at",
        "comment",
        "mine",
    )
    list_display_links = ("step__name",)
    search_fields = (
        "document__title",
        "document__code",
        "step__name",
        "comment",
    )
    ordering = ("-created_at", "-pk")
    tag_fields = {
        "status": TagStyle(colors=TASK_COLORS),
        "step__kind": TagStyle(colors=KIND_COLORS),
    }
    presets = {
        _("My tasks"): {
            "columns": [
                "document",
                "step__name",
                "step__kind",
                "status",
                "due_on",
                "created_at",
            ],
            **matching(
                condition("mine", "is_true"),
                condition("status", "any_of", [ReviewTask.Status.PENDING]),
            ),
            "order": [["due_on", "asc"]],
        },
        _("To do"): matching(
            condition("status", "any_of", [ReviewTask.Status.PENDING])
        ),
    }
    actions = ("approve_tasks", "reject_tasks", "remind_tasks")

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "document",
                    "review",
                    "step",
                    "instructions",
                    "assignee",
                    "status",
                    "due_on",
                )
            },
        ),
        (
            _("Your answer"),
            {
                "fields": ("decision", "comment", "delegate_to"),
                "description": _(
                    "Approve (reviewed, read) or reject - or hand it to "
                    "someone else."
                ),
            },
        ),
    )
    form_extra_fields = {
        "decision": serializers.ChoiceField(
            label=_("Answer"),
            choices=(
                ("approve", _("Approve - reviewed, read")),
                ("reject", _("Reject - changes needed")),
            ),
            required=False,
            allow_blank=True,
        ),
        "delegate_to": serializers.PrimaryKeyRelatedField(
            label=_("Or hand it to"),
            queryset=get_user_model()._default_manager.filter(is_active=True),
            required=False,
            allow_null=True,
        ),
    }
    form_overrides = {"comment": {"rows": 4}}
    readonly_fields = (
        "document",
        "review",
        "step",
        "instructions",
        "assignee",
        "status",
        "due_on",
    )
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "document",
                    "review",
                    "step",
                    "instructions",
                    "assignee",
                    "status",
                    "due_on",
                    "comment",
                    "decided_by",
                    "decided_at",
                    "delegated_to",
                )
            },
        ),
    )
    history = False

    def scope_to_teams(self, request: Any, queryset: QuerySet) -> QuerySet:
        user = getattr(request, "user", None)

        return widened(
            queryset,
            super().scope_to_teams(request, queryset),
            Q(assignee=getattr(user, "pk", None)),
        )

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                is_mine=Case(
                    When(
                        assignee=getattr(request.user, "pk", None),
                        then=Value(True),
                    ),
                    default=Value(False),
                    output_field=BooleanField(),
                )
            )
        )

    # Everyone signed in may have tasks: the rows say which.
    def has_view_permission(self, request: Any, obj: Any = None) -> bool:
        return bool(getattr(request.user, "is_authenticated", False))

    def has_module_permission(self, request: Any) -> bool:
        return self.has_view_permission(request)

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        if obj is None:
            return self.has_view_permission(request)

        return workflows.may_answer(request.user, obj)

    def get_record_links(self, request: Any, obj: Any) -> list[Any]:
        from generic.views.toolbar import ToolbarItem

        if not workflows.may_answer(request.user, obj):
            return []

        return [
            ToolbarItem(
                url=self.get_change_url(obj.pk),
                label=gettext("Answer"),
                icon="rate_review",
                variant="primary",
            )
        ]

    @display(description=_("Instructions"))
    def instructions(self, task: ReviewTask) -> str:
        return task.review.message or "-"

    @display(
        description=_("Mine"),
        boolean=True,
        filter_field="is_mine",
        filter_type="boolean",
    )
    def mine(self, task: ReviewTask) -> bool:
        return bool(getattr(task, "is_mine", False))

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        task = serializer.instance
        values = serializer.extra_values
        comment = serializer.validated_data.get("comment", "")
        to = values.get("delegate_to")
        decision = values.get("decision") or ""

        try:
            if to is not None:
                return workflows.delegate(task, user=request.user, to=to)

            if not decision:
                raise serializers.ValidationError(
                    {"decision": [gettext("Choose an answer.")]}
                )

            return workflows.decide(
                task,
                user=request.user,
                approve=decision == "approve",
                comment=comment,
            )
        except workflows.WorkflowError as error:
            raise serializers.ValidationError({"decision": [str(error)]})

    def answered(self, request: Any, queryset: Any, approve: bool) -> dict:
        done, refused = 0, 0

        for task in queryset.select_related("review", "step"):
            try:
                workflows.decide(task, user=request.user, approve=approve)
                done += 1
            except workflows.WorkflowError:
                refused += 1

        message = gettext("%(count)s answered.") % {"count": done}

        if refused:
            message += " " + gettext(
                "%(count)s left: answered already, or not yours."
            ) % {"count": refused}

        return {
            "message": message,
            "level": "warning" if refused else "success",
        }

    @action(description=_("Approve"), icon="thumb_up", permissions=("view",))
    def approve_tasks(self, request: Any, queryset: Any) -> dict:
        return self.answered(request, queryset, True)

    @action(
        description=_("Reject"),
        icon="thumb_down",
        permissions=("view",),
        confirm=_("Reject? The review ends there. Open the task to say why."),
        variant="danger",
    )
    def reject_tasks(self, request: Any, queryset: Any) -> dict:
        return self.answered(request, queryset, False)

    @action(
        description=_("Remind"), icon="notifications", permissions=("view",)
    )
    def remind_tasks(self, request: Any, queryset: Any) -> dict:
        count = workflows.remind(
            queryset.filter(status=ReviewTask.Status.PENDING).select_related(
                "review__document", "step", "assignee"
            )
        )

        return {
            "message": gettext("%(count)s people reminded.")
            % {"count": count},
            "level": "success" if count else "info",
        }


def merge_page_for(queryset: Any, kind: str) -> dict:
    """The *Merge into Word* actions: the merge page, opened with the
    selection's Word files chosen, in the list's order."""
    keys = [
        f"{kind}{pk}"
        for pk in queryset.filter(
            file_format__in=merging.WORD_FORMATS
        ).values_list("pk", flat=True)[: merging.MAX_ITEMS]
    ]

    if not keys:
        return {
            "message": gettext("None of the selected files is a Word file."),
            "level": "warning",
        }

    url = site.get_resource(Document).get_page_url("merge")

    return {"redirect": f"{url}?items={','.join(keys)}"}


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
MY_TASKS = (
    '/documents/reviewtask/?filters={"match":"all","conditions":['
    '{"column":"mine","operator":"is_true"},'
    '{"column":"status","operator":"any_of","value":["pending"]}]}'
)

site.add_shortcut(
    _("My tasks"),
    url=MY_TASKS,
    icon="task_alt",
    description=_("Documents waiting for your review, approval or reading."),
    count=lambda request: ReviewTask.objects.filter(
        assignee=request.user.pk,
        status=ReviewTask.Status.PENDING,
        document__deleted_at__isnull=True,
    ).count(),
    order=-1,
)
site.add_shortcut(
    _("Reviews in progress"),
    url='/documents/review/?filters={"match":"all","conditions":'
    '[{"column":"status","operator":"any_of","value":["in_progress"]}]}',
    icon="rule",
    description=_("Documents going through their circuits."),
    count=lambda request: site.get_resource(Review)
    .get_queryset(request)
    .filter(status=Review.Status.IN_PROGRESS)
    .count(),
    permission="documents.view_review",
)
site.add_shortcut(
    _("Merge Word files"),
    url="/documents/document/merge/",
    icon="merge_type",
    description=_("Documents and versions put together with a template."),
    permission="documents.view_document",
)

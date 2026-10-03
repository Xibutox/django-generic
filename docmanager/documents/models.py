"""Folders, documents and the versions of their files.

* A **folder** belongs to a team (``generic_teams.Team``); its
  documents are that team's, and only its members - and whoever sees
  every team - reach them.
* A **document** is what people look for: a title, a type, a status,
  tags, and its current file - or none yet: a document may be only a
  number, *codified* before it is written (``codification.py``).
* A **team wiki** says a wiki is one team's: only its members - and
  whoever sees every team - read it (``documents/wikis.py``, plugged in
  as ``GENERIC["WIKI_ACCESS"]``). A wiki of no team is everyone's.
* A **version** is one file the document has had, with who sent it,
  when, and why. A document's file is always its latest version's;
  versions are never changed, only added - restoring an old one adds a
  new one.
* A **workflow** is a review circuit anyone may draw: steps of
  reviewing, approving or reading, each naming people, groups, or the
  team's leaders or members. A **review** is one document going
  through one - its steps copied, so they may still be changed - and a
  **task** is what one person is asked to do at one step
  (``workflows.py`` runs them).
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from generic.numbering import Pattern
from generic.teams.models import Team
from generic.wiki.models import Wiki

#: What a team's numbers look like until it says otherwise.
DEFAULT_PATTERN = "{team}-{type}-{year}-{seq:04}"

#: The fields a numbering pattern may use, beside the date and {seq}.
PATTERN_FIELDS = ("team", "type")


def validate_pattern(value: str) -> None:
    Pattern(value, fields=PATTERN_FIELDS).validate()


def file_path(instance: models.Model, filename: str) -> str:
    """``documents/2026/10/3f2a9c4e1b7d/report.docx``.

    A folder of its own per file, so the name it was sent with is kept
    as it is: two versions of ``report.docx`` never become
    ``report_x7Gq2.docx``.
    """
    folder = timezone.now().strftime("documents/%Y/%m/")

    return f"{folder}{uuid.uuid4().hex[:12]}/{filename}"


def extension_of(name: str) -> str:
    """``"DOCX"`` for ``report.docx``; ``""`` for a name without one."""
    return PurePosixPath(name or "").suffix.lstrip(".").upper()[:10]


class Folder(models.Model):
    team = models.ForeignKey(
        Team,
        verbose_name=_("team"),
        # A team's folders stay until they are moved or emptied.
        on_delete=models.PROTECT,
        related_name="folders",
    )
    name = models.CharField(_("name"), max_length=120)
    description = models.TextField(_("description"), blank=True, default="")

    class Meta:
        ordering = ("team__name", "name")
        verbose_name = _("folder")
        verbose_name_plural = _("folders")
        constraints = (
            models.UniqueConstraint(
                fields=("team", "name"), name="documents_folder_unique_name"
            ),
        )

    def __str__(self) -> str:
        return f"{self.team} / {self.name}"


class Tag(models.Model):
    name = models.CharField(_("name"), max_length=60, unique=True)
    color = models.CharField(_("colour"), max_length=30, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("tag")
        verbose_name_plural = _("tags")

    def __str__(self) -> str:
        return self.name


class DocumentType(models.Model):
    """What kind of document it is - a contract, a procedure - and the
    code its numbers carry (``{type}``)."""

    name = models.CharField(_("name"), max_length=100, unique=True)
    code = models.CharField(
        _("code"),
        max_length=10,
        unique=True,
        help_text=_("Short, in the numbers: CTR, PRC..."),
    )
    color = models.CharField(_("colour"), max_length=30, blank=True)
    description = models.TextField(_("description"), blank=True, default="")

    class Meta:
        ordering = ("name",)
        verbose_name = _("document type")
        verbose_name_plural = _("document types")

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class Codification(models.Model):
    """How a team numbers its documents."""

    team = models.OneToOneField(
        Team,
        verbose_name=_("team"),
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="codification",
    )
    code = models.CharField(
        _("team code"),
        max_length=10,
        help_text=_("Short, in the numbers ({team}): LEG, ENG..."),
    )
    pattern = models.CharField(
        _("pattern"),
        max_length=120,
        default=DEFAULT_PATTERN,
        validators=[validate_pattern],
        help_text=_(
            "{team}, {type}, {year}, {yy}, {month}, {day} and the "
            "running number {seq} - {seq:04} pads it to four digits. "
            "Each series counts on its own: with {year}, from 1 again "
            "every year."
        ),
    )
    on_create = models.BooleanField(
        _("number every new document"),
        default=False,
        help_text=_("Otherwise a document is numbered when asked (Codify)."),
    )

    class Meta:
        ordering = ("team__name",)
        verbose_name = _("codification")
        verbose_name_plural = _("codifications")

    def __str__(self) -> str:
        return f"{self.team}: {self.pattern}"

    def save(self, *args, **kwargs) -> None:
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class Document(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        REVIEW = "review", _("In review")
        APPROVED = "approved", _("Approved")
        OBSOLETE = "obsolete", _("Obsolete")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, editable=False
    )
    #: The number given by the team's codification, once asked for.
    code = models.CharField(
        _("number"),
        max_length=60,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    codified_at = models.DateTimeField(
        _("numbered at"), null=True, blank=True, editable=False
    )
    title = models.CharField(_("title"), max_length=200)
    document_type = models.ForeignKey(
        DocumentType,
        verbose_name=_("type"),
        on_delete=models.PROTECT,
        related_name="documents",
        null=True,
        blank=True,
    )
    folder = models.ForeignKey(
        Folder,
        verbose_name=_("folder"),
        on_delete=models.PROTECT,
        related_name="documents",
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    tags = models.ManyToManyField(
        Tag, verbose_name=_("tags"), related_name="documents", blank=True
    )
    description = models.TextField(_("description"), blank=True, default="")
    #: The latest version's file. Replacing it adds a version. None yet
    #: for a document only numbered so far.
    file = models.FileField(
        _("file"), upload_to=file_path, max_length=255, blank=True
    )
    version = models.PositiveIntegerField(
        _("version"), default=0, editable=False
    )
    file_size = models.PositiveBigIntegerField(
        _("size"), default=0, editable=False
    )
    #: The file's extension, upper case - ``DOCX``, ``PDF`` - kept as a
    #: field so that lists filter, search and count by it.
    file_format = models.CharField(
        _("format"), max_length=10, blank=True, db_index=True, editable=False
    )
    review_on = models.DateField(
        _("next review on"),
        null=True,
        blank=True,
        help_text=_("When the document should be read again."),
    )
    related = models.ManyToManyField(
        "self",
        verbose_name=_("related documents"),
        blank=True,
    )
    #: Who said they are working on the file. A notice to the others,
    #: never a lock: anyone may still send a version.
    checked_out_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("checked out by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
    )
    checked_out_at = models.DateTimeField(
        _("checked out at"), null=True, blank=True, editable=False
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField(
        _("created at"), default=timezone.now, editable=False
    )
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-pk")
        verbose_name = _("document")
        verbose_name_plural = _("documents")

    def __str__(self) -> str:
        if not self.reference:
            return self.title

        return f"{self.code or self.reference} {self.title}"

    def save(self, *args, **kwargs) -> None:
        self.file_format = extension_of(self.file.name)
        super().save(*args, **kwargs)

        # Numbered by its key, once it has one.
        if not self.reference:
            self.reference = f"DOC-{self.pk:05d}"
            type(self).objects.filter(pk=self.pk).update(
                reference=self.reference
            )

    @property
    def team(self) -> Team:
        return self.folder.team


class DocumentVersion(models.Model):
    document = models.ForeignKey(
        Document,
        verbose_name=_("document"),
        on_delete=models.CASCADE,
        related_name="versions",
    )
    number = models.PositiveIntegerField(_("version"), editable=False)
    file = models.FileField(_("file"), upload_to=file_path, max_length=255)
    comment = models.TextField(
        _("change note"),
        blank=True,
        default="",
        help_text=_("What changed, and why."),
    )
    file_name = models.CharField(
        _("file name"), max_length=255, editable=False
    )
    file_size = models.PositiveBigIntegerField(
        _("size"), default=0, editable=False
    )
    #: The file's extension, upper case - ``DOCX``, ``PDF`` - kept as a
    #: field so that lists filter, search and count by it.
    file_format = models.CharField(
        _("format"), max_length=10, blank=True, db_index=True, editable=False
    )
    content_type = models.CharField(
        _("content type"), max_length=120, blank=True, editable=False
    )
    checksum = models.CharField(
        _("SHA-256"), max_length=64, blank=True, editable=False
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("sent by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField(
        _("sent at"), default=timezone.now, editable=False
    )

    class Meta:
        ordering = ("document", "-number")
        verbose_name = _("version")
        verbose_name_plural = _("versions")
        constraints = (
            models.UniqueConstraint(
                fields=("document", "number"),
                name="documents_version_unique_number",
            ),
        )

    def __str__(self) -> str:
        return f"{self.document.reference} v{self.number}"

    def save(self, *args, **kwargs) -> None:
        self.file_format = extension_of(self.file_name or self.file.name)
        super().save(*args, **kwargs)


class Comment(models.Model):
    """A word left on a document by one of its readers."""

    document = models.ForeignKey(
        Document,
        verbose_name=_("document"),
        on_delete=models.CASCADE,
        related_name="comments",
    )
    body = models.TextField(_("comment"))
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("author"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField(
        _("written at"), default=timezone.now, editable=False
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = _("comment")
        verbose_name_plural = _("comments")

    def __str__(self) -> str:
        return self.body[:60]


class TeamWiki(models.Model):
    """Who reads and who writes a wiki. The wikis themselves are the
    framework's (``generic.wiki``); this says whose they are.

    ``team`` reads it - empty, everyone does; ``editing_teams`` write
    in it - none, whoever reads it may (with the page permissions).
    """

    wiki = models.OneToOneField(
        Wiki,
        verbose_name=_("wiki"),
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="team_link",
    )
    team = models.ForeignKey(
        Team,
        verbose_name=_("readers"),
        # A team's wiki never becomes everyone's by its team going.
        on_delete=models.PROTECT,
        related_name="wikis",
        null=True,
        blank=True,
        help_text=_("The team reading it; empty, everyone reads it."),
    )
    editing_teams = models.ManyToManyField(
        Team,
        verbose_name=_("editing teams"),
        related_name="edited_wikis",
        blank=True,
        help_text=_(
            "The teams writing in it - they read it too. None: whoever "
            "reads it writes in it, with the page permissions."
        ),
    )

    class Meta:
        ordering = ("wiki__position", "wiki__name")
        verbose_name = _("team wiki")
        verbose_name_plural = _("team wikis")

    def __str__(self) -> str:
        return str(self.wiki)


class StepKind(models.TextChoices):
    REVIEW = "review", _("Review")
    APPROVAL = "approval", _("Approval")
    ACKNOWLEDGEMENT = "acknowledgement", _("Acknowledgement")


class StepRule(models.TextChoices):
    ANY = "any", _("One of them")
    ALL = "all", _("Each of them")


class Participants(models.Model):
    """Who a step asks: people, groups (roles), and the document's
    team's leaders or members - any mix, each person once."""

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("people"),
        related_name="+",
        blank=True,
    )
    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name=_("roles"),
        related_name="+",
        blank=True,
        help_text=_("Every active member of these groups."),
    )
    team_leaders = models.BooleanField(
        _("the team's leaders"),
        default=False,
        help_text=_("Those leading the document's team."),
    )
    team_members = models.BooleanField(
        _("the team's members"),
        default=False,
        help_text=_("Everyone in the document's team."),
    )

    class Meta:
        abstract = True


class Workflow(models.Model):
    """A review circuit: steps one after the other, drawn once and used
    for any number of documents. Anyone may draw their own."""

    name = models.CharField(_("name"), max_length=120)
    description = models.TextField(_("description"), blank=True, default="")
    team = models.ForeignKey(
        Team,
        verbose_name=_("team"),
        on_delete=models.CASCADE,
        related_name="workflows",
        null=True,
        blank=True,
        help_text=_("Offered to this team only; empty, to everyone."),
    )
    is_active = models.BooleanField(
        _("offered"),
        default=True,
        help_text=_("Untick to stop offering it; reviews keep going."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField(
        _("created at"), default=timezone.now, editable=False
    )

    class Meta:
        ordering = ("name",)
        verbose_name = _("workflow")
        verbose_name_plural = _("workflows")

    def __str__(self) -> str:
        return self.name


class StepFields(Participants):
    position = models.PositiveIntegerField(_("order"), default=1)
    name = models.CharField(_("name"), max_length=120)
    kind = models.CharField(
        _("asks to"),
        max_length=20,
        choices=StepKind.choices,
        default=StepKind.APPROVAL,
    )
    rule = models.CharField(
        _("answered by"),
        max_length=10,
        choices=StepRule.choices,
        default=StepRule.ANY,
        help_text=_(
            "One of them: the first answer closes the step. Each of "
            "them: everyone answers."
        ),
    )
    days = models.PositiveIntegerField(
        _("days to answer"),
        null=True,
        blank=True,
        help_text=_("A due date, for the reminders; never a deadline."),
    )

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.position}. {self.name}"


class WorkflowStep(StepFields):
    workflow = models.ForeignKey(
        Workflow,
        verbose_name=_("workflow"),
        on_delete=models.CASCADE,
        related_name="steps",
    )

    class Meta:
        ordering = ("workflow", "position", "pk")
        verbose_name = _("step")
        verbose_name_plural = _("steps")


class Review(models.Model):
    """One document going through a circuit."""

    class Status(models.TextChoices):
        PREPARING = "preparing", _("Preparing")
        IN_PROGRESS = "in_progress", _("In progress")
        APPROVED = "approved", _("Completed")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")

    document = models.ForeignKey(
        Document,
        verbose_name=_("document"),
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    workflow = models.ForeignKey(
        Workflow,
        verbose_name=_("workflow"),
        on_delete=models.SET_NULL,
        related_name="reviews",
        null=True,
        blank=True,
        help_text=_(
            "Its steps are copied into the review, where they may still "
            "be changed. Empty: draw the steps below."
        ),
    )
    message = models.TextField(
        _("message"),
        blank=True,
        default="",
        help_text=_("What the reviewers should know - sent with the task."),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PREPARING,
        editable=False,
    )
    #: The document's version when the review started.
    version = models.PositiveIntegerField(
        _("version"), default=0, editable=False
    )
    #: The document's status before, given back when the review ends
    #: without an approval.
    previous_status = models.CharField(
        _("status before"), max_length=20, blank=True, editable=False
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("started by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField(
        _("created at"), default=timezone.now, editable=False
    )
    started_at = models.DateTimeField(
        _("started at"), null=True, blank=True, editable=False
    )
    finished_at = models.DateTimeField(
        _("finished at"), null=True, blank=True, editable=False
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = _("review")
        verbose_name_plural = _("reviews")

    def __str__(self) -> str:
        return f"{self.document} - {self.get_status_display()}"

    @property
    def is_open(self) -> bool:
        return self.status in (self.Status.PREPARING, self.Status.IN_PROGRESS)


class ReviewStep(StepFields):
    class Status(models.TextChoices):
        WAITING = "waiting", _("Waiting")
        ACTIVE = "active", _("In progress")
        DONE = "done", _("Done")
        REJECTED = "rejected", _("Rejected")
        SKIPPED = "skipped", _("Skipped")

    review = models.ForeignKey(
        Review,
        verbose_name=_("review"),
        on_delete=models.CASCADE,
        related_name="steps",
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.WAITING,
        editable=False,
    )
    due_on = models.DateField(
        _("due on"), null=True, blank=True, editable=False
    )
    started_at = models.DateTimeField(
        _("started at"), null=True, blank=True, editable=False
    )
    finished_at = models.DateTimeField(
        _("finished at"), null=True, blank=True, editable=False
    )

    class Meta:
        ordering = ("review", "position", "pk")
        verbose_name = _("review step")
        verbose_name_plural = _("review steps")


class ReviewTask(models.Model):
    """What one person is asked to do, at one step of one review."""

    class Status(models.TextChoices):
        PENDING = "pending", _("To do")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        DELEGATED = "delegated", _("Delegated")
        SKIPPED = "skipped", _("Not needed")

    step = models.ForeignKey(
        ReviewStep,
        verbose_name=_("step"),
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    #: The step's review, kept here so that lists filter on it.
    review = models.ForeignKey(
        Review,
        verbose_name=_("review"),
        on_delete=models.CASCADE,
        related_name="tasks",
        editable=False,
    )
    #: And its document, linked from the task's page and lists.
    document = models.ForeignKey(
        Document,
        verbose_name=_("document"),
        on_delete=models.CASCADE,
        related_name="tasks",
        editable=False,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("asked of"),
        on_delete=models.CASCADE,
        related_name="document_tasks",
        editable=False,
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        editable=False,
    )
    comment = models.TextField(_("comment"), blank=True, default="")
    due_on = models.DateField(
        _("due on"), null=True, blank=True, editable=False
    )
    created_at = models.DateTimeField(
        _("asked at"), default=timezone.now, editable=False
    )
    decided_at = models.DateTimeField(
        _("answered at"), null=True, blank=True, editable=False
    )
    #: Who answered: the assignee, or someone steering the review for
    #: them.
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("answered by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
    )
    delegated_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("delegated to"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
    )
    reminded_at = models.DateTimeField(
        _("reminded at"), null=True, blank=True, editable=False
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = _("task")
        verbose_name_plural = _("tasks")

    def __str__(self) -> str:
        return f"{self.step.name}: {self.review.document}"

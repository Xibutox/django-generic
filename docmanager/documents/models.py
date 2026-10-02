"""Folders, documents and the versions of their files.

* A **folder** belongs to a team (``generic_teams.Team``); its
  documents are that team's, and only its members - and whoever sees
  every team - reach them.
* A **document** is what people look for: a title, a status, tags, and
  its current file.
* A **version** is one file the document has had, with who sent it,
  when, and why. A document's file is always its latest version's;
  versions are never changed, only added - restoring an old one adds a
  new one.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from generic.teams.models import Team


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


class Document(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        REVIEW = "review", _("In review")
        APPROVED = "approved", _("Approved")
        OBSOLETE = "obsolete", _("Obsolete")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, editable=False
    )
    title = models.CharField(_("title"), max_length=200)
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
    #: The latest version's file. Replacing it adds a version.
    file = models.FileField(_("file"), upload_to=file_path, max_length=255)
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

        return f"{self.reference} {self.title}"

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

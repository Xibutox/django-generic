"""Change management (ISO/IEC 27002 8.32).

A change request says what changes, on which assets, the risk, how it
was tested and how to undo it; it is approved by someone other than its
requester (segregation of duties, 5.3), implemented, then reviewed.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from iso.common import number

USER = settings.AUTH_USER_MODEL


class ChangeRequest(models.Model):
    class Kind(models.TextChoices):
        STANDARD = "standard", _("Standard (pre-approved)")
        NORMAL = "normal", _("Normal")
        EMERGENCY = "emergency", _("Emergency")

    class Category(models.TextChoices):
        APPLICATION = "application", _("Application")
        INFRASTRUCTURE = "infrastructure", _("Infrastructure")
        NETWORK = "network", _("Network")
        CONFIGURATION = "configuration", _("Configuration")
        SECURITY = "security", _("Security")
        OTHER = "other", _("Other")

    class Risk(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Submitted")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        IMPLEMENTED = "implemented", _("Implemented")
        FAILED = "failed", _("Failed, rolled back")
        CLOSED = "closed", _("Closed")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, blank=True, editable=False
    )
    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(_("description"))
    reason = models.TextField(_("reason"), blank=True)
    kind = models.CharField(
        _("kind"), max_length=10, choices=Kind.choices, default="normal"
    )
    category = models.CharField(
        _("category"), max_length=16, choices=Category.choices
    )
    assets = models.ManyToManyField(
        "assets.Asset",
        verbose_name=_("assets"),
        blank=True,
        related_name="changes",
    )
    risk = models.CharField(
        _("risk"), max_length=8, choices=Risk.choices, default="low"
    )
    impact = models.TextField(_("impact"), blank=True)
    test_plan = models.TextField(_("test plan"), blank=True)
    rollback_plan = models.TextField(_("rollback plan"), blank=True)
    requested_by = models.ForeignKey(
        USER,
        verbose_name=_("requested by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    implementer = models.ForeignKey(
        USER,
        verbose_name=_("implementer"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(
        _("status"), max_length=12, choices=Status.choices, default="draft"
    )
    approved_by = models.ForeignKey(
        USER,
        verbose_name=_("decided by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    approved_at = models.DateTimeField(
        _("decided at"), null=True, blank=True, editable=False
    )
    planned_start = models.DateTimeField(
        _("planned start"), null=True, blank=True
    )
    planned_end = models.DateTimeField(_("planned end"), null=True, blank=True)
    implemented_at = models.DateTimeField(
        _("implemented at"), null=True, blank=True
    )
    review = models.TextField(
        _("post-implementation review"),
        blank=True,
        help_text=_("Did it work, was security affected, what to learn."),
    )

    class Meta:
        ordering = ("-pk",)
        verbose_name = _("change request")
        verbose_name_plural = _("change requests")
        permissions = [
            ("approve_changerequest", _("Can approve a change request"))
        ]

    def __str__(self) -> str:
        return f"{self.reference} {self.title}".strip()

    def save(self, *args, **kwargs) -> None:
        with transaction.atomic():
            number(self, "CHG-{seq:04}", "iso.change")
            super().save(*args, **kwargs)

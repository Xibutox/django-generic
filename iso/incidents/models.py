"""Security events and incidents (ISO/IEC 27002 5.24 to 5.28, 6.8).

Anyone reports an event; the security team decides whether it is an
incident (5.25), works it through a timeline of updates (5.26), keeps
its evidence with a checksum and a chain of custody (5.28), and writes
down what was learned (5.27). A personal data breach carries the GDPR's
72-hour deadline to notify the authority.
"""

from __future__ import annotations

import datetime
import hashlib

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from iso.common import Severity, number

USER = settings.AUTH_USER_MODEL

REFERENCE_PATTERN = "INC-{year}-{seq:04}"

#: GDPR art. 33: the supervisory authority, within 72 hours.
BREACH_NOTIFICATION_HOURS = 72


class Incident(models.Model):
    class Category(models.TextChoices):
        PHISHING = "phishing", _("Phishing")
        MALWARE = "malware", _("Malware")
        ACCESS = "access", _("Unauthorised access")
        LEAK = "leak", _("Data leak")
        LOSS = "loss", _("Loss or theft")
        DENIAL = "denial", _("Denial of service")
        MISCONFIGURATION = "misconfiguration", _("Misconfiguration")
        PHYSICAL = "physical", _("Physical")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        REPORTED = "reported", _("Reported")
        TRIAGE = "triage", _("Being assessed")
        CONTAINED = "contained", _("Contained")
        RESOLVED = "resolved", _("Resolved")
        CLOSED = "closed", _("Closed")
        NOT_INCIDENT = "not_incident", _("Not an incident")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, blank=True, editable=False
    )
    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(_("what happened"))
    category = models.CharField(
        _("category"), max_length=16, choices=Category.choices
    )
    severity = models.CharField(
        _("severity"),
        max_length=10,
        choices=Severity.choices,
        default=Severity.MEDIUM,
    )
    status = models.CharField(
        _("status"), max_length=12, choices=Status.choices, default="reported"
    )
    reported_by = models.ForeignKey(
        USER,
        verbose_name=_("reported by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    reported_at = models.DateTimeField(
        _("reported at"), default=timezone.now, editable=False
    )
    detected_at = models.DateTimeField(_("detected at"), default=timezone.now)
    handler = models.ForeignKey(
        USER,
        verbose_name=_("handler"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    assets = models.ManyToManyField(
        "assets.Asset",
        verbose_name=_("assets affected"),
        blank=True,
        related_name="incidents",
    )
    personal_data_breach = models.BooleanField(
        _("personal data breach"), default=False
    )
    authority_notified_at = models.DateTimeField(
        _("authority notified at"), null=True, blank=True
    )
    subjects_notified_at = models.DateTimeField(
        _("data subjects notified at"), null=True, blank=True
    )
    root_cause = models.TextField(_("root cause"), blank=True)
    lessons_learned = models.TextField(_("lessons learned"), blank=True)
    closed_at = models.DateTimeField(
        _("closed at"), null=True, blank=True, editable=False
    )

    class Meta:
        ordering = ("-detected_at", "-pk")
        verbose_name = _("incident")
        verbose_name_plural = _("incidents")

    def __str__(self) -> str:
        return f"{self.reference} {self.title}".strip()

    @property
    def notification_due(self) -> datetime.datetime | None:
        """When the authority must have been told, for a breach."""
        if not self.personal_data_breach or not self.detected_at:
            return None
        return self.detected_at + datetime.timedelta(
            hours=BREACH_NOTIFICATION_HOURS
        )

    @property
    def notification_late(self) -> bool:
        due = self.notification_due
        if due is None:
            return False
        told = self.authority_notified_at
        return (told or timezone.now()) > due

    def save(self, *args, **kwargs) -> None:
        closing = self.status in (self.Status.CLOSED, self.Status.NOT_INCIDENT)
        if closing and self.closed_at is None:
            self.closed_at = timezone.now()
        elif not closing:
            self.closed_at = None
        with transaction.atomic():
            number(self, REFERENCE_PATTERN, "iso.incident")
            super().save(*args, **kwargs)


class IncidentUpdate(models.Model):
    """One line of an incident's timeline (A.5.26)."""

    class Kind(models.TextChoices):
        NOTE = "note", _("Note")
        ACTION = "action", _("Action taken")
        DECISION = "decision", _("Decision")
        COMMUNICATION = "communication", _("Communication")

    incident = models.ForeignKey(
        Incident,
        verbose_name=_("incident"),
        on_delete=models.CASCADE,
        related_name="updates",
    )
    at = models.DateTimeField(_("at"), default=timezone.now)
    kind = models.CharField(
        _("kind"), max_length=14, choices=Kind.choices, default="note"
    )
    text = models.TextField(_("text"))
    author = models.ForeignKey(
        USER,
        verbose_name=_("author"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        ordering = ("-at", "-pk")
        verbose_name = _("update")
        verbose_name_plural = _("updates")

    def __str__(self) -> str:
        return f"{self.incident.reference} - {self.at:%Y-%m-%d %H:%M}"


class Evidence(models.Model):
    """An item of evidence, its checksum and custody (A.5.28).

    The SHA-256 of the file is computed when it is stored, so anyone can
    later show the file is the one collected.
    """

    incident = models.ForeignKey(
        Incident,
        verbose_name=_("incident"),
        on_delete=models.CASCADE,
        related_name="evidence",
    )
    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(_("description"), blank=True)
    file = models.FileField(
        _("file"), upload_to="iso/incident-evidence/", blank=True
    )
    sha256 = models.CharField(
        _("SHA-256"), max_length=64, blank=True, editable=False
    )
    collected_at = models.DateTimeField(
        _("collected at"), default=timezone.now
    )
    collected_by = models.ForeignKey(
        USER,
        verbose_name=_("collected by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    stored_at = models.CharField(
        _("where it is kept"), max_length=200, blank=True
    )
    custody = models.TextField(
        _("chain of custody"),
        blank=True,
        help_text=_("Who handed it to whom, when, and why."),
    )

    class Meta:
        ordering = ("-collected_at", "-pk")
        verbose_name = _("evidence")
        verbose_name_plural = _("evidence")

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        if not self.file:
            self.sha256 = ""
        elif not self.sha256 or not getattr(self.file, "_committed", True):
            # A file just sent - the first, or one replacing it.
            digest = hashlib.sha256()
            self.file.open("rb")
            for chunk in self.file.chunks():
                digest.update(chunk)
            self.file.seek(0)
            self.sha256 = digest.hexdigest()
        super().save(*args, **kwargs)

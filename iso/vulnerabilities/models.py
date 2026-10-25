"""Technical vulnerabilities (ISO/IEC 27002 8.8).

Where each vulnerability came from, which assets it affects, how severe
it is, and the date it must be fixed by - worked out from its severity
unless someone sets it: the remediation deadlines an auditor checks
were kept.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from iso.common import Severity, number

USER = settings.AUTH_USER_MODEL

#: Days to fix, by severity. A project changes them in its settings:
#: ``ISO_VULNERABILITY_DAYS = {"critical": 3, ...}``.
DEFAULT_DAYS = {"critical": 7, "high": 30, "medium": 90, "low": 180}


def remediation_days() -> dict[str, int]:
    return {
        **DEFAULT_DAYS,
        **getattr(settings, "ISO_VULNERABILITY_DAYS", {}),
    }


def severity_of(score: Decimal | float | None) -> str:
    """CVSS v3/v4 qualitative rating of a base score."""
    if score is None:
        return ""
    if score >= 9:
        return Severity.CRITICAL
    if score >= 7:
        return Severity.HIGH
    if score >= 4:
        return Severity.MEDIUM
    return Severity.LOW


class Vulnerability(models.Model):
    class Source(models.TextChoices):
        SCANNER = "scanner", _("Scanner")
        ADVISORY = "advisory", _("Security advisory")
        PENTEST = "pentest", _("Penetration test")
        REPORT = "report", _("Reported by someone")
        AUDIT = "audit", _("Audit")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        IN_PROGRESS = "in_progress", _("Being fixed")
        FIXED = "fixed", _("Fixed")
        ACCEPTED = "accepted", _("Risk accepted")
        FALSE_POSITIVE = "false_positive", _("False positive")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, blank=True, editable=False
    )
    title = models.CharField(_("title"), max_length=200)
    identifier = models.CharField(
        _("identifier"),
        max_length=50,
        blank=True,
        help_text=_("CVE, GHSA or the scanner's own."),
    )
    source = models.CharField(
        _("source"), max_length=10, choices=Source.choices
    )
    description = models.TextField(_("description"), blank=True)
    assets = models.ManyToManyField(
        "assets.Asset",
        verbose_name=_("assets affected"),
        blank=True,
        related_name="vulnerabilities",
    )
    cvss = models.DecimalField(
        _("CVSS score"),
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )
    severity = models.CharField(
        _("severity"),
        max_length=10,
        choices=Severity.choices,
        blank=True,
        help_text=_("Worked out from the CVSS score when left empty."),
    )
    discovered_on = models.DateField(
        _("discovered on"), default=timezone.localdate
    )
    due_on = models.DateField(
        _("fix by"),
        null=True,
        blank=True,
        help_text=_("Worked out from the severity when left empty."),
    )
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(
        _("status"), max_length=14, choices=Status.choices, default="open"
    )
    remediation = models.TextField(_("remediation"), blank=True)
    fixed_on = models.DateField(_("fixed on"), null=True, blank=True)

    class Meta:
        ordering = ("due_on", "-cvss")
        verbose_name = _("vulnerability")
        verbose_name_plural = _("vulnerabilities")

    def __str__(self) -> str:
        return f"{self.reference} {self.title}".strip()

    @property
    def is_overdue(self) -> bool:
        open_ = self.status in (self.Status.OPEN, self.Status.IN_PROGRESS)
        return bool(
            open_ and self.due_on and self.due_on < timezone.localdate()
        )

    def save(self, *args, **kwargs) -> None:
        if not self.severity:
            self.severity = severity_of(self.cvss) or Severity.MEDIUM
        if self.due_on is None:
            self.due_on = self.discovered_on + datetime.timedelta(
                days=remediation_days()[self.severity]
            )
        if self.status == self.Status.FIXED and self.fixed_on is None:
            self.fixed_on = timezone.localdate()
        with transaction.atomic():
            number(self, "VUL-{seq:04}", "iso.vulnerability")
            super().save(*args, **kwargs)

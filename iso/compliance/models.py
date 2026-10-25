"""Controls, the Statement of Applicability, and obligations.

The 93 Annex A controls are rows from the start (migration 0002): for
each one the organisation says whether it applies and why, how far it is
implemented, by whom and with what proof - which, exported, is the
Statement of Applicability (ISO/IEC 27001 6.1.3 d). Obligations are the
laws, regulations and contracts the ISMS must meet (A.5.31).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

USER = settings.AUTH_USER_MODEL


class Control(models.Model):
    class Theme(models.TextChoices):
        ORGANISATIONAL = "organisational", _("Organisational")
        PEOPLE = "people", _("People")
        PHYSICAL = "physical", _("Physical")
        TECHNOLOGICAL = "technological", _("Technological")

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", _("Not started")
        PLANNED = "planned", _("Planned")
        PARTIAL = "partial", _("Partly implemented")
        IMPLEMENTED = "implemented", _("Implemented")

    code = models.CharField(_("code"), max_length=10, unique=True)
    title = models.CharField(_("title"), max_length=200)
    theme = models.CharField(_("theme"), max_length=16, choices=Theme.choices)
    position = models.PositiveIntegerField(
        _("position"), default=0, editable=False
    )
    applicable = models.BooleanField(_("applicable"), default=True)
    justification = models.TextField(
        _("justification"),
        blank=True,
        help_text=_("Why it is included, or why it is excluded."),
    )
    status = models.CharField(
        _("implementation"),
        max_length=12,
        choices=Status.choices,
        default="not_started",
    )
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    implementation = models.TextField(_("how it is implemented"), blank=True)
    evidence = models.TextField(
        _("where the evidence is"),
        blank=True,
        help_text=_("Records, tools, documents an auditor can read."),
    )
    reviewed_on = models.DateField(_("reviewed on"), null=True, blank=True)

    class Meta:
        ordering = ("position", "code")
        verbose_name = _("control")
        verbose_name_plural = _("controls")

    def __str__(self) -> str:
        return f"{self.code} {self.title}"


class ControlEvidence(models.Model):
    """A document, a screenshot or a link proving a control works."""

    control = models.ForeignKey(
        Control,
        verbose_name=_("control"),
        on_delete=models.CASCADE,
        related_name="evidence_items",
    )
    title = models.CharField(_("title"), max_length=200)
    file = models.FileField(_("file"), upload_to="iso/evidence/", blank=True)
    url = models.URLField(_("link"), blank=True)
    collected_on = models.DateField(
        _("collected on"), default=timezone.localdate
    )
    collected_by = models.ForeignKey(
        USER,
        verbose_name=_("collected by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ("-collected_on", "-pk")
        verbose_name = _("evidence")
        verbose_name_plural = _("evidence")

    def __str__(self) -> str:
        return self.title


class Obligation(models.Model):
    """A law, regulation, contract or standard to meet (A.5.31)."""

    class Kind(models.TextChoices):
        LAW = "law", _("Law")
        REGULATION = "regulation", _("Regulation")
        CONTRACT = "contract", _("Contract")
        STANDARD = "standard", _("Standard")
        INTERNAL = "internal", _("Internal rule")

    class Status(models.TextChoices):
        NOT_ASSESSED = "not_assessed", _("Not assessed")
        COMPLIANT = "compliant", _("Compliant")
        PARTIAL = "partial", _("Partly compliant")
        NON_COMPLIANT = "non_compliant", _("Not compliant")

    title = models.CharField(_("title"), max_length=200)
    kind = models.CharField(_("kind"), max_length=12, choices=Kind.choices)
    source = models.CharField(
        _("source"),
        max_length=200,
        blank=True,
        help_text=_("The text and article: GDPR art. 32, contract 2024-17."),
    )
    jurisdiction = models.CharField(
        _("jurisdiction"), max_length=100, blank=True
    )
    requirement = models.TextField(_("what it requires"))
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    controls = models.ManyToManyField(
        Control,
        verbose_name=_("controls"),
        blank=True,
        related_name="obligations",
    )
    status = models.CharField(
        _("status"),
        max_length=14,
        choices=Status.choices,
        default="not_assessed",
    )
    assessed_on = models.DateField(_("assessed on"), null=True, blank=True)
    next_review_on = models.DateField(
        _("next review on"), null=True, blank=True
    )
    url = models.URLField(_("link"), blank=True)

    class Meta:
        ordering = ("kind", "title")
        verbose_name = _("obligation")
        verbose_name_plural = _("obligations")

    def __str__(self) -> str:
        return self.title

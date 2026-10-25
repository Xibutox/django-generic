"""Business continuity (ISO/IEC 27002 5.29, 5.30, 8.13, 8.14).

The business impact analysis rates each service: how long it can be
down (RTO), how much data it can lose (RPO), the longest outage the
business survives (MTPD). A continuity plan says how a service is
recovered; exercises - backup restores included - prove the plan
works, by comparing the times achieved with the targets.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from iso.common import Severity

USER = settings.AUTH_USER_MODEL


class Service(models.Model):
    """A business activity and its impact analysis."""

    name = models.CharField(_("name"), max_length=200, unique=True)
    description = models.TextField(_("description"), blank=True)
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    criticality = models.CharField(
        _("criticality"),
        max_length=10,
        choices=Severity.choices,
        default=Severity.MEDIUM,
    )
    assets = models.ManyToManyField(
        "assets.Asset",
        verbose_name=_("assets it depends on"),
        blank=True,
        related_name="services",
    )
    rto_hours = models.PositiveIntegerField(
        _("RTO (hours)"),
        null=True,
        blank=True,
        help_text=_("Recovery time objective: how long it may be down."),
    )
    rpo_hours = models.PositiveIntegerField(
        _("RPO (hours)"),
        null=True,
        blank=True,
        help_text=_("Recovery point objective: how much data may be lost."),
    )
    mtpd_hours = models.PositiveIntegerField(
        _("MTPD (hours)"),
        null=True,
        blank=True,
        help_text=_("Maximum tolerable period of disruption."),
    )
    impact = models.TextField(
        _("impact of a disruption"),
        blank=True,
        help_text=_("Financial, legal, contractual, reputational."),
    )
    analysed_on = models.DateField(_("analysed on"), null=True, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("service")
        verbose_name_plural = _("services")

    def __str__(self) -> str:
        return self.name


class ContinuityPlan(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        APPROVED = "approved", _("Approved")
        RETIRED = "retired", _("Retired")

    title = models.CharField(_("title"), max_length=200)
    services = models.ManyToManyField(
        Service,
        verbose_name=_("services"),
        blank=True,
        related_name="plans",
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
        _("status"), max_length=10, choices=Status.choices, default="draft"
    )
    version = models.CharField(_("version"), max_length=20, default="1.0")
    activation = models.TextField(
        _("activation"),
        blank=True,
        help_text=_("Who decides to activate the plan, and when."),
    )
    procedure = models.TextField(_("recovery procedure"), blank=True)
    security_measures = models.TextField(
        _("security during disruption"),
        blank=True,
        help_text=_("How security is kept while the plan runs (A.5.29)."),
    )
    document = models.FileField(
        _("document"), upload_to="iso/continuity/", blank=True
    )
    next_test_on = models.DateField(_("next test"), null=True, blank=True)

    class Meta:
        ordering = ("title",)
        verbose_name = _("continuity plan")
        verbose_name_plural = _("continuity plans")

    def __str__(self) -> str:
        return self.title


class Exercise(models.Model):
    """A test of a plan, or of a backup restore (A.8.13)."""

    class Kind(models.TextChoices):
        TABLETOP = "tabletop", _("Tabletop")
        SIMULATION = "simulation", _("Simulation")
        RESTORE = "restore", _("Backup restore")
        FAILOVER = "failover", _("Failover")
        FULL = "full", _("Full interruption")

    class Result(models.TextChoices):
        PLANNED = "planned", _("Planned")
        PASSED = "passed", _("Passed")
        PARTIAL = "partial", _("Partly passed")
        FAILED = "failed", _("Failed")

    title = models.CharField(_("title"), max_length=200)
    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices)
    plan = models.ForeignKey(
        ContinuityPlan,
        verbose_name=_("plan"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exercises",
    )
    service = models.ForeignKey(
        Service,
        verbose_name=_("service"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exercises",
    )
    held_on = models.DateField(_("held on"), default=timezone.localdate)
    participants: models.ManyToManyField = models.ManyToManyField(
        USER,
        verbose_name=_("participants"),
        blank=True,
        related_name="+",
    )
    result = models.CharField(
        _("result"), max_length=10, choices=Result.choices, default="planned"
    )
    achieved_rto_hours = models.DecimalField(
        _("recovery time achieved (hours)"),
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
    )
    achieved_rpo_hours = models.DecimalField(
        _("data loss achieved (hours)"),
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
    )
    findings = models.TextField(_("findings"), blank=True)

    class Meta:
        ordering = ("-held_on",)
        verbose_name = _("exercise")
        verbose_name_plural = _("exercises")

    def __str__(self) -> str:
        return self.title

    @property
    def target_met(self) -> bool | None:
        """Whether the times achieved meet the service's objectives;
        ``None`` when either side is unknown."""
        service = self.service
        if service is None or self.achieved_rto_hours is None:
            return None
        if service.rto_hours is None:
            return None
        met = self.achieved_rto_hours <= service.rto_hours
        if self.achieved_rpo_hours is not None and service.rpo_hours:
            met = met and self.achieved_rpo_hours <= service.rpo_hours
        return met

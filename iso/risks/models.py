"""The risk register (ISO/IEC 27001 6.1.2, 6.1.3, 8.2, 8.3).

A risk is a threat exploiting a vulnerability of some assets, rated by
likelihood and impact on a 1 to 5 scale before treatment, then again
once the chosen controls work: the residual risk its owner accepts.
Treatment actions are the plan that gets from one to the other.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from iso.common import number

USER = settings.AUTH_USER_MODEL

REFERENCE_PATTERN = "RISK-{seq:04}"

SCALE = [
    (1, _("1 - Rare")),
    (2, _("2 - Unlikely")),
    (3, _("3 - Possible")),
    (4, _("4 - Likely")),
    (5, _("5 - Almost certain")),
]
IMPACTS = [
    (1, _("1 - Negligible")),
    (2, _("2 - Minor")),
    (3, _("3 - Moderate")),
    (4, _("4 - Major")),
    (5, _("5 - Severe")),
]


class Level(models.TextChoices):
    LOW = "low", _("Low")
    MEDIUM = "medium", _("Medium")
    HIGH = "high", _("High")
    CRITICAL = "critical", _("Critical")


def level_of(score: int | None) -> str:
    """The level of a likelihood x impact score (1 to 25)."""
    if not score:
        return ""
    if score <= 4:
        return Level.LOW
    if score <= 9:
        return Level.MEDIUM
    if score <= 16:
        return Level.HIGH
    return Level.CRITICAL


class Risk(models.Model):
    class Category(models.TextChoices):
        CONFIDENTIALITY = "confidentiality", _("Confidentiality")
        INTEGRITY = "integrity", _("Integrity")
        AVAILABILITY = "availability", _("Availability")
        COMPLIANCE = "compliance", _("Compliance")

    class Treatment(models.TextChoices):
        MITIGATE = "mitigate", _("Mitigate")
        ACCEPT = "accept", _("Accept")
        AVOID = "avoid", _("Avoid")
        TRANSFER = "transfer", _("Transfer")

    class Status(models.TextChoices):
        IDENTIFIED = "identified", _("Identified")
        ASSESSED = "assessed", _("Assessed")
        TREATING = "treating", _("Being treated")
        ACCEPTED = "accepted", _("Accepted")
        CLOSED = "closed", _("Closed")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, blank=True, editable=False
    )
    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(_("description"), blank=True)
    category = models.CharField(
        _("category"), max_length=16, choices=Category.choices
    )
    threat = models.CharField(_("threat"), max_length=200)
    vulnerability = models.CharField(_("vulnerability"), max_length=200)
    assets = models.ManyToManyField(
        "assets.Asset",
        verbose_name=_("assets"),
        blank=True,
        related_name="risks",
    )
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    likelihood = models.PositiveSmallIntegerField(
        _("likelihood"), choices=SCALE, default=3
    )
    impact = models.PositiveSmallIntegerField(
        _("impact"), choices=IMPACTS, default=3
    )
    score = models.PositiveSmallIntegerField(
        _("score"), default=0, editable=False
    )
    level = models.CharField(
        _("level"), max_length=10, choices=Level.choices, editable=False
    )
    treatment = models.CharField(
        _("treatment"),
        max_length=10,
        choices=Treatment.choices,
        default="mitigate",
    )
    controls = models.ManyToManyField(
        "compliance.Control",
        verbose_name=_("controls"),
        blank=True,
        related_name="risks",
    )
    residual_likelihood = models.PositiveSmallIntegerField(
        _("residual likelihood"), choices=SCALE, null=True, blank=True
    )
    residual_impact = models.PositiveSmallIntegerField(
        _("residual impact"), choices=IMPACTS, null=True, blank=True
    )
    residual_score = models.PositiveSmallIntegerField(
        _("residual score"), null=True, blank=True, editable=False
    )
    residual_level = models.CharField(
        _("residual level"),
        max_length=10,
        choices=Level.choices,
        blank=True,
        editable=False,
    )
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=Status.choices,
        default="identified",
    )
    accepted_by = models.ForeignKey(
        USER,
        verbose_name=_("accepted by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    accepted_on = models.DateField(
        _("accepted on"), null=True, blank=True, editable=False
    )
    identified_on = models.DateField(
        _("identified on"), default=timezone.localdate
    )
    next_review_on = models.DateField(
        _("next review on"), null=True, blank=True
    )

    class Meta:
        ordering = ("-score", "reference")
        verbose_name = _("risk")
        verbose_name_plural = _("risks")
        permissions = [("accept_risk", _("Can accept a residual risk"))]

    def __str__(self) -> str:
        return f"{self.reference} {self.title}".strip()

    def save(self, *args, **kwargs) -> None:
        self.score = self.likelihood * self.impact
        self.level = level_of(self.score)
        if self.residual_likelihood and self.residual_impact:
            self.residual_score = (
                self.residual_likelihood * self.residual_impact
            )
        else:
            self.residual_score = None
        self.residual_level = level_of(self.residual_score)
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {
                *kwargs["update_fields"],
                "score",
                "level",
                "residual_score",
                "residual_level",
            }
        with transaction.atomic():
            number(self, REFERENCE_PATTERN, "iso.risk")
            super().save(*args, **kwargs)


class TreatmentAction(models.Model):
    """A step of the risk treatment plan (6.1.3 e, 8.3)."""

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        IN_PROGRESS = "in_progress", _("In progress")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")

    risk = models.ForeignKey(
        Risk,
        verbose_name=_("risk"),
        on_delete=models.CASCADE,
        related_name="actions",
    )
    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(_("description"), blank=True)
    control = models.ForeignKey(
        "compliance.Control",
        verbose_name=_("control"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="treatment_actions",
    )
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    due_on = models.DateField(_("due on"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=12, choices=Status.choices, default="planned"
    )
    done_on = models.DateField(_("done on"), null=True, blank=True)

    class Meta:
        ordering = ("due_on", "pk")
        verbose_name = _("treatment action")
        verbose_name_plural = _("treatment actions")

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        if self.status == self.Status.DONE and self.done_on is None:
            self.done_on = timezone.localdate()
        elif self.status != self.Status.DONE:
            self.done_on = None
        super().save(*args, **kwargs)

"""Suppliers and the security of what they provide (ISO/IEC 27002 5.19
to 5.23).

A supplier is rated by how much harm a failure on their side would do
and by the data they reach; their agreements say which security clauses
were signed; assessments - questionnaires, audits, certificates read -
are the monitoring 5.22 asks for, each one setting the date of the next.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from iso.common import Severity

USER = settings.AUTH_USER_MODEL


class Supplier(models.Model):
    class Status(models.TextChoices):
        PROSPECT = "prospect", _("Prospect")
        ACTIVE = "active", _("Active")
        REVIEW = "review", _("Under review")
        ENDED = "ended", _("Ended")

    class DataAccess(models.TextChoices):
        NONE = "none", _("None")
        INTERNAL = "internal", _("Internal data")
        CONFIDENTIAL = "confidential", _("Confidential data")
        PERSONAL = "personal", _("Personal data")

    name = models.CharField(_("name"), max_length=200, unique=True)
    services = models.TextField(_("services provided"))
    criticality = models.CharField(
        _("criticality"),
        max_length=10,
        choices=Severity.choices,
        default=Severity.MEDIUM,
    )
    status = models.CharField(
        _("status"), max_length=10, choices=Status.choices, default="active"
    )
    data_access = models.CharField(
        _("data reached"),
        max_length=12,
        choices=DataAccess.choices,
        default="none",
    )
    cloud_service = models.BooleanField(
        _("cloud service"),
        default=False,
        help_text=_("They provide a cloud service (A.5.23)."),
    )
    certifications = models.CharField(
        _("certifications"),
        max_length=200,
        blank=True,
        help_text=_("ISO/IEC 27001, SOC 2, HDS..."),
    )
    certification_expires_on = models.DateField(
        _("certificate expires on"), null=True, blank=True
    )
    owner = models.ForeignKey(
        USER,
        verbose_name=_("relationship owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    contact_name = models.CharField(_("contact"), max_length=200, blank=True)
    contact_email = models.EmailField(_("contact e-mail"), blank=True)
    website = models.URLField(_("website"), blank=True)
    next_review_on = models.DateField(
        _("next review on"), null=True, blank=True
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("supplier")
        verbose_name_plural = _("suppliers")

    def __str__(self) -> str:
        return self.name


class Agreement(models.Model):
    """A contract and the security clauses it holds (A.5.20)."""

    class Kind(models.TextChoices):
        CONTRACT = "contract", _("Contract")
        DPA = "dpa", _("Data processing agreement")
        NDA = "nda", _("Non-disclosure agreement")
        SLA = "sla", _("Service level agreement")

    supplier = models.ForeignKey(
        Supplier,
        verbose_name=_("supplier"),
        on_delete=models.CASCADE,
        related_name="agreements",
    )
    title = models.CharField(_("title"), max_length=200)
    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices)
    starts_on = models.DateField(_("starts on"), null=True, blank=True)
    ends_on = models.DateField(_("ends on"), null=True, blank=True)
    security_clauses = models.BooleanField(
        _("security requirements"), default=False
    )
    confidentiality = models.BooleanField(_("confidentiality"), default=False)
    incident_notification = models.BooleanField(
        _("incident notification"), default=False
    )
    right_to_audit = models.BooleanField(_("right to audit"), default=False)
    subcontracting = models.BooleanField(
        _("subcontracting rules"), default=False
    )
    exit_clause = models.BooleanField(_("exit and data return"), default=False)
    document = models.FileField(
        _("document"), upload_to="iso/agreements/", blank=True
    )

    class Meta:
        ordering = ("supplier", "-starts_on")
        verbose_name = _("agreement")
        verbose_name_plural = _("agreements")

    def __str__(self) -> str:
        return f"{self.supplier} - {self.title}"

    CLAUSES = (
        "security_clauses",
        "confidentiality",
        "incident_notification",
        "right_to_audit",
        "subcontracting",
        "exit_clause",
    )

    @property
    def clauses_signed(self) -> int:
        return sum(bool(getattr(self, name)) for name in self.CLAUSES)


class Assessment(models.Model):
    """A supplier's security assessed, and when next (A.5.21, A.5.22)."""

    class Method(models.TextChoices):
        QUESTIONNAIRE = "questionnaire", _("Questionnaire")
        AUDIT = "audit", _("Audit")
        CERTIFICATE = "certificate", _("Certificate review")
        MEETING = "meeting", _("Service review meeting")

    class Result(models.TextChoices):
        APPROVED = "approved", _("Approved")
        CONDITIONS = "conditions", _("Approved with conditions")
        REJECTED = "rejected", _("Rejected")

    supplier = models.ForeignKey(
        Supplier,
        verbose_name=_("supplier"),
        on_delete=models.CASCADE,
        related_name="assessments",
    )
    assessed_on = models.DateField(
        _("assessed on"), default=timezone.localdate
    )
    method = models.CharField(
        _("method"), max_length=14, choices=Method.choices
    )
    assessor = models.ForeignKey(
        USER,
        verbose_name=_("assessor"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    score = models.PositiveSmallIntegerField(
        _("score (%)"), null=True, blank=True
    )
    result = models.CharField(
        _("result"), max_length=12, choices=Result.choices
    )
    findings = models.TextField(_("findings"), blank=True)
    next_assessment_on = models.DateField(
        _("next assessment on"), null=True, blank=True
    )

    class Meta:
        ordering = ("-assessed_on", "-pk")
        verbose_name = _("assessment")
        verbose_name_plural = _("assessments")

    def __str__(self) -> str:
        return f"{self.supplier} - {self.assessed_on}"

    def save(self, *args, **kwargs) -> None:
        super().save(*args, **kwargs)
        # The supplier's next review follows its latest assessment.
        if self.next_assessment_on:
            latest = self.supplier.assessments.order_by(
                "-assessed_on", "-pk"
            ).first()
            if latest and latest.pk == self.pk:
                Supplier.objects.filter(pk=self.supplier_id).update(
                    next_review_on=self.next_assessment_on
                )

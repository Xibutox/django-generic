"""Audits, nonconformities and corrective actions (ISO/IEC 27001 9.2,
10.2; ISO/IEC 27002 5.35, 5.36).

An audit has a scope, criteria and a conclusion; what it finds - and
what an incident, a review or a complaint reveals - is a
nonconformity, graded, with its root cause. Corrective actions remove
the cause; each one is checked for effectiveness before the
nonconformity closes (10.2 d).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from iso.common import number

USER = settings.AUTH_USER_MODEL


class Audit(models.Model):
    class Kind(models.TextChoices):
        INTERNAL = "internal", _("Internal audit")
        CERTIFICATION = "certification", _("Certification audit")
        SURVEILLANCE = "surveillance", _("Surveillance audit")
        SUPPLIER = "supplier", _("Supplier audit")
        INDEPENDENT = "independent", _("Independent review")
        COMPLIANCE = "compliance", _("Compliance check")

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        IN_PROGRESS = "in_progress", _("In progress")
        REPORTED = "reported", _("Reported")
        CLOSED = "closed", _("Closed")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, blank=True, editable=False
    )
    title = models.CharField(_("title"), max_length=200)
    kind = models.CharField(_("kind"), max_length=14, choices=Kind.choices)
    scope = models.TextField(_("scope"))
    criteria = models.TextField(
        _("criteria"),
        blank=True,
        help_text=_("What is audited against: clauses, controls, policies."),
    )
    lead_auditor = models.ForeignKey(
        USER,
        verbose_name=_("lead auditor"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    auditors = models.CharField(
        _("other auditors"), max_length=200, blank=True
    )
    controls = models.ManyToManyField(
        "compliance.Control",
        verbose_name=_("controls covered"),
        blank=True,
        related_name="audits",
    )
    planned_on = models.DateField(_("planned on"))
    performed_on = models.DateField(_("performed on"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=12, choices=Status.choices, default="planned"
    )
    conclusion = models.TextField(_("conclusion"), blank=True)
    report = models.FileField(_("report"), upload_to="iso/audits/", blank=True)

    class Meta:
        ordering = ("-planned_on",)
        verbose_name = _("audit")
        verbose_name_plural = _("audits")

    def __str__(self) -> str:
        return f"{self.reference} {self.title}".strip()

    def save(self, *args, **kwargs) -> None:
        with transaction.atomic():
            number(self, "AUD-{year}-{seq:02}", "iso.audit")
            super().save(*args, **kwargs)


class Nonconformity(models.Model):
    class Source(models.TextChoices):
        AUDIT = "audit", _("Audit")
        INCIDENT = "incident", _("Incident")
        REVIEW = "review", _("Management review")
        MONITORING = "monitoring", _("Monitoring")
        COMPLAINT = "complaint", _("Complaint")
        OTHER = "other", _("Other")

    class Grade(models.TextChoices):
        MAJOR = "major", _("Major nonconformity")
        MINOR = "minor", _("Minor nonconformity")
        OBSERVATION = "observation", _("Observation")
        OPPORTUNITY = "opportunity", _("Opportunity for improvement")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        PLANNED = "planned", _("Action planned")
        VERIFYING = "verifying", _("Checking effectiveness")
        CLOSED = "closed", _("Closed")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, blank=True, editable=False
    )
    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(_("description"))
    source = models.CharField(
        _("source"), max_length=12, choices=Source.choices, default="audit"
    )
    audit = models.ForeignKey(
        Audit,
        verbose_name=_("audit"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="findings",
    )
    grade = models.CharField(_("grade"), max_length=12, choices=Grade.choices)
    requirement = models.CharField(
        _("requirement"),
        max_length=50,
        blank=True,
        help_text=_("The clause or control not met: 9.2, A.8.8..."),
    )
    control = models.ForeignKey(
        "compliance.Control",
        verbose_name=_("control"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nonconformities",
    )
    raised_on = models.DateField(_("raised on"), default=timezone.localdate)
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    root_cause = models.TextField(_("root cause"), blank=True)
    status = models.CharField(
        _("status"), max_length=10, choices=Status.choices, default="open"
    )
    closed_on = models.DateField(
        _("closed on"), null=True, blank=True, editable=False
    )

    class Meta:
        ordering = ("-raised_on", "-pk")
        verbose_name = _("nonconformity")
        verbose_name_plural = _("nonconformities")

    def __str__(self) -> str:
        return f"{self.reference} {self.title}".strip()

    def save(self, *args, **kwargs) -> None:
        if self.status == self.Status.CLOSED and self.closed_on is None:
            self.closed_on = timezone.localdate()
        elif self.status != self.Status.CLOSED:
            self.closed_on = None
        with transaction.atomic():
            number(self, "NC-{seq:04}", "iso.nonconformity")
            super().save(*args, **kwargs)


class CorrectiveAction(models.Model):
    class Kind(models.TextChoices):
        CORRECTION = "correction", _("Correction")
        CORRECTIVE = "corrective", _("Corrective action")
        PREVENTIVE = "preventive", _("Preventive action")

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        IN_PROGRESS = "in_progress", _("In progress")
        DONE = "done", _("Done")
        EFFECTIVE = "effective", _("Effective")
        INEFFECTIVE = "ineffective", _("Not effective")

    nonconformity = models.ForeignKey(
        Nonconformity,
        verbose_name=_("nonconformity"),
        on_delete=models.CASCADE,
        related_name="actions",
    )
    title = models.CharField(_("title"), max_length=200)
    kind = models.CharField(
        _("kind"), max_length=12, choices=Kind.choices, default="corrective"
    )
    description = models.TextField(_("description"), blank=True)
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
    verified_by = models.ForeignKey(
        USER,
        verbose_name=_("verified by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    verified_on = models.DateField(
        _("verified on"), null=True, blank=True, editable=False
    )

    class Meta:
        ordering = ("due_on", "pk")
        verbose_name = _("corrective action")
        verbose_name_plural = _("corrective actions")

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs) -> None:
        finished = (self.Status.DONE, self.Status.EFFECTIVE)
        if self.status in finished and self.done_on is None:
            self.done_on = timezone.localdate()
        super().save(*args, **kwargs)

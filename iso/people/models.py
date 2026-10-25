"""People security: training records and personnel files (ISO/IEC
27001 7.2, 7.3; ISO/IEC 27002 6.1 to 6.6).

Courses say what must be learnt and how long it stays valid; training
records say who learnt it and when it expires. A personnel file keeps
the security steps of a person's time in the organisation: screened
before joining (6.1), responsibilities and confidentiality signed (6.2,
6.6), and on leaving, access removed and assets returned (6.5, 5.11).
"""

from __future__ import annotations

import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

USER = settings.AUTH_USER_MODEL


def add_months(day: datetime.date, months: int) -> datetime.date:
    """The same day ``months`` later, the month's last day if shorter."""
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    for last in (31, 30, 29, 28):
        try:
            return day.replace(year=year, month=month, day=min(day.day, last))
        except ValueError:
            continue
    raise ValueError(day)  # pragma: no cover - every month has a 28th


class Course(models.Model):
    class Topic(models.TextChoices):
        AWARENESS = "awareness", _("Security awareness")
        POLICY = "policy", _("Policies and rules")
        PRIVACY = "privacy", _("Data protection")
        ROLE = "role", _("Role-specific")
        TECHNICAL = "technical", _("Technical")

    title = models.CharField(_("title"), max_length=200)
    topic = models.CharField(_("topic"), max_length=10, choices=Topic.choices)
    description = models.TextField(_("description"), blank=True)
    mandatory = models.BooleanField(
        _("mandatory"),
        default=False,
        help_text=_("Every member of staff must follow it."),
    )
    audience = models.CharField(_("audience"), max_length=200, blank=True)
    validity_months = models.PositiveSmallIntegerField(
        _("valid for (months)"),
        default=12,
        help_text=_("0: never expires."),
    )
    url = models.URLField(_("link"), blank=True)

    class Meta:
        ordering = ("title",)
        verbose_name = _("course")
        verbose_name_plural = _("courses")

    def __str__(self) -> str:
        return self.title


class TrainingRecord(models.Model):
    """Somebody followed a course (7.2, 7.3, A.6.3)."""

    course = models.ForeignKey(
        Course,
        verbose_name=_("course"),
        on_delete=models.PROTECT,
        related_name="records",
    )
    person = models.ForeignKey(
        USER,
        verbose_name=_("person"),
        on_delete=models.CASCADE,
        related_name="training_records",
    )
    completed_on = models.DateField(
        _("completed on"), default=timezone.localdate
    )
    expires_on = models.DateField(
        _("expires on"), null=True, blank=True, editable=False
    )
    score = models.PositiveSmallIntegerField(
        _("score (%)"), null=True, blank=True
    )
    certificate = models.FileField(
        _("certificate"), upload_to="iso/training/", blank=True
    )
    notes = models.CharField(_("notes"), max_length=300, blank=True)

    class Meta:
        ordering = ("-completed_on", "-pk")
        verbose_name = _("training record")
        verbose_name_plural = _("training records")

    def __str__(self) -> str:
        return f"{self.person} - {self.course}"

    def save(self, *args, **kwargs) -> None:
        months = self.course.validity_months
        self.expires_on = (
            add_months(self.completed_on, months) if months else None
        )
        super().save(*args, **kwargs)


class PersonnelFile(models.Model):
    """The security steps of a person's time here (A.6.1 to A.6.6)."""

    class Employment(models.TextChoices):
        EMPLOYEE = "employee", _("Employee")
        CONTRACTOR = "contractor", _("Contractor")
        INTERN = "intern", _("Intern")
        TEMPORARY = "temporary", _("Temporary")

    class Status(models.TextChoices):
        JOINING = "joining", _("Joining")
        ACTIVE = "active", _("Active")
        LEAVING = "leaving", _("Leaving")
        LEFT = "left", _("Left")

    full_name = models.CharField(_("full name"), max_length=200)
    user = models.OneToOneField(
        USER,
        verbose_name=_("account"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="personnel_file",
    )
    job_title = models.CharField(_("job title"), max_length=200, blank=True)
    department = models.CharField(_("department"), max_length=200, blank=True)
    employment = models.CharField(
        _("employment"),
        max_length=10,
        choices=Employment.choices,
        default="employee",
    )
    status = models.CharField(
        _("status"), max_length=8, choices=Status.choices, default="joining"
    )
    starts_on = models.DateField(_("starts on"), null=True, blank=True)
    ends_on = models.DateField(_("ends on"), null=True, blank=True)
    screened_on = models.DateField(
        _("background checked on"),
        null=True,
        blank=True,
        help_text=_("Checks proportionate to the role (A.6.1)."),
    )
    terms_signed_on = models.DateField(
        _("security responsibilities signed on"),
        null=True,
        blank=True,
        help_text=_("In the contract or a charter (A.6.2)."),
    )
    nda_signed_on = models.DateField(
        _("confidentiality agreement signed on"),
        null=True,
        blank=True,
        help_text=_("A.6.6."),
    )
    access_revoked_on = models.DateField(
        _("access removed on"), null=True, blank=True
    )
    assets_returned_on = models.DateField(
        _("assets returned on"), null=True, blank=True
    )
    exit_reminder_on = models.DateField(
        _("reminded of duties on"),
        null=True,
        blank=True,
        help_text=_("Duties that last after leaving (A.6.5)."),
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ("full_name",)
        verbose_name = _("personnel file")
        verbose_name_plural = _("personnel files")

    def __str__(self) -> str:
        return self.full_name

    JOINING_STEPS = ("screened_on", "terms_signed_on", "nda_signed_on")
    LEAVING_STEPS = (
        "access_revoked_on",
        "assets_returned_on",
        "exit_reminder_on",
    )

    def missing(self, steps: tuple[str, ...]) -> list[str]:
        return [
            str(getattr(self._meta.get_field(name), "verbose_name", name))
            for name in steps
            if not getattr(self, name)
        ]

    @property
    def missing_steps(self) -> list[str]:
        """What is still to do: the joining steps, and the leaving ones
        once the person is leaving."""
        steps: tuple[str, ...] = self.JOINING_STEPS
        if self.status in (self.Status.LEAVING, self.Status.LEFT):
            steps = steps + self.LEAVING_STEPS
        return self.missing(steps)

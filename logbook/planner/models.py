"""The logbook's records: projects, notes and their lines, tasks, time.

A note is written line by line (``NoteLine``): plain text, a heading, a
bullet, a to-do ticked off - or a task line, which *is* a task: the
line holds the ``Task`` it became, and the task the note it came from.
Tasks are of three kinds, FNC (a ticket: something to fix, with its
criticality), DM (an evolution: something to build) and AUT (the rest:
a meeting, help given to someone), each numbered in its own series
(FNC-0001, DM-0001, AUT-0001) by the framework's numbering. A task is
about any number of projects, none included. Time is logged
against a task (``TimeEntry``): started and ended - a running timer has
no end yet - then checked by whoever verifies the timesheet.

From the older planner it replaces: a task's ``Imputation`` (with its
``Direction``), the distribution matrix (``ImputationShare``) the
imputation export spreads time over, and the COMET/DES usage figures
(``KpiRecord``) the key figures API serves; ``legacy_id`` marks what
``import_planner`` brought over.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from generic.numbering import allocate

#: The number every task gets: its kind, then its place in that series.
REFERENCE_PATTERN = "{kind}-{seq:04}"


class Label(models.Model):
    """A word to sort notes by, with its colour."""

    name = models.CharField(_("name"), max_length=60, unique=True)
    color = models.CharField(_("colour"), max_length=30, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("label")
        verbose_name_plural = _("labels")

    def __str__(self) -> str:
        return self.name


class Project(models.Model):
    """What notes and tasks are about: a product, a client, a plan."""

    name = models.CharField(_("name"), max_length=120, unique=True)
    color = models.CharField(_("colour"), max_length=30, blank=True)
    description = models.TextField(_("description"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("project")
        verbose_name_plural = _("projects")

    def __str__(self) -> str:
        return self.name


class Direction(models.Model):
    """A department the time is charged to."""

    name = models.CharField(_("name"), max_length=128, unique=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("direction")
        verbose_name_plural = _("directions")

    def __str__(self) -> str:
        return self.name


class Imputation(models.Model):
    """An accounting code a task's time is charged to."""

    name = models.CharField(_("name"), max_length=128, unique=True)
    number = models.CharField(_("number"), max_length=128, unique=True)
    direction = models.ForeignKey(
        Direction,
        verbose_name=_("direction"),
        on_delete=models.PROTECT,
        related_name="imputations",
    )

    class Meta:
        ordering = ("name",)
        verbose_name = _("imputation")
        verbose_name_plural = _("imputations")

    def __str__(self) -> str:
        return f"[{self.direction}] {self.name}"


class ImputationShare(models.Model):
    """One line of the distribution matrix: the share of the time the
    imputation export gives to a number. The shares add up to 100."""

    number = models.CharField(_("number"), max_length=128, unique=True)
    percentage = models.FloatField(_("percentage"))

    class Meta:
        ordering = ("number",)
        verbose_name = _("matrix line")
        verbose_name_plural = _("distribution matrix")

    def __str__(self) -> str:
        return f"{self.number} ({self.percentage:g} %)"


class Note(models.Model):
    """A page of notes: lines of text, some of them tasks."""

    title = models.CharField(_("title"), max_length=200)
    project = models.ForeignKey(
        Project,
        verbose_name=_("project"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
    )
    labels = models.ManyToManyField(
        Label, verbose_name=_("labels"), blank=True, related_name="notes"
    )
    pinned = models.BooleanField(
        _("pinned"),
        default=False,
        help_text=_("Pinned notes come first, and on the dashboard."),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("author"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="planner_notes",
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        ordering = ("-pinned", "-updated_at", "-pk")
        verbose_name = _("note")
        verbose_name_plural = _("notes")

    def __str__(self) -> str:
        return self.title


class Task(models.Model):
    """Something to do: a ticket (FNC), an evolution (DM), or anything
    else (AUT) - a meeting, support given to someone."""

    class Kind(models.TextChoices):
        FNC = "FNC", _("FNC - ticket")
        DM = "DM", _("DM - evolution")
        AUT = "AUT", _("AUT - other")

    class Criticality(models.TextChoices):
        """How bad a ticket is - FNC tasks only."""

        MINOR = "minor", _("Minor")
        MAJOR = "major", _("Major")
        CRITICAL = "critical", _("Critical")

    class Status(models.TextChoices):
        BACKLOG = "backlog", _("Backlog")
        TODO = "todo", pgettext_lazy("task status", "To do")
        DOING = "doing", _("In progress")
        REVIEW = "review", _("In review")
        DONE = "done", pgettext_lazy("task status", "Done")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, editable=False
    )
    kind = models.CharField(
        _("kind"), max_length=3, choices=Kind.choices, default=Kind.FNC
    )
    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(
        _("specification"),
        blank=True,
        help_text=_("What is expected: the ticket's facts, or the spec."),
    )
    criticality = models.CharField(
        _("criticality"),
        max_length=10,
        choices=Criticality.choices,
        blank=True,
        help_text=_("FNC tickets only: minor, major or critical."),
    )
    projects = models.ManyToManyField(
        Project,
        verbose_name=_("projects"),
        blank=True,
        related_name="tasks",
    )
    imputation = models.ForeignKey(
        Imputation,
        verbose_name=_("imputation"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tasks",
    )
    labels = models.ManyToManyField(
        Label, verbose_name=_("labels"), blank=True, related_name="tasks"
    )
    note = models.ForeignKey(
        Note,
        verbose_name=_("note"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=Status.choices,
        default=Status.TODO,
    )
    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("assignee"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="planner_tasks",
    )
    due_on = models.DateField(_("due on"), null=True, blank=True)
    estimate = models.DecimalField(
        _("estimate (h)"),
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    done_at = models.DateTimeField(
        _("done at"), null=True, blank=True, editable=False
    )
    #: The task's id in the planner it was imported from, if any.
    legacy_id = models.BigIntegerField(
        null=True, blank=True, unique=True, editable=False
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = _("task")
        verbose_name_plural = _("tasks")

    def __str__(self) -> str:
        return f"{self.reference} {self.title}".strip()

    def clean(self) -> None:
        super().clean()

        if self.kind == self.Kind.FNC and not self.criticality:
            raise ValidationError(
                {"criticality": _("A ticket (FNC) needs its criticality.")}
            )

    def save(self, *args, **kwargs) -> None:
        # Only tickets are critical; a ticket written in a note starts
        # as major, until someone says otherwise.
        if self.kind != self.Kind.FNC:
            self.criticality = ""
        elif not self.criticality:
            self.criticality = self.Criticality.MAJOR

        # Numbered once, in the transaction that stores the number: the
        # series is locked until it commits (generic.numbering).
        with transaction.atomic():
            if not self.reference:
                self.reference = allocate(
                    REFERENCE_PATTERN,
                    namespace="planner.task",
                    exists=lambda code: Task.objects.filter(
                        reference=code
                    ).exists(),
                    kind=self.kind,
                )

            if self.status == self.Status.DONE and self.done_at is None:
                self.done_at = timezone.now()
            elif self.status != self.Status.DONE:
                self.done_at = None

            super().save(*args, **kwargs)


class NoteLine(models.Model):
    """One line of a note, in its place."""

    class Kind(models.TextChoices):
        TEXT = "text", _("Text")
        HEADING = "heading", _("Heading")
        BULLET = "bullet", _("Bullet")
        CHECK = "check", _("To-do")
        TASK = "task", _("Task")

    note = models.ForeignKey(
        Note,
        verbose_name=_("note"),
        on_delete=models.CASCADE,
        related_name="lines",
    )
    position = models.PositiveIntegerField(_("position"), default=0)
    kind = models.CharField(
        _("kind"), max_length=10, choices=Kind.choices, default=Kind.TEXT
    )
    indent = models.PositiveSmallIntegerField(_("indent"), default=0)
    text = models.TextField(_("text"), blank=True)
    done = models.BooleanField(_("done"), default=False)
    task = models.OneToOneField(
        Task,
        verbose_name=_("task"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="line",
    )

    class Meta:
        ordering = ("note", "position", "pk")
        verbose_name = _("note line")
        verbose_name_plural = _("note lines")

    def __str__(self) -> str:
        return self.text[:80] or f"#{self.position}"


class TimeEntryQuerySet(models.QuerySet):
    def running(self) -> "TimeEntryQuerySet":
        return self.filter(ended_at__isnull=True)


class TimeEntry(models.Model):
    """Time spent on a task: from a start to an end, checked later."""

    task = models.ForeignKey(
        Task,
        verbose_name=_("task"),
        on_delete=models.CASCADE,
        related_name="time_entries",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("person"),
        on_delete=models.PROTECT,
        related_name="planner_time_entries",
    )
    started_at = models.DateTimeField(_("started at"), default=timezone.now)
    ended_at = models.DateTimeField(
        _("ended at"),
        null=True,
        blank=True,
        help_text=_("Empty while the timer runs."),
    )
    hours = models.DecimalField(
        _("hours"),
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
    )
    comment = models.TextField(_("comment"), blank=True)
    verified = models.BooleanField(_("verified"), default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("verified by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    verified_at = models.DateTimeField(
        _("verified at"), null=True, blank=True, editable=False
    )
    #: The entry's id in the planner it was imported from, if any.
    legacy_id = models.BigIntegerField(
        null=True, blank=True, unique=True, editable=False
    )

    objects = TimeEntryQuerySet.as_manager()

    class Meta:
        ordering = ("-started_at", "-pk")
        verbose_name = _("time entry")
        verbose_name_plural = _("time entries")
        permissions = [("verify_timeentry", _("Can verify time entries"))]

    def __str__(self) -> str:
        start = timezone.localtime(self.started_at)
        when = start.strftime("%Y-%m-%d %H:%M")

        return f"{self.task.reference} {when}"

    @property
    def is_running(self) -> bool:
        return self.ended_at is None

    def save(self, *args, **kwargs) -> None:
        # Kept with the record, so lists sum and chart it like any
        # number; a running timer counts nothing yet.
        self.hours = (
            length_in_hours(self.ended_at - self.started_at)
            if self.ended_at and self.started_at
            else None
        )
        super().save(*args, **kwargs)


def length_in_hours(length: datetime.timedelta) -> Decimal:
    return (Decimal(length.total_seconds()) / 3600).quantize(Decimal("0.01"))


class KpiRecord(models.Model):
    """Figures read from the business tools (COMET, DES): how many
    people used them in a month, or in a year (``sync_kpi``)."""

    class Period(models.TextChoices):
        MONTH = "month", _("Month")
        YEAR = "year", _("Year")

    period = models.CharField(
        _("period"), max_length=5, choices=Period.choices
    )
    date = models.DateField(
        _("date"), help_text=_("The first day of the month or the year.")
    )
    des_users = models.IntegerField(_("DES users"))
    comet_users = models.IntegerField(_("COMET users"))

    class Meta:
        ordering = ("-date", "period")
        verbose_name = _("tool usage")
        verbose_name_plural = _("tool usage")
        constraints = [
            models.UniqueConstraint(
                fields=("period", "date"), name="planner_kpi_period_date"
            )
        ]

    def __str__(self) -> str:
        if self.period == self.Period.YEAR:
            return f"{self.date:%Y}"

        return f"{self.date:%m-%Y}"

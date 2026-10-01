"""What a run of a task left behind.

One row per run, written as the run goes rather than at the end: a task
that never finishes is the one whose row is worth reading, and a page
watching it should see the steps arrive.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from generic.reports import Report


class TaskRunQuerySet(models.QuerySet):
    def unfinished(self) -> "TaskRunQuerySet":
        return self.filter(
            status__in=(TaskRun.Status.PENDING, TaskRun.Status.RUNNING)
        )

    def failed(self) -> "TaskRunQuerySet":
        return self.filter(status=TaskRun.Status.FAILURE)

    def of(self, name: str) -> "TaskRunQuerySet":
        return self.filter(task=name)


class TaskRun(models.Model):
    """One execution of a declared task, from queued to reported."""

    objects = TaskRunQuerySet.as_manager()

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting")
        RUNNING = "running", _("Running")
        SUCCESS = "success", _("Finished")
        FAILURE = "failure", _("Failed")

    class Trigger(models.TextChoices):
        MANUAL = "manual", _("By hand")
        SCHEDULE = "schedule", _("On schedule")
        CODE = "code", _("By the application")

    task = models.CharField(
        _("task"),
        max_length=200,
        db_index=True,
        help_text=_("The declared name the schedule and Celery both use."),
    )
    #: Copied at the start: a task can be renamed or withdrawn, and a
    #: run of it still has to say what it was.
    label = models.CharField(_("label"), max_length=200, blank=True)
    status = models.CharField(
        _("status"),
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    trigger = models.CharField(
        _("started"),
        max_length=10,
        choices=Trigger.choices,
        default=Trigger.MANUAL,
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("started by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generic_task_runs",
    )
    arguments = models.JSONField(_("arguments"), default=dict, blank=True)

    queued_at = models.DateTimeField(_("queued at"), default=timezone.now)
    started_at = models.DateTimeField(_("started at"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)

    #: Step 3, the headline: one line a notification can carry whole.
    summary = models.CharField(_("summary"), max_length=300, blank=True)
    #: Step 3, the rest: whatever the task added, in the order it did.
    results = models.JSONField(_("results"), default=list, blank=True)
    #: What happened, line by line, with the time of each.
    log = models.JSONField(_("steps"), default=list, blank=True)
    error = models.TextField(_("error"), blank=True)
    #: What the work had to say, as a tree of levelled lines and
    #: sections (:mod:`generic.reports`): written through ``run.report``
    #: (``run.report.warning()``, ``run.report.section()``...) and saved
    #: as it grows.
    tree = models.JSONField(_("report"), default=list, blank=True)
    #: The language of whoever started it: a worker or a thread has no
    #: request to read it from, and the report is written in it.
    language = models.CharField(_("language"), max_length=15, blank=True)

    celery_id = models.CharField(_("Celery id"), max_length=64, blank=True)

    class Meta:
        verbose_name = _("task run")
        verbose_name_plural = _("task runs")
        ordering = ("-queued_at", "-pk")
        permissions = (("run_task", _("Can run a task by hand")),)
        indexes = (
            models.Index(
                fields=("task", "-queued_at"),
                name="generic_run_task_idx",
            ),
        )

    def __str__(self) -> str:
        return f"{self.label or self.task} - {self.get_status_display()}"

    # -- reading ---------------------------------------------------------

    @property
    def is_finished(self) -> bool:
        return self.status in (self.Status.SUCCESS, self.Status.FAILURE)

    @property
    def duration_seconds(self) -> float | None:
        """How long the work took, once it has."""
        if not self.started_at or not self.finished_at:
            return None

        return (self.finished_at - self.started_at).total_seconds()

    def duration_display(self) -> str:
        seconds = self.duration_seconds

        if seconds is None:
            return ""

        if seconds < 60:
            return f"{seconds:.1f} s"

        minutes, rest = divmod(int(seconds), 60)

        return f"{minutes} min {rest:02d} s"

    @property
    def level(self) -> str:
        """How it went, in a toast's words: the report's worst line.

        A failed run is an error whatever its report says; a run that
        finished with errors written in its report is one too, even
        though the work as a whole went to its end.
        """
        if self.status == self.Status.FAILURE:
            return "error"

        if not self.is_finished:
            return "info"

        return self.report.level

    def as_client(self) -> dict[str, Any]:
        """The run as an event payload: what a watching page draws."""
        return {
            "id": self.pk,
            "finished": self.is_finished,
            "level": self.level,
            "report": self.report.as_list(),
            "counts": self.report.counts(),
            "task": self.task,
            "label": self.label or self.task,
            "status": self.status,
            "statusLabel": str(self.get_status_display()),
            "summary": self.summary,
            "results": self.results or [],
            "log": self.log or [],
            "error": self.error,
            "duration": self.duration_display(),
            "url": self.get_absolute_url(),
        }

    def get_absolute_url(self) -> str:
        from django.urls import NoReverseMatch, reverse

        try:
            return reverse("site:generic_taskrun_detail", args=[self.pk])
        except NoReverseMatch:  # pragma: no cover - site not mounted
            return ""

    # -- writing, as the run goes ----------------------------------------

    def note(self, message: str, **extra: Any) -> dict[str, Any]:
        """Record a step. Saved at once: an unfinished run is read live."""
        entry = {
            "at": timezone.now().isoformat(timespec="seconds"),
            "message": str(message),
            **extra,
        }

        self.log = [*(self.log or []), entry]
        self.save(update_fields=["log"])

        return entry

    def add(
        self, label: str, value: Any = None, **extra: Any
    ) -> dict[str, Any]:
        """Add one line to the result this run is building (step 3)."""
        item = {"label": str(label), "value": value, **extra}

        self.results = [*(self.results or []), item]
        self.save(update_fields=["results"])

        return item

    # -- the report, as the run goes -------------------------------------

    @property
    def report(self) -> Report:
        """What the run has to say, as a :class:`generic.reports.Report`.

        ``run.report.warning(...)``, ``with run.report.section(...)``.
        Bound to the row: lines are saved as they arrive (once a second
        at most, and whenever a section closes), so a run's page shows
        a long piece of work as it goes.
        """
        report = self.__dict__.get("_report")

        if report is None or report.nodes is not self.tree:
            if not isinstance(self.tree, list):
                self.tree = []

            report = Report(self.tree, on_change=self._save_report)
            self.__dict__["_report"] = report

        return report

    def _save_report(self) -> None:
        if self.pk:
            self.save(update_fields=["tree"])

"""The task screens.

Three of them, and they answer three different questions:

    the catalogue    what can be run, and run one now (a page)
    the runs         what has run, and what came of it (this file)
    the schedules    what runs by itself (django-celery-beat, below)

The schedules are only there when ``django_celery_beat`` is installed:
its models are the ones the admin plugin shows, declared here as
resources so they get the same tables, filters and forms as everything
else - and so that managing them does not mean sending anybody to
``/admin/``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.apps import apps
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from generic.conf import generic_settings
from generic.sites import ModelResource, TagStyle, action, display, site
from generic.tasks.models import TaskRun
from generic.tasks.registry import registry
from generic.tasks.runner import launch

logger = logging.getLogger(__name__)

#: A run says how it went before it says anything else.
STATUS_COLORS = {
    TaskRun.Status.PENDING: "#64748b",
    TaskRun.Status.RUNNING: "#2563eb",
    TaskRun.Status.SUCCESS: "#16a34a",
    TaskRun.Status.FAILURE: {"background": "#dc2626", "color": "#ffffff"},
}


def beat_installed() -> bool:
    """Whether the scheduler's own models are part of this project."""
    return apps.is_installed("django_celery_beat")


def tasks_are_offered() -> bool:
    """Whether this project has any use for the task pages."""
    setting = generic_settings.SHOW_TASKS

    if setting is not None:
        return bool(setting)

    # The framework's own tasks - the mailings' dispatcher - are no
    # reason to show a project pages it never asked for; nor are
    # operations, which pages of the project start themselves.
    declared = [
        name
        for name in registry.names()
        if not name.startswith("generic.") and registry.get(name).catalogue
    ]

    return bool(declared) or beat_installed()


def runs_are_kept() -> bool:
    """Whether runs need their pages: tasks offered, or operations.

    An operation's run is where its notification leads, so a project
    declaring one gets the run pages without the Tasks page.
    """
    if generic_settings.SHOW_TASKS is not None:
        return bool(generic_settings.SHOW_TASKS)

    return tasks_are_offered() or any(
        not task.catalogue and not task.name.startswith("generic.")
        for task in registry.all()
    )


class TaskRunResource(ModelResource):
    """What has run: one row per run, with what it produced."""

    icon = "history"
    group = _("Tasks")
    order = 1
    label = _("Run")
    label_plural = _("Runs")
    description = _("Every run of every task, and what came of it.")

    list_display = (
        "label",
        "status",
        "trigger",
        "started_at",
        "duration",
        "triggered_by",
        "summary",
    )
    list_display_links = ("label",)
    search_fields = ("task", "label", "summary")
    ordering = ("-queued_at", "-pk")
    tag_fields = {"status": TagStyle(colors=STATUS_COLORS)}
    list_select_related = ("triggered_by",)
    actions = ("run_again", "delete_selected")

    detail_stats = ("status", "duration", "trigger")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    ("task", "label"),
                    ("triggered_by", "arguments"),
                    ("queued_at", "started_at", "finished_at"),
                    "summary",
                    "error",
                )
            },
        ),
    )

    # A run writes itself as it goes - a line per step - and a history
    # of that would be the same story told twice, at ten times the
    # size. The run's own page is its history.
    history = False

    def has_view_permission(self, request: Any, obj: Any = None) -> bool:
        """Readers of the runs - and whoever started this one.

        An operation tells the person who started it where its report
        is; that page has to open for them without the right to read
        everybody's runs.
        """
        if super().has_view_permission(request, obj):
            return True

        user = getattr(request, "user", None)

        return bool(
            obj is not None
            and getattr(user, "pk", None) is not None
            and obj.triggered_by_id == user.pk
        )

    # A run is a record of something that happened: it is not edited,
    # and nothing may be invented by hand.
    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    @display(description=_("Duration"))
    def duration(self, run: TaskRun) -> str:
        return run.duration_display()

    @action(
        description=_("Run again"),
        icon="replay",
        permissions=("generic.run_task",),
        confirm=_("Run the selected tasks again?"),
    )
    def run_again(self, request: Any, queryset: Any) -> str:
        started = 0
        unknown = []
        operations = []

        for run in queryset:
            definition = registry.get(run.task)

            if definition is None:
                unknown.append(run.task)
                continue

            # An operation ran on what its page chose; running it again
            # from here, with nothing chosen, would be a different thing.
            if not definition.catalogue:
                operations.append(definition.title)
                continue

            launch(run.task, user=request.user)
            started += 1

        message = gettext("%(count)s started.") % {"count": started}

        if unknown:
            message += " " + gettext("%(missing)s is no longer declared.") % {
                "missing": ", ".join(sorted(set(unknown)))
            }

        if operations:
            message += " " + gettext(
                "%(operations)s is started from its own page, not from here."
            ) % {"operations": ", ".join(sorted(set(operations)))}

        return message


# -- The scheduler's own models -----------------------------------------


class PeriodicTaskResource(ModelResource):
    """A schedule: which task runs, how often, and whether it is on."""

    icon = "schedule"
    group = _("Tasks")
    order = 0
    label = _("Schedule")
    label_plural = _("Schedules")
    description = _("What runs by itself, and when.")

    list_display = (
        "name",
        "task",
        "schedule_display",
        "enabled",
        "last_run_at",
        "total_run_count",
    )
    search_fields = ("name", "task", "description")
    ordering = ("name",)
    fieldsets = (
        (None, {"fields": ("name", "task", "description")}),
        (
            _("When"),
            {
                "fields": (
                    ("interval", "crontab"),
                    ("clocked", "one_off"),
                    ("start_time", "expires"),
                ),
                "description": _(
                    "One of interval, crontab or clocked. A clocked "
                    "schedule runs once, so it goes with One off."
                ),
            },
        ),
        (
            _("Arguments"),
            {"fields": ("args", "kwargs"), "classes": ("collapse",)},
        ),
        (
            _("Routing"),
            {
                "fields": ("queue", "priority", "expire_seconds"),
                "classes": ("collapse",),
            },
        ),
        (
            _("History"),
            {
                "fields": ("enabled", "last_run_at", "total_run_count"),
                "classes": ("tab",),
            },
        ),
    )
    readonly_fields = ("last_run_at", "total_run_count")
    actions = ("run_now", "enable", "disable", "delete_selected")

    # Who changed a schedule is worth keeping; the counters the
    # scheduler bumps on every tick are not, and recording them would
    # write a version of this row every time anything ran.
    history_exclude = ("last_run_at", "total_run_count", "date_changed")

    @display(description=_("When"))
    def schedule_display(self, obj: Any) -> str:
        return str(obj.schedule) if obj.schedule else ""

    @staticmethod
    def arguments_of(schedule: Any) -> dict[str, Any]:
        """The keyword arguments beat would call this task with.

        Running one by hand should do what the schedule does, so the
        row's own kwargs come along. Anything that is not an object of
        arguments is ignored rather than guessed at.
        """
        try:
            arguments = json.loads(schedule.kwargs or "{}")
        except (TypeError, ValueError):
            return {}

        return arguments if isinstance(arguments, dict) else {}

    @action(
        description=_("Run now"),
        icon="play_arrow",
        permissions=("generic.run_task",),
    )
    def run_now(self, request: Any, queryset: Any) -> str:
        started = 0
        refused = []

        for schedule in queryset:
            if registry.get(schedule.task) is None:
                refused.append(schedule.task)
                continue

            launch(
                schedule.task,
                user=request.user,
                arguments=self.arguments_of(schedule),
            )
            started += 1

        if refused:
            # Celery can run anything by name, but only a declared task
            # announces itself, keeps a run and reports - which is what
            # these pages are about.
            return gettext(
                "%(count)s started. %(missing)s is not declared to the "
                "framework, so it can only run on its schedule."
            ) % {"count": started, "missing": ", ".join(sorted(set(refused)))}

        return gettext("%(count)s started.") % {"count": started}

    @action(description=_("Enable"), icon="toggle_on")
    def enable(self, request: Any, queryset: Any) -> str:
        return self._set_enabled(queryset, True)

    @action(description=_("Disable"), icon="toggle_off", variant="danger")
    def disable(self, request: Any, queryset: Any) -> str:
        return self._set_enabled(queryset, False)

    def _set_enabled(self, queryset: Any, value: bool) -> str:
        count = 0

        # One save each: the scheduler notices a change through the
        # model's own save(), which update() would skip.
        for schedule in queryset:
            schedule.enabled = value
            schedule.save(update_fields=["enabled"])
            count += 1

        from generic.sites.realtime import announce

        announce(self, "bulk")

        return gettext("%(count)s changed.") % {"count": count}


class IntervalScheduleResource(ModelResource):
    icon = "timer"
    group = _("Tasks")
    order = 2
    label = _("Interval")
    label_plural = _("Intervals")
    description = _("Every so many seconds, minutes, hours or days.")
    list_display = ("__str__", "every", "period")
    search_fields = ("period",)


class CrontabScheduleResource(ModelResource):
    icon = "calendar_month"
    group = _("Tasks")
    order = 3
    label = _("Crontab")
    label_plural = _("Crontabs")
    description = _("At a time of day, on the days you choose.")
    list_display = (
        "__str__",
        "minute",
        "hour",
        "day_of_week",
        "day_of_month",
        "month_of_year",
        "timezone",
    )
    search_fields = ("minute", "hour", "day_of_week")


class ClockedScheduleResource(ModelResource):
    icon = "alarm"
    group = _("Tasks")
    order = 4
    label = _("Clocked")
    label_plural = _("Clocked times")
    description = _("Once, at one moment.")
    list_display = ("__str__", "clocked_time")


#: The scheduler's models, and the resource each one is shown with.
BEAT_RESOURCES = (
    ("PeriodicTask", PeriodicTaskResource),
    ("IntervalSchedule", IntervalScheduleResource),
    ("CrontabSchedule", CrontabScheduleResource),
    ("ClockedSchedule", ClockedScheduleResource),
)


def register_screens() -> None:
    """Put the task screens on the site, if this project wants them.

    Called from ``GenericConfig.ready()`` after every app's
    ``resources.py``, so a project gets these pages without declaring
    anything - below its own in the navigation, and gone entirely with
    ``SHOW_TASKS = False``.
    """
    if not runs_are_kept():
        return

    if not site.is_registered(TaskRun):
        site.register(TaskRun, TaskRunResource)

    if not tasks_are_offered():
        return

    if beat_installed():
        register_schedules()

    site.add_link(
        _("Tasks"),
        route="site:tasks",
        icon="playlist_play",
        group=_("Tasks"),
        order=-1,
        permission="generic.run_task",
    )


def register_schedules() -> None:
    """The scheduler's models, as resources of the Tasks group."""
    for model_name, resource_class in BEAT_RESOURCES:
        try:
            model = apps.get_model("django_celery_beat", model_name)
        except LookupError:  # pragma: no cover - an older beat release
            logger.debug("django_celery_beat has no %s", model_name)
            continue

        if not site.is_registered(model):
            site.register(model, resource_class)

"""Every screen of the logbook, declared.

- **Notes**: the list, and each note's page - the editor, where lines
  are written and task lines become tasks (templates/generic/resource/
  planner/note/detail.html, static/planner/note.js), above the note's
  tasks and time. Its lines travel through the note's ``document``
  page (JSON).
- **Tasks**: FNC (tickets) and DM (evolutions), numbered; the kanban
  board by status (and one by person), the due dates on a calendar,
  the timer started and stopped from a task or its line.
- **Time**: the timesheet - an hourly calendar of the week where the
  entries are moved, stretched, added by dragging across the hours or
  by dropping a task on them - and their verification.
- Projects and labels, the dashboard.

Nothing here draws a table, a form, a board or a calendar: the
framework does, from these declarations.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, QuerySet, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from rest_framework.exceptions import APIException

from generic.sites import (
    Allocate,
    Board,
    Calendar,
    Cards,
    Chart,
    Kpi,
    ModelResource,
    RelatedTable,
    TagStyle,
    action,
    display,
    page,
    register,
    site,
)
from generic.sites.realtime import announce
from planner import documents, timers
from planner.models import Label, Note, NoteLine, Project, Task, TimeEntry

GROUP = _("Planner")
TIME = _("Time")

KIND_COLORS = {"FNC": "#dc2626", "DM": "#7c3aed"}
STATUS_COLORS = {
    "backlog": "#64748b",
    "todo": "#2563eb",
    "doing": "#d97706",
    "review": "#9333ea",
    "done": "#16a34a",
}
PRIORITY_COLORS = {
    "low": "#64748b",
    "normal": "#0891b2",
    "high": "#ea580c",
    "urgent": {"background": "#dc2626", "color": "#ffffff"},
}

#: Tasks still to finish.
NOT_DONE = {"column": "status", "operator": "none_of", "value": ["done"]}

#: Work under way: what the timesheet offers to plan first.
UNDER_WAY = {
    "column": "status",
    "operator": "any_of",
    "value": ["todo", "doing", "review"],
}


def hours(value: Any) -> Decimal:
    return (value or Decimal("0")).quantize(Decimal("0.01"))


@register(Label)
class LabelResource(ModelResource):
    icon = "label"
    group = GROUP
    order = 5
    list_display = ("name", "color", "note_count")
    search_fields = ("name",)
    tag_fields = {"name": TagStyle(color="color")}
    form_overrides = {"color": {"widget": "color"}}
    related_tables = (RelatedTable("notes"),)

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(note_total=Count("notes", distinct=True))
        )

    @display(description=_("Notes"), ordering="note_total")
    def note_count(self, label: Label) -> int:
        return getattr(label, "note_total", 0)


@register(Project)
class ProjectResource(ModelResource):
    icon = "workspaces"
    group = GROUP
    order = 4
    description = _("What the notes and the tasks are about.")
    list_display = ("name", "is_active", "open_tasks", "logged")
    search_fields = ("name", "description")
    tag_fields = {"name": TagStyle(color="color")}
    form_overrides = {"color": {"widget": "color"}}
    fields = (("name", "color"), "is_active", "description")
    detail_stats = ("open_tasks", "logged")
    detail_fieldsets = ((None, {"fields": ("is_active", "description")}),)
    related_tables = (
        RelatedTable("tasks", charts=("by_status",)),
        RelatedTable("notes"),
        RelatedTable(
            "time",
            model=TimeEntry,
            lookup="task__project",
            title=_("Time"),
            icon="schedule",
            charts=("by_week",),
        ),
    )
    duplicate = True

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                open_total=Count(
                    "tasks", filter=~Q(tasks__status="done"), distinct=True
                ),
            )
        )

    @display(description=_("Open tasks"), ordering="open_total")
    def open_tasks(self, project: Project) -> int:
        if hasattr(project, "open_total"):
            return project.open_total

        return project.tasks.exclude(status="done").count()

    @display(description=_("Hours logged"))
    def logged(self, project: Project) -> Decimal:
        return hours(
            TimeEntry.objects.filter(task__project=project).aggregate(
                total=Sum("hours")
            )["total"]
        )


@register(Note)
class NoteResource(ModelResource):
    icon = "edit_note"
    group = GROUP
    order = 0
    description = _("Notes written line by line; task lines become tasks.")
    list_display = (
        "title",
        "project",
        "labels",
        "pinned",
        "task_count",
        "open_count",
        "updated_at",
    )
    list_display_hidden = ("open_count",)
    search_fields = ("title", "lines__text", "project__name")
    ordering = ("-pinned", "-updated_at", "-pk")
    tag_fields = {
        "labels": TagStyle(color="color"),
        "project": TagStyle(color="color"),
    }
    fields = ("title", ("project", "pinned"), "labels")
    readonly_fields = ("author", "created_at", "updated_at")
    detail_stats = ("task_count", "open_count", "logged")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "project",
                    "labels",
                    "pinned",
                    "author",
                    "updated_at",
                )
            },
        ),
    )
    related_tables = (
        RelatedTable(
            "tasks",
            columns=(
                "reference",
                "title",
                "kind",
                "status",
                "assignee",
                "time_spent",
            ),
            charts=("by_status",),
        ),
        RelatedTable(
            "time",
            model=TimeEntry,
            lookup="task__note",
            title=_("Time"),
            icon="schedule",
        ),
    )
    bulk_edit_fields = ("project", "labels", "pinned")
    duplicate = True
    presets = {
        _("Pinned"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {"column": "pinned", "operator": "is_true", "value": None}
                ],
            },
        },
    }
    cards = (
        Cards(
            "pinned",
            title=_("Pinned notes"),
            icon="push_pin",
            filters={
                "match": "all",
                "conditions": [
                    {"column": "pinned", "operator": "is_true", "value": None}
                ],
            },
            ordering=("-updated_at",),
            subtitle="project",
            fields=("labels", "updated_at"),
            limit=6,
            order=0,
        ),
    )

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                task_total=Count("tasks", distinct=True),
                open_total=Count(
                    "tasks", filter=~Q(tasks__status="done"), distinct=True
                ),
            )
        )

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        if not change:
            return serializer.save(author=request.user)

        return serializer.save()

    @display(description=_("Tasks"), ordering="task_total")
    def task_count(self, note: Note) -> int:
        if hasattr(note, "task_total"):
            return note.task_total

        return note.tasks.count()

    @display(description=_("Open tasks"), ordering="open_total")
    def open_count(self, note: Note) -> int:
        if hasattr(note, "open_total"):
            return note.open_total

        return note.tasks.exclude(status="done").count()

    @display(description=_("Hours logged"))
    def logged(self, note: Note) -> Decimal:
        return hours(
            TimeEntry.objects.filter(task__note=note).aggregate(
                total=Sum("hours")
            )["total"]
        )

    @page(detail=True, button=False, methods=("get", "post"))
    def document(self, request: Any, note: Note) -> JsonResponse:
        """The note's title and lines, as the editor reads them; posted
        back, written (planner/documents.py)."""
        if request.method == "POST":
            if not self.has_change_permission(request, note):
                return JsonResponse(
                    {"detail": gettext("You may not change this note.")},
                    status=403,
                )

            try:
                documents.write(note, request, read_json(request))
            except APIException as error:
                return JsonResponse(
                    error_body(error.detail), status=error.status_code
                )

            note.refresh_from_db()

        answer = documents.read(note, request, self.site)
        answer["canEdit"] = self.has_change_permission(request, note)
        answer["canAddTasks"] = request.user.has_perm("planner.add_task")
        answer["canTime"] = request.user.has_perm("planner.add_timeentry")

        return JsonResponse(answer)


def read_json(request: Any) -> Any:
    import json

    try:
        return json.loads(request.body or b"null")
    except ValueError:
        return None


def error_body(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        return {
            key: [str(item) for item in value] for key, value in detail.items()
        }

    if isinstance(detail, list):
        return {"detail": " ".join(str(item) for item in detail)}

    return {"detail": str(detail)}


@register(NoteLine)
class NoteLineResource(ModelResource):
    """Kept for the history of each line; written by the note's editor."""

    icon = "notes"
    group = GROUP
    show_in_navigation = False
    list_display = ("note", "position", "kind", "text", "task")
    search_fields = ("text",)

    def has_module_permission(self, request: Any) -> bool:
        # Not a screen of its own, on the dashboard either.
        return False


@register(Task)
class TaskResource(ModelResource):
    icon = "task_alt"
    group = GROUP
    order = 1
    description = _("FNC tickets and DM evolutions, from the notes or not.")
    list_display = (
        "reference",
        "title",
        "kind",
        "status",
        "priority",
        "project",
        "assignee",
        "due_on",
        "time_spent",
        "estimate",
        "note",
    )
    list_display_hidden = ("estimate", "note")
    search_fields = ("reference", "title", "description", "project__name")
    ordering = ("-created_at", "-pk")
    tag_fields = {
        "kind": TagStyle(colors=KIND_COLORS),
        "status": TagStyle(colors=STATUS_COLORS),
        "priority": TagStyle(colors=PRIORITY_COLORS),
        "project": TagStyle(color="color"),
    }
    fieldsets = (
        (None, {"fields": (("kind", "title"), "description")}),
        (
            _("Planning"),
            {
                "fields": (
                    ("status", "priority"),
                    ("project", "assignee"),
                    ("due_on", "estimate"),
                    "note",
                )
            },
        ),
    )
    form_overrides = {"description": {"rows": 8}}
    detail_stats = ("time_spent", "estimate", "remaining")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "kind",
                    "status",
                    "priority",
                    "project",
                    "assignee",
                    "due_on",
                    "note",
                )
            },
        ),
        (_("Specification"), {"fields": ("description",)}),
    )
    related_tables = (
        RelatedTable(
            "time_entries",
            columns=("started_at", "ended_at", "hours", "user", "check_state"),
            charts=("by_person",),
            title=_("Time"),
        ),
    )
    editable_fields = ("status", "priority", "assignee", "due_on")
    bulk_edit_fields = (
        "status",
        "priority",
        "project",
        "assignee",
        "due_on",
    )
    actions = ("start_timer", "stop_timer", "mark_done", "delete_selected")
    duplicate = True
    compare_fields = True
    presets = {
        _("My open tasks"): {
            "filters": {"match": "all", "conditions": [NOT_DONE]},
            "order": [["priority", "desc"]],
        },
        _("Tickets (FNC)"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {"column": "kind", "operator": "any_of", "value": ["FNC"]},
                    NOT_DONE,
                ],
            },
        },
        _("Evolutions (DM)"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {"column": "kind", "operator": "any_of", "value": ["DM"]},
                    NOT_DONE,
                ],
            },
        },
    }
    charts = (
        Chart(
            "by_status",
            title=_("By status"),
            type="donut",
            group_by="status",
        ),
        Chart(
            "by_kind",
            title=_("Tickets and evolutions"),
            group_by="project",
            split_by="kind",
            stacked=True,
            horizontal=True,
        ),
    )
    list_charts = ("by_status", "by_kind")
    chart_builder = True

    # The kanban: a column per status, a card per task; dragging a card
    # changes its status. And the same tasks by person.
    boards = (
        Board(
            "board",
            field="status",
            title=_("Board"),
            icon="view_kanban",
            description=_("Every task in the column of its status."),
            color="kind",
            fields=("project", "priority", "assignee", "time_spent"),
            editable=True,
            navigation=True,
        ),
        Board(
            "people",
            field="assignee",
            title=_("Who does what"),
            icon="group",
            description=_("The tasks still open, by person."),
            color="status",
            fields=("project", "due_on"),
            editable=True,
        ),
    )
    calendars = (
        Calendar(
            "due",
            date="due_on",
            title=_("Due dates"),
            icon="event",
            color="kind",
            fields=("status", "assignee"),
            editable=True,
        ),
    )
    kpis = (
        Kpi(
            "open-tickets",
            title=_("Open tickets (FNC)"),
            icon="bug_report",
            filters={
                "match": "all",
                "conditions": [
                    {"column": "kind", "operator": "any_of", "value": ["FNC"]},
                    NOT_DONE,
                ],
            },
            warning=10,
            danger=20,
            order=0,
        ),
        Kpi(
            "open-evolutions",
            title=_("Open evolutions (DM)"),
            icon="rocket_launch",
            filters={
                "match": "all",
                "conditions": [
                    {"column": "kind", "operator": "any_of", "value": ["DM"]},
                    NOT_DONE,
                ],
            },
            order=1,
        ),
    )
    cards = (
        Cards(
            "in-progress",
            title=_("In progress"),
            icon="pending_actions",
            filters={
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "any_of",
                        "value": ["doing"],
                    }
                ],
            },
            ordering=("due_on",),
            subtitle="project",
            fields=("kind", "assignee", "time_spent"),
            limit=6,
            order=1,
        ),
    )

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(spent_total=Sum("time_entries__hours"))
        )

    def get_initial(self, request: Any) -> dict[str, Any]:
        return {
            "assignee": str(request.user.pk),
            **super().get_initial(request),
        }

    @display(description=_("Time spent"), ordering="spent_total")
    def time_spent(self, task: Task) -> Decimal:
        if hasattr(task, "spent_total"):
            return hours(task.spent_total)

        return hours(task.time_entries.aggregate(total=Sum("hours"))["total"])

    @display(description=_("Remaining (h)"))
    def remaining(self, task: Task) -> Any:
        if task.estimate is None:
            return None

        return hours(task.estimate - self.time_spent(task))

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        if name in ("start_timer", "stop_timer"):
            running = timers.running(request.user)
            on_this = running is not None and running.task_id == obj.pk

            return on_this if name == "stop_timer" else not on_this

        if name == "mark_done":
            return obj.status != Task.Status.DONE

        return super().has_record_action(request, obj, name)

    @action(
        description=_("Start the timer"),
        icon="play_arrow",
        permissions=("planner.add_timeentry",),
        help=_("Log time on this task from now; any other timer stops."),
    )
    def start_timer(self, request: Any, queryset: QuerySet) -> Any:
        task = queryset.first()

        if task is None or queryset.count() != 1:
            return {
                "message": gettext("Start the timer on one task at a time."),
                "level": "warning",
            }

        timers.start(request.user, task)

        return gettext("The timer runs on %(task)s.") % {"task": task}

    @action(
        description=_("Stop the timer"),
        icon="stop",
        permissions=("planner.add_timeentry",),
        help=_("End the time entry running now."),
    )
    def stop_timer(self, request: Any, queryset: QuerySet) -> Any:
        entry = timers.stop(request.user)

        if entry is None:
            return {"message": gettext("No timer runs."), "level": "info"}

        return gettext("%(hours)s h logged on %(task)s.") % {
            "hours": entry.hours,
            "task": entry.task,
        }

    @action(
        description=_("Mark as done"),
        icon="done_all",
        permissions=("change",),
        help=_("Put the task in the Done column."),
    )
    def mark_done(self, request: Any, queryset: QuerySet) -> str:
        count = 0

        for task in queryset.exclude(status=Task.Status.DONE):
            task.status = Task.Status.DONE
            task.save()
            count += 1

        return ngettext(
            "%(count)s task done.", "%(count)s tasks done.", count
        ) % {"count": count}

    @page(detail=True, button=False, methods=("post",))
    def timer(self, request: Any, task: Task) -> JsonResponse:
        """Start the timer on this task, or stop it if it runs here: the
        note editor's play button."""
        if not request.user.has_perm("planner.add_timeentry"):
            raise PermissionDenied()

        entry = timers.toggle(request.user, task)

        return JsonResponse(
            {
                "running": entry is not None,
                "task": task.pk,
                "hours": str(self.time_spent(task)),
            }
        )


#: Not yet checked, ended: what the verification goes through.
TO_VERIFY = {"column": "verified", "operator": "is_false", "value": None}


@register(TimeEntry)
class TimeEntryResource(ModelResource):
    icon = "schedule"
    group = TIME
    order = 0
    label_plural = _("time entries")
    description = _("Time logged on the tasks, then verified.")
    list_display = (
        "started_at",
        "ended_at",
        "hours",
        "task",
        "task__kind",
        "task__project",
        "user",
        "comment",
        "check_state",
        "verified",
    )
    list_display_hidden = ("verified",)
    search_fields = ("comment", "task__reference", "task__title")
    ordering = ("-started_at", "-pk")
    tag_fields = {"task__kind": TagStyle(colors=KIND_COLORS)}
    fields = ("task", "user", ("started_at", "ended_at"), "comment")
    readonly_fields = ("verified_by", "verified_at")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "task",
                    "user",
                    "started_at",
                    "ended_at",
                    "hours",
                    "comment",
                )
            },
        ),
        (
            _("Verification"),
            {"fields": ("check_state", "verified_by", "verified_at")},
        ),
    )
    editable_fields = ("started_at", "ended_at", "comment")
    bulk_edit_fields = ("task", "user")
    actions = ("verify", "unverify", "delete_selected")
    presets = {
        _("To verify"): {
            "filters": {
                "match": "all",
                "conditions": [
                    TO_VERIFY,
                    {
                        "column": "ended_at",
                        "operator": "not_empty",
                        "value": None,
                    },
                ],
            },
            "order": [["started_at", "asc"]],
        },
        _("This week"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "started_at",
                        "operator": "this_week",
                        "value": None,
                    }
                ],
            },
        },
    }

    # The verification page: the week as hours. Entries are moved and
    # stretched where they belong, hours dragged across to add one, and
    # a task dropped on a time to log it there; then verified.
    calendars = (
        Calendar(
            "timesheet",
            date="started_at",
            end="ended_at",
            title=_("Timesheet"),
            icon="event_note",
            description=_(
                "The time logged, placed on the hours: move it, stretch "
                "it, drop a task on a time, then verify the week."
            ),
            label="task",
            color="check_state",
            fields=("project", "user"),
            editable=True,
            navigation=True,
            hours=(7, 20),
            step=15,
            views=("week", "day", "month", "list"),
            allocate=Allocate(
                "task",
                title=_("Tasks under way"),
                filters={"match": "all", "conditions": [UNDER_WAY]},
                ordering=("-created_at",),
                fields=("project",),
                color="kind",
                duration=60,
            ),
        ),
    )

    charts = (
        Chart(
            "by_week",
            title=_("Hours logged"),
            icon="schedule",
            group_by="started_at",
            split_by="task__kind",
            stacked=True,
            value=Sum("hours"),
            value_label=_("Hours"),
            unit="h",
            decimals=1,
            period="week",
            periods=("day", "week", "month"),
        ),
        Chart(
            "by_project",
            title=_("Hours by project"),
            group_by="task__project",
            value=Sum("hours"),
            value_label=_("Hours"),
            unit="h",
            decimals=1,
            horizontal=True,
            limit=8,
        ),
        Chart(
            "by_person",
            title=_("Hours by person"),
            group_by="user",
            value=Sum("hours"),
            value_label=_("Hours"),
            unit="h",
            decimals=1,
            horizontal=True,
        ),
    )
    list_charts = ("by_week", "by_project")

    kpis = (
        Kpi(
            "this-week",
            title=_("Hours this week"),
            icon="schedule",
            filters={
                "match": "all",
                "conditions": [
                    {
                        "column": "started_at",
                        "operator": "this_week",
                        "value": None,
                    }
                ],
            },
            value=Sum("hours"),
            unit="h",
            decimals=1,
            order=2,
        ),
        Kpi(
            "to-verify",
            title=_("Entries to verify"),
            icon="fact_check",
            filters={
                "match": "all",
                "conditions": [
                    TO_VERIFY,
                    {
                        "column": "ended_at",
                        "operator": "not_empty",
                        "value": None,
                    },
                ],
            },
            warning=20,
            danger=60,
            order=3,
        ),
    )
    cards = (
        Cards(
            "running",
            title=_("Timers running"),
            icon="timer",
            filters={
                "match": "all",
                "conditions": [
                    {"column": "ended_at", "operator": "empty", "value": None}
                ],
            },
            ordering=("-started_at",),
            subtitle="task",
            fields=("user", "started_at"),
            limit=4,
            order=2,
        ),
    )

    def get_initial(self, request: Any) -> dict[str, Any]:
        return {"user": str(request.user.pk), **super().get_initial(request)}

    def create_editable(
        self, request: Any, values: dict[str, Any], fixed: dict[str, Any]
    ) -> Any:
        # A task dropped on the timesheet: time of whoever dropped it.
        return super().create_editable(
            request, values, {"user": request.user.pk, **fixed}
        )

    @display(description=_("Project"))
    def project(self, entry: TimeEntry) -> Any:
        return entry.task.project

    @display(description=_("Check"), tags=True)
    def check_state(self, entry: TimeEntry) -> list[dict[str, str]]:
        if entry.ended_at is None:
            return [{"label": gettext("Running"), "color": "#2563eb"}]

        if entry.verified:
            return [{"label": gettext("Verified"), "color": "#16a34a"}]

        return [{"label": gettext("To verify"), "color": "#d97706"}]

    @action(
        description=_("Verify"),
        icon="fact_check",
        permissions=("planner.verify_timeentry",),
        help=_("The time is right: mark it verified."),
    )
    def verify(self, request: Any, queryset: QuerySet) -> str:
        count = queryset.filter(verified=False, ended_at__isnull=False).update(
            verified=True,
            verified_by=request.user,
            verified_at=timezone.now(),
        )
        announce(self, "bulk")

        return ngettext(
            "%(count)s entry verified.", "%(count)s entries verified.", count
        ) % {"count": count}

    @action(
        description=_("Back to verify"),
        icon="undo",
        permissions=("planner.verify_timeentry",),
        help=_("Look at this time again."),
    )
    def unverify(self, request: Any, queryset: QuerySet) -> str:
        count = queryset.filter(verified=True).update(
            verified=False, verified_by=None, verified_at=None
        )
        announce(self, "bulk")

        return ngettext(
            "%(count)s entry to verify again.",
            "%(count)s entries to verify again.",
            count,
        ) % {"count": count}

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        if name == "verify":
            return not obj.verified and obj.ended_at is not None

        if name == "unverify":
            return obj.verified

        return super().has_record_action(request, obj, name)


site.add_shortcut(
    _("Write a note"),
    route="site:planner_note_add",
    icon="edit_note",
    description=_("Lines of text; task lines become tasks."),
    permission="planner.add_note",
    order=0,
)
site.add_shortcut(
    _("The board"),
    route="site:planner_task_board",
    icon="view_kanban",
    description=_("The tasks by status: drag them along."),
    permission="planner.view_task",
    order=1,
)
site.add_shortcut(
    _("The timesheet"),
    route="site:planner_timeentry_timesheet",
    icon="event_note",
    description=_("This week's time, on the hours, to check."),
    permission="planner.view_timeentry",
    order=2,
)

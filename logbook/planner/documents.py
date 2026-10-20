"""A note as the editor reads and writes it: its title and its lines.

The editor (static/planner/note.js) sends the whole note back each time
it saves - a few hundred lines at most - and ``write`` makes the stored
lines match it in one transaction: lines kept, moved, added, removed.
A task line is where a task is born: the first time a line is saved as
one, a ``Task`` is created, numbered, and linked to it; after that the
line's text is the task's title. A task line turned back into text, or
removed, lets its task go: the task is kept once it is more than that
line - time logged on it, a specification written, work started - and
deleted otherwise.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext
from rest_framework.exceptions import PermissionDenied, ValidationError

from planner.models import Note, NoteLine, Task, TimeEntry

#: The most lines one note keeps.
MAX_LINES = 2000

#: The deepest a line is indented.
MAX_INDENT = 4

#: The longest text a line holds.
MAX_TEXT = 5000


def read(note: Note, request: Any, site: Any) -> dict[str, Any]:
    """The note, its lines and their tasks, for the editor."""
    user = request.user
    lines = list(note.lines.select_related("task"))
    tasks = [line.task for line in lines if line.task_id]
    hours = dict(
        TimeEntry.objects.filter(task__in=tasks)
        .values("task")
        .annotate(total=Sum("hours"))
        .values_list("task", "total")
    )
    running = (
        TimeEntry.objects.running()
        .filter(user=user)
        .values_list("task", flat=True)
        .first()
    )
    task_resource = site.get_resource(Task)

    def task_of(task: Task | None) -> dict[str, Any] | None:
        if task is None:
            return None

        return {
            "id": task.pk,
            "reference": task.reference,
            "kind": task.kind,
            "criticality": task.criticality,
            "status": task.status,
            "statusLabel": str(task.get_status_display()),
            "url": task_resource.get_object_url(task.pk),
            "api": task_resource._reverse(
                task_resource.api_url_name("detail"), pk=task.pk
            ),
            "timerUrl": task_resource.get_page_url("timer", task),
            "hours": str(hours.get(task.pk) or "0.00"),
            "running": running == task.pk,
        }

    return {
        "id": note.pk,
        "title": note.title,
        "statuses": [
            {"value": value, "label": str(label)}
            for value, label in Task.Status.choices
        ],
        "criticalities": [
            {"value": value, "label": str(label)}
            for value, label in Task.Criticality.choices
        ],
        "lines": [
            {
                "id": line.pk,
                "kind": line.kind,
                "indent": line.indent,
                "text": line.text,
                "done": line.done,
                "task": task_of(line.task),
            }
            for line in lines
        ],
    }


def clean_lines(payload: Any) -> tuple[str | None, list[dict[str, Any]]]:
    """The title and the lines sent, checked; a 400 naming what is
    wrong otherwise."""
    if not isinstance(payload, dict) or not isinstance(
        payload.get("lines"), list
    ):
        raise ValidationError(gettext("Send the note's lines."))

    title = payload.get("title")

    if title is not None:
        title = str(title).strip()[:200]

        if not title:
            raise ValidationError(
                {"title": [gettext("A note needs a title.")]}
            )

    if len(payload["lines"]) > MAX_LINES:
        raise ValidationError(
            gettext("A note holds at most %(count)s lines.")
            % {"count": MAX_LINES}
        )

    kinds = set(NoteLine.Kind.values)
    task_kinds = set(Task.Kind.values)
    lines = []

    for number, item in enumerate(payload["lines"], start=1):
        if not isinstance(item, dict) or item.get("kind") not in kinds:
            raise ValidationError(
                gettext("Line %(number)s cannot be read.") % {"number": number}
            )

        try:
            indent = min(max(int(item.get("indent") or 0), 0), MAX_INDENT)
        except (TypeError, ValueError):
            indent = 0

        line_id = item.get("id")

        lines.append(
            {
                "id": line_id if isinstance(line_id, int) else None,
                "kind": item["kind"],
                "indent": indent,
                "text": str(item.get("text") or "")[:MAX_TEXT],
                "done": bool(item.get("done")),
                "task_kind": (
                    item.get("taskKind")
                    if item.get("taskKind") in task_kinds
                    else Task.Kind.FNC
                ),
            }
        )

    return title, lines


def task_title(text: str) -> str:
    title = " ".join(text.split())[:200]

    return title or gettext("Untitled task")


def write(note: Note, request: Any, payload: Any) -> None:
    """Make the note's lines what the editor sent."""
    user = request.user
    title, lines = clean_lines(payload)
    may_add = user.has_perm("planner.add_task")
    may_change = user.has_perm("planner.change_task")

    with transaction.atomic():
        note = Note.objects.select_for_update().get(pk=note.pk)
        kept = {line.pk: line for line in note.lines.select_related("task")}

        for position, item in enumerate(lines):
            line = kept.pop(item["id"], None) or NoteLine(note=note)
            line.position = position
            line.kind = item["kind"]
            line.indent = item["indent"]
            line.text = item["text"]
            line.done = item["done"] if item["kind"] == "check" else False

            if line.kind == NoteLine.Kind.TASK:
                line.task = sync_task(
                    note, line, item, user, may_add, may_change
                )
            elif line.task_id:
                release(line.task)
                line.task = None

            line.save()

        for line in kept.values():
            task = line.task
            line.delete()

            if task is not None:
                release(task)

        if title is not None and title != note.title:
            note.title = title

        # Saved either way: "updated at" says when it was last written.
        note.save()


def sync_task(
    note: Note,
    line: NoteLine,
    item: dict[str, Any],
    user: Any,
    may_add: bool,
    may_change: bool,
) -> Task:
    """The line's task: created the first time, its title kept equal to
    the line's text after that."""
    task = line.task
    title = task_title(item["text"])

    if task is None:
        if not may_add:
            raise PermissionDenied(
                gettext("You may not create tasks: this line stays text.")
            )

        task = Task.objects.create(
            kind=item["task_kind"],
            title=title,
            note=note,
            assignee=user if user.is_authenticated else None,
        )

        # About what the note is about, to begin with.
        if note.project_id:
            task.projects.add(note.project_id)

        return task

    if task.title != title:
        if not may_change:
            raise PermissionDenied(gettext("You may not change tasks."))

        task.title = title
        task.save(update_fields=["title"])

    return task


def release(task: Task) -> None:
    """A task its line let go: kept once it is more than a line - time
    logged on it (the timesheet points at it), a specification written,
    work started - deleted otherwise."""
    untouched = (
        not task.description
        and task.status in (Task.Status.BACKLOG, Task.Status.TODO)
        and not task.time_entries.exists()
    )

    if untouched:
        task.delete()

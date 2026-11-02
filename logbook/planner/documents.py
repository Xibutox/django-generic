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

A task line can also show a task that exists: a new line, or one whose
task is replaced (``link``); a task taken from another note leaves its
title there, as text.

``attach`` is the other way round: text from a note - lines the editor
selected - added to the specification of a task that already exists,
under the note's title and the day.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.utils import formats, timezone
from django.utils.translation import gettext
from rest_framework.exceptions import PermissionDenied, ValidationError

from generic.search import text_lookup
from planner.models import Note, NoteLine, Task, TimeEntry

#: The most lines one note keeps.
MAX_LINES = 2000

#: The deepest a line is indented.
MAX_INDENT = 4

#: The longest text a line holds.
MAX_TEXT = 5000

#: The most text attached to a task at once.
MAX_ATTACHED = 20000

#: The tasks offered to attach to, at most.
ATTACH_CHOICES = 20


def read(note: Note, request: Any, site: Any) -> dict[str, Any]:
    """The note, its lines and their tasks, for the editor."""
    user = request.user
    lines = list(note.lines.select_related("task__assignee"))
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
            "dueOn": task.due_on.isoformat() if task.due_on else None,
            "assignee": (
                (task.assignee.get_full_name() or task.assignee.get_username())
                if task.assignee
                else None
            ),
        }

    return {
        "id": note.pk,
        "title": note.title,
        # Past it, an open task's due date is late.
        "today": timezone.localdate().isoformat(),
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
        task_id = item.get("taskId")

        lines.append(
            {
                "id": line_id if isinstance(line_id, int) else None,
                "kind": item["kind"],
                "indent": indent,
                "text": str(item.get("text") or "")[:MAX_TEXT],
                "done": bool(item.get("done")),
                # An existing task the line is to show (attach_choices).
                "task_id": (
                    task_id
                    if isinstance(task_id, int) and item["kind"] == "task"
                    else None
                ),
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


def write(note: Note, request: Any, payload: Any, site: Any = None) -> None:
    """Make the note's lines what the editor sent."""
    user = request.user
    tasks = (
        site.get_resource(Task).get_queryset(request)
        if site is not None
        else Task.objects.all()
    )
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

            # An existing task asked for: put on a new task line, or in
            # place of the line's own task, which is let go.
            asked = item["task_id"]

            if (
                line.kind == NoteLine.Kind.TASK
                and asked is not None
                and asked != line.task_id
            ):
                former = line.task
                line.task = link(note, item, tasks, may_change)

                if former is not None:
                    release(former)

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


def link(
    note: Note, item: dict[str, Any], tasks: Any, may_change: bool
) -> Task | None:
    """An existing task put in the note by a task line. It moves to the
    note; a line of another note that showed it stays there as text,
    its title. None when none is asked."""
    if item["task_id"] is None:
        return None

    if not may_change:
        raise PermissionDenied(gettext("You may not change tasks."))

    # Locked alone (the visible tasks may be annotated), then checked:
    # visible, and no line of this note shows it already.
    task = (
        Task.objects.select_for_update(of=("self",))
        .filter(pk=item["task_id"])
        .first()
    )
    shown = (
        NoteLine.objects.select_for_update().filter(task=task).first()
        if task is not None
        else None
    )
    free = (
        task is not None
        and tasks.filter(pk=task.pk).exists()
        and (shown is None or shown.note_id != note.pk)
    )

    if task is None or not free:
        raise ValidationError(
            gettext(
                "This task is already in this note, or cannot be found: "
                "reload the page."
            )
        )

    if shown is not None:
        # The other note keeps the words, not the task.
        shown.kind = NoteLine.Kind.TEXT
        shown.text = task.title
        shown.task = None
        shown.save(update_fields=["kind", "text", "task"])

    if task.note_id != note.pk:
        task.note = note
        task.save(update_fields=["note"])

    return task


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


def attach_choices(
    note: Note, request: Any, site: Any, term: str
) -> list[dict[str, Any]]:
    """The tasks text may be attached to, searched by reference or
    title: the note's own first, then the open ones, the newest first."""
    resource = site.get_resource(Task)
    queryset = resource.get_queryset(request).select_related("line__note")
    term = " ".join(str(term or "").split())[:100]

    for word in term.split():
        queryset = queryset.filter(
            Q(**{text_lookup("reference"): word})
            | Q(**{text_lookup("title"): word})
        )

    queryset = queryset.annotate(
        here=Case(
            When(note=note, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        closed=Case(
            When(status=Task.Status.DONE, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
    ).order_by("here", "closed", "-created_at", "-pk")

    return [
        {
            "id": task.pk,
            "reference": task.reference,
            "kind": task.kind,
            "title": task.title,
            "status": task.status,
            "statusLabel": str(task.get_status_display()),
            # The note whose line shows it, if any: such a task can take
            # text, not be put in this note too.
            "inNote": line_note(task),
            "here": line_note_id(task) == note.pk,
        }
        for task in queryset[:ATTACH_CHOICES]
    ]


def task_line(task: Task) -> NoteLine | None:
    try:
        return task.line
    except NoteLine.DoesNotExist:
        return None


def line_note(task: Task) -> str | None:
    line = task_line(task)

    return line.note.title if line is not None else None


def line_note_id(task: Task) -> int | None:
    line = task_line(task)

    return line.note_id if line is not None else None


def attach(
    note: Note, request: Any, site: Any, payload: Any
) -> dict[str, Any]:
    """Text from the note added to an existing task's specification,
    under the note's title and today's date."""
    if not isinstance(payload, dict):
        raise ValidationError(gettext("Send the task and the text."))

    text = str(payload.get("text") or "").strip()
    task_id = payload.get("task")

    if not text:
        raise ValidationError({"text": [gettext("There is no text.")]})

    if len(text) > MAX_ATTACHED:
        raise ValidationError(
            {
                "text": [
                    gettext("Attach at most %(count)s characters at once.")
                    % {"count": MAX_ATTACHED}
                ]
            }
        )

    if not isinstance(task_id, int):
        raise ValidationError({"task": [gettext("Pick a task.")]})

    resource = site.get_resource(Task)
    task = resource.get_queryset(request).filter(pk=task_id).first()

    if task is None:
        raise ValidationError(
            {"task": [gettext("This task cannot be found.")]}
        )

    if not resource.has_change_permission(request, task):
        raise PermissionDenied(gettext("You may not change this task."))

    heading = gettext('From the note "%(note)s", %(date)s:') % {
        "note": note.title,
        "date": formats.date_format(timezone.localdate(), "DATE_FORMAT"),
    }
    added = f"{heading}\n{text}"
    current = task.description.rstrip()
    task.description = f"{current}\n\n{added}" if current else added
    # A save of its own: the task's history says who added what.
    task.save()

    return {
        "id": task.pk,
        "reference": task.reference,
        "url": resource.get_object_url(task.pk),
    }

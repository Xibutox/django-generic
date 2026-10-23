"""The timer: time logged as it is spent.

A person has at most one timer running - a time entry without an end.
Starting one on a task stops whichever ran, at the same instant, so
the two entries touch and no minute is counted twice; a task still to
do is then in progress.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from planner.models import Task, TimeEntry


def running(user: Any) -> TimeEntry | None:
    """The person's running entry, if any."""
    return (
        TimeEntry.objects.running()
        .filter(user=user)
        .select_related("task")
        .first()
    )


def stop(user: Any, at: Any = None) -> TimeEntry | None:
    """End the person's running entry now; the one stopped, or None."""
    with transaction.atomic():
        entry = (
            TimeEntry.objects.running()
            .select_for_update()
            .filter(user=user)
            .first()
        )

        if entry is None:
            return None

        entry.ended_at = max(at or timezone.now(), entry.started_at)
        entry.save()

        return entry


def start(user: Any, task: Task) -> TimeEntry:
    """A new running entry on ``task``, the previous one stopped."""
    with transaction.atomic():
        now = timezone.now()
        stop(user, at=now)

        # Work on it has started: on the board, it moves along.
        if task.status in (Task.Status.BACKLOG, Task.Status.TODO):
            task.status = Task.Status.DOING
            task.save()

        return TimeEntry.objects.create(task=task, user=user, started_at=now)


def toggle(user: Any, task: Task) -> TimeEntry | None:
    """Stop the timer when it runs on ``task``, start it there
    otherwise: the running entry after it, or None."""
    current = running(user)

    if current is not None and current.task_id == task.pk:
        stop(user)

        return None

    return start(user, task)

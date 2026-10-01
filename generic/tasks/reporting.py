"""Who hears about a run, and what it says.

Steps 1 and 4 of a run are the same problem twice - say something to
some people - so they are one piece of code with two messages. What a
task declares is the channels; who they reach is the audience; how they
are sent is :mod:`generic.delivery`, which the watch module uses too.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _

from generic import delivery
from generic.delivery import NotificationLevel
from generic.reports import describe_counts
from generic.tasks.models import TaskRun
from generic.tasks.registry import TaskDefinition

logger = logging.getLogger(__name__)


# -- who ----------------------------------------------------------------


def recipients(definition: TaskDefinition, run: TaskRun) -> list[Any]:
    """The users a run reports to, by the task's declaration."""
    audience = definition.audience

    if callable(audience):
        return [user for user in audience(run) if user is not None]

    # With their preferences, which the delivery reads for each of them:
    # one query for the lot rather than one per person.
    users = (
        get_user_model()
        ._default_manager.filter(is_active=True)
        .select_related("generic_preferences")
    )

    if audience == "everyone":
        return list(users)

    if audience == "staff":
        return list(users.filter(is_staff=True))

    if audience == "superusers":
        return list(users.filter(is_superuser=True))

    # "trigger": whoever pressed the button. A scheduled run has nobody
    # to answer to, which is what the other audiences are for.
    return [run.triggered_by] if run.triggered_by is not None else []


# -- what ---------------------------------------------------------------


def _started_message(
    run: TaskRun,
    definition: TaskDefinition,
) -> tuple[str, str, int]:
    return (
        _("%(task)s has started") % {"task": run.label or run.task},
        # Resolved here rather than where it was declared: the reader's
        # language is the one this group is being written in.
        str(definition.description or ""),
        NotificationLevel.INFO,
    )


def _finished_message(
    run: TaskRun,
    definition: TaskDefinition,
) -> tuple[str, str, int]:
    if run.status == TaskRun.Status.FAILURE:
        return (
            _("%(task)s failed") % {"task": run.label or run.task},
            run.error or run.summary,
            NotificationLevel.CRITICAL,
        )

    body = run.summary or _("Nothing to report.")

    if run.duration_display():
        body = _("%(summary)s (%(duration)s)") % {
            "summary": body,
            "duration": run.duration_display(),
        }

    # Finished is not the same as fine: a report with warnings or errors
    # in it says so on the bell as well as on the page.
    level = run.level

    if level in ("warning", "error"):
        counts = describe_counts(run.report.counts())

        if counts not in body:
            body = f"{body} - {counts}"

    return (
        _("%(task)s has finished") % {"task": run.label or run.task},
        body,
        LEVELS.get(level, NotificationLevel.SUCCESS),
    )


#: A report's level, as a notification's.
LEVELS = {
    "info": NotificationLevel.SUCCESS,
    "success": NotificationLevel.SUCCESS,
    "warning": NotificationLevel.WARNING,
    "error": NotificationLevel.CRITICAL,
}


# -- how ----------------------------------------------------------------


def report_through(
    run: TaskRun,
    definition: TaskDefinition,
    channels: Iterable[str],
    *,
    message: Callable[[TaskRun, TaskDefinition], tuple[str, str, int]],
) -> list[Any]:
    """Send one message through the channels a task declared."""
    return delivery.deliver(
        recipients(definition, run),
        channels=channels,
        message=lambda: message(run, definition),
        url=run.get_absolute_url(),
        content_object=run,
        context=f"task run {run.pk}",
    )


def announce(run: TaskRun, definition: TaskDefinition) -> list[Any]:
    """Step 1: say that the work is about to start."""
    return report_through(
        run,
        definition,
        definition.announce,
        message=_started_message,
    )


def report(run: TaskRun, definition: TaskDefinition) -> list[Any]:
    """Step 4: say how it went, and where the whole of it is."""
    return report_through(
        run,
        definition,
        definition.report,
        message=_finished_message,
    )

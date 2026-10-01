"""Declared tasks: announced, run, collected, reported.

A project declares what it knows how to do::

    from generic.tasks import managed_task

    @managed_task(
        label=_("Nightly digest"),
        announce=("notification",),          # step 1: it is starting
        report=("notification", "mail"),     # step 4: how it went
        audience="staff",
    )
    def nightly_digest(run):
        run.note(_("Collecting"))
        run.add(_("Tickets"), 12)

        return _("12 tickets")

*When* it runs is a separate question, answered by a schedule
(``django_celery_beat``, managed from the site) or by somebody pressing
*Run now* on the tasks page. Either way one ``TaskRun`` row records the
whole of it, and that row is the page people are sent to.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from generic.tasks.models import TaskRun
from generic.tasks.registry import (
    ALL,
    AUDIENCES,
    CHANNELS,
    TaskDefinition,
    check_channels,
    get_task,
    registry,
)
from generic.tasks.runner import create_run, execute, launch

logger = logging.getLogger(__name__)


def _celery_task(name: str) -> Any:
    """A Celery task under this name, when Celery is installed.

    The task takes a run id, so a worker picks up the row this process
    wrote. Called with none - which is what a schedule does - it opens
    its own run and marks it as a scheduled one.
    """
    try:
        from celery import shared_task
    except ImportError:
        return None

    def entry(run_id: int | None = None, **arguments: Any) -> int:
        if run_id is None:
            run_id = create_run(
                name,
                trigger=TaskRun.Trigger.SCHEDULE,
                arguments=arguments,
            ).pk

        return execute(run_id).pk

    # Celery builds a function header from __name__ and execs it, so
    # what goes there has to be an identifier - a task name is only
    # required to be a string.
    identifier = "".join(
        letter if letter.isalnum() else "_" for letter in name
    )
    entry.__name__ = (
        identifier if identifier[:1].isalpha() else f"t{identifier}"
    )

    return shared_task(name=name)(entry)


def managed_task(
    function: Callable[..., Any] | None = None,
    *,
    name: str = "",
    label: str = "",
    description: str = "",
    icon: str = "bolt",
    announce: Iterable[str] = ("notification",),
    report: Iterable[str] = ("notification",),
    audience: Any = "trigger",
    permission: str = "",
    catalogue: bool = True,
    background: bool = False,
) -> Any:
    """Declare a task: what it is called, who hears, through what.

    ``announce`` and ``report`` take any of ``notification``, ``mail``
    and ``page`` - ``generic.tasks.ALL`` is every channel that delivers
    something, and ``("page",)`` is the run's own page and nothing else.
    A notification also reaches the pages its reader has open, as a
    toast. ``audience`` is ``trigger`` (whoever started it),
    ``staff``, ``superusers``, ``everyone``, or a callable taking the
    run and returning users.

    ``catalogue=False`` keeps it off the Tasks page: something a page of
    the project starts, as :func:`generic.tasks.operations.operation`
    declares.
    """

    def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
        task_name = name or f"{target.__module__}.{target.__name__}"
        definition = TaskDefinition(
            name=task_name,
            function=target,
            label=label,
            description=description,
            icon=icon,
            announce=check_channels(announce, "announce"),
            report=check_channels(report, "report"),
            audience=audience,
            permission=permission,
            celery_task=_celery_task(task_name),
            catalogue=catalogue,
            background=background,
        )
        registry.register(definition)

        target.definition = definition  # type: ignore[attr-defined]
        target.launch = (  # type: ignore[attr-defined]
            lambda **kwargs: launch(task_name, **kwargs)
        )

        return target

    if function is not None:
        return decorate(function)

    return decorate


# Declared below managed_task, which they are built on.
from generic.tasks.operations import (  # noqa: E402
    operation,
    operation_payload,
    operation_response,
    start_operation,
)

__all__ = [
    "ALL",
    "AUDIENCES",
    "CHANNELS",
    "TaskDefinition",
    "TaskRun",
    "create_run",
    "execute",
    "get_task",
    "launch",
    "managed_task",
    "operation",
    "operation_payload",
    "operation_response",
    "registry",
    "start_operation",
]

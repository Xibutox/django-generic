"""Running a task: the same four steps every time.

    1. announce   say it is starting, to whoever the task declared
    2. run        call the function, with the run to write into
    3. collect    turn what it returned into one result
    4. report     say how it went, through the declared channels

The steps are here rather than in each task so that every task gets
them: a task that only knows how to do its work still announces itself,
still records what it produced, and still reports.

Where the work happens is a separate question. With Celery installed
the run is handed to a worker; without it - or without a broker to
reach - it happens in the process that asked, which is what makes a
development machine behave like production minus the waiting.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from django.utils import timezone
from django.utils.translation import ngettext

from generic.history import acting_as
from generic.tasks import reporting
from generic.tasks.models import TaskRun
from generic.tasks.registry import TaskDefinition, get_task

logger = logging.getLogger(__name__)

#: An error is kept whole enough to act on, not whole enough to fill a
#: page with somebody else's stack.
MAX_ERROR = 4000


def create_run(
    name: str,
    *,
    user: Any = None,
    trigger: str = TaskRun.Trigger.MANUAL,
    arguments: dict[str, Any] | None = None,
) -> TaskRun:
    """Record that a run is wanted, before anything is started.

    The row exists first so that a task which dies on its first line
    still has a page saying so.
    """
    definition = get_task(name)

    return TaskRun.objects.create(
        task=definition.name,
        label=definition.title,
        status=TaskRun.Status.PENDING,
        trigger=trigger,
        triggered_by=user if getattr(user, "pk", None) else None,
        arguments=arguments or {},
    )


def can_queue(definition: TaskDefinition) -> bool:
    """Whether there is a worker path worth trying.

    An installed Celery is not a reachable one: with no broker
    configured, the default app points at a queue nobody is serving,
    and ``delay()`` would wait on a connection to nothing. Running the
    work here instead is what makes the same code behave on a laptop.
    """
    task = definition.celery_task

    if task is None:
        return False

    conf = getattr(getattr(task, "app", None), "conf", None)

    if conf is None:  # pragma: no cover - a Celery without an app
        return False

    # Eager still goes through Celery, which is the point of eager.
    return bool(conf.get("task_always_eager") or conf.get("broker_url"))


def launch(
    name: str,
    *,
    user: Any = None,
    trigger: str = TaskRun.Trigger.MANUAL,
    arguments: dict[str, Any] | None = None,
    inline: bool | None = None,
) -> TaskRun:
    """Start a task and return its run, queued or already finished."""
    definition = get_task(name)
    run = create_run(name, user=user, trigger=trigger, arguments=arguments)

    if inline is None:
        inline = not can_queue(definition)

    if inline:
        return execute(run.pk)

    try:
        async_result = definition.celery_task.delay(run.pk)
    except Exception:
        # No broker to reach. Doing the work here is slower than a
        # worker and better than silently not doing it at all.
        logger.warning(
            "Could not queue %s; running it in this process.",
            definition.name,
            exc_info=True,
        )

        return execute(run.pk)

    celery_id = getattr(async_result, "id", "") or ""

    if celery_id:
        run.celery_id = str(celery_id)[:64]
        run.save(update_fields=["celery_id"])

    run.refresh_from_db()

    return run


def execute(run_id: int) -> TaskRun:
    """The four steps, wherever the work turned out to happen."""
    run = TaskRun.objects.get(pk=run_id)
    definition = get_task(run.task)

    # Whatever the task writes is recorded as the task's doing, and as
    # the person's where one asked for it: a worker has no request to
    # read that from.
    with acting_as(run.triggered_by, source=run.label or run.task):
        _announce(run, definition)

        try:
            outcome = _run(run, definition)
        except Exception as error:  # noqa: BLE001 - a failure is a result
            return _failed(run, definition, error)

        return _finish(run, definition, outcome)


# -- the steps ----------------------------------------------------------


def _announce(run: TaskRun, definition: TaskDefinition) -> None:
    """Step 1."""
    run.status = TaskRun.Status.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    try:
        told = reporting.announce(run, definition)
    except Exception:
        # Telling people is not the work. A notification backend that
        # is down must not stop the task it was announcing.
        logger.exception("Could not announce task run %s", run.pk)
        return

    if told:
        run.note(
            ngettext(
                "Announced to %(count)s person.",
                "Announced to %(count)s people.",
                len(told),
            )
            % {"count": len(told)},
            kind="announce",
        )


def _run(run: TaskRun, definition: TaskDefinition) -> Any:
    """Step 2: the task's own work, with the run to write into."""
    return definition.function(run, **(run.arguments or {}))


def _collect(run: TaskRun, outcome: Any) -> None:
    """Step 3: one result, whatever shape the task returned.

    A task may write as it goes (``run.note``, ``run.add``), return a
    headline, return rows, or return nothing at all and leave what it
    already wrote to speak for itself.
    """
    if outcome is None:
        pass
    elif isinstance(outcome, dict):
        if "summary" in outcome:
            run.summary = str(outcome["summary"])[:300]

        rows = outcome.get("results")

        if isinstance(rows, list):
            run.results = [*(run.results or []), *rows]
        elif rows is not None:
            run.results = [*(run.results or []), rows]

        extra = {
            key: value
            for key, value in outcome.items()
            if key not in ("summary", "results")
        }

        if extra:
            run.results = [*(run.results or []), extra]
    elif isinstance(outcome, (list, tuple)):
        run.results = [*(run.results or []), *outcome]
    else:
        run.summary = str(outcome)[:300]

    if not run.summary and run.results:
        # Something has to fit in a notification; the first line will do
        # better than the task's name on its own.
        first = run.results[0]
        run.summary = str(
            first.get("label", first) if isinstance(first, dict) else first
        )[:300]


def _finish(run: TaskRun, definition: TaskDefinition, outcome: Any) -> TaskRun:
    _collect(run, outcome)

    run.status = TaskRun.Status.SUCCESS
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at", "summary", "results"])

    _report(run, definition)

    return run


def _failed(
    run: TaskRun,
    definition: TaskDefinition,
    error: Exception,
) -> TaskRun:
    logger.exception("Task %s failed", run.task)

    run.status = TaskRun.Status.FAILURE
    run.finished_at = timezone.now()
    run.error = "".join(
        traceback.format_exception_only(type(error), error)
    ).strip()[:MAX_ERROR]

    if not run.summary:
        run.summary = run.error.splitlines()[0][:300] if run.error else ""

    run.save(update_fields=["status", "finished_at", "error", "summary"])

    _report(run, definition)

    return run


def _report(run: TaskRun, definition: TaskDefinition) -> None:
    """Step 4."""
    try:
        reporting.report(run, definition)
    except Exception:
        logger.exception("Could not report task run %s", run.pk)

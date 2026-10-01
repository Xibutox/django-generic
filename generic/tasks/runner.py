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
import threading
import traceback
from typing import Any

from django.db import connections, transaction
from django.utils import timezone, translation
from django.utils.translation import ngettext

from generic.history import acting_as
from generic.reports import describe_counts
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
        # What the work writes is written in the language of whoever
        # asked for it, wherever the work turns out to happen.
        language=translation.get_language() or "",
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


def has_worker(definition: TaskDefinition) -> bool:
    """Whether a worker, not this process, would do the work.

    Eager goes through Celery but runs right here, in the request: for
    work that must not hold the request, that is no worker at all.
    """
    task = definition.celery_task
    conf = getattr(getattr(task, "app", None), "conf", None)

    if conf is None:
        return False

    return bool(conf.get("broker_url")) and not conf.get("task_always_eager")


def launch(
    name: str,
    *,
    user: Any = None,
    trigger: str = TaskRun.Trigger.MANUAL,
    arguments: dict[str, Any] | None = None,
    inline: bool | None = None,
    fallback: str = "inline",
    deliver: bool = True,
) -> TaskRun:
    """Start a task and return its run, queued or already finished.

    ``inline=None`` goes through Celery when it is set up (eagerly, if
    that is how) and does the work here otherwise. ``inline=True`` does
    it here and now. ``inline=False`` means "not in this request": a
    worker when one can be reached, else ``fallback`` decides -
    ``"inline"`` (here after all, the request waits) or ``"thread"`` (a
    thread of this process, the request does not).
    ``deliver=False`` skips steps 1 and 4 for a run done in the
    request: whoever asked is reading the answer already.
    """
    if fallback not in FALLBACKS:
        raise ValueError(
            f"fallback must be one of {', '.join(FALLBACKS)}, "
            f"not {fallback!r}."
        )

    definition = get_task(name)
    run = create_run(name, user=user, trigger=trigger, arguments=arguments)

    if inline is None:
        inline = not can_queue(definition)
    elif not inline and not has_worker(definition):
        if fallback == "thread":
            return start_thread(run)

        inline = True

    if inline:
        return execute(run.pk, deliver=deliver)

    try:
        async_result = definition.celery_task.delay(run.pk)
    except Exception:
        # No broker to reach. Doing the work here is slower than a
        # worker and better than silently not doing it at all.
        logger.warning(
            "Could not queue %s; running it %s.",
            definition.name,
            "in a thread" if fallback == "thread" else "in this process",
            exc_info=True,
        )

        if fallback == "thread":
            return start_thread(run)

        return execute(run.pk, deliver=deliver)

    celery_id = getattr(async_result, "id", "") or ""

    if celery_id:
        run.celery_id = str(celery_id)[:64]
        run.save(update_fields=["celery_id"])

    run.refresh_from_db()

    return run


#: Where a run goes when it should not hold the request and no worker
#: can be reached.
FALLBACKS = ("inline", "thread")


def start_thread(run: TaskRun) -> TaskRun:
    """Do the work in a thread of this process, once the row is saved.

    For a project with no Celery - a laptop, a small server, the
    minimal example - this is what lets a page answer at once and the
    work report when it is done. It is not a queue: the work is lost if
    the process stops, which is what a worker is for.
    """
    thread = threading.Thread(
        target=_in_thread,
        args=(run.pk,),
        name=f"generic-run-{run.pk}",
        daemon=True,
    )

    # After the commit, or the thread's own connection would not find
    # the row it was given.
    transaction.on_commit(thread.start)

    return run


def _in_thread(run_id: int) -> None:
    try:
        execute(run_id)
    except Exception:  # pragma: no cover - execute() records failures
        logger.exception("Task run %s failed in its thread", run_id)
    finally:
        # A thread's connections are its own; nobody else closes them.
        connections.close_all()


def execute(run_id: int, *, deliver: bool = True) -> TaskRun:
    """The four steps, wherever the work turned out to happen."""
    run = TaskRun.objects.get(pk=run_id)
    definition = get_task(run.task)

    # Whatever the task writes is recorded as the task's doing, and as
    # the person's where one asked for it: a worker has no request to
    # read that from. Its words are in that person's language, too.
    with (
        acting_as(run.triggered_by, source=run.label or run.task),
        translation.override(run.language or translation.get_language()),
    ):
        if deliver:
            _announce(run, definition)
        else:
            _start(run)

        try:
            outcome = _run(run, definition)
        except Exception as error:  # noqa: BLE001 - a failure is a result
            return _failed(run, definition, error, deliver=deliver)

        return _finish(run, definition, outcome, deliver=deliver)


# -- the steps ----------------------------------------------------------


def _start(run: TaskRun) -> None:
    run.status = TaskRun.Status.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])


def _announce(run: TaskRun, definition: TaskDefinition) -> None:
    """Step 1."""
    _start(run)

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

    if not run.summary and run.tree:
        # A report and no headline: what it holds, counted.
        run.summary = describe_counts(run.report.counts())[:300]


def _finish(
    run: TaskRun,
    definition: TaskDefinition,
    outcome: Any,
    *,
    deliver: bool = True,
) -> TaskRun:
    _collect(run, outcome)

    run.status = TaskRun.Status.SUCCESS
    run.finished_at = timezone.now()
    run.save(
        update_fields=["status", "finished_at", "summary", "results", "tree"]
    )

    _finished(run, definition, deliver)

    return run


def _failed(
    run: TaskRun,
    definition: TaskDefinition,
    error: Exception,
    *,
    deliver: bool = True,
) -> TaskRun:
    logger.exception("Task %s failed", run.task)

    run.status = TaskRun.Status.FAILURE
    run.finished_at = timezone.now()
    run.error = "".join(
        traceback.format_exception_only(type(error), error)
    ).strip()[:MAX_ERROR]

    if not run.summary:
        run.summary = run.error.splitlines()[0][:300] if run.error else ""

    # What the report held when it stopped is kept: the lines before
    # the failure are often what explains it.
    run.save(
        update_fields=["status", "finished_at", "error", "summary", "tree"]
    )

    _finished(run, definition, deliver)

    return run


def _finished(run: TaskRun, definition: TaskDefinition, deliver: bool) -> None:
    """Step 4, and the open page of whoever started the run.

    The event is for a page still waiting on this run - the operation
    toast - and is addressed to that one person; it is not how anybody
    learns of the run (the notification is). A run done in the request
    (``deliver=False``) has neither: the answer is the report.
    """
    if not deliver:
        return

    _report(run, definition)

    if run.triggered_by_id is None:
        return

    try:
        from generic.events.bus import publish_to_users

        publish_to_users(
            [run.triggered_by_id], "operation.finished", run.as_client()
        )
    except Exception:
        logger.exception("Could not publish the end of task run %s", run.pk)


def _report(run: TaskRun, definition: TaskDefinition) -> None:
    """Step 4."""
    try:
        reporting.report(run, definition)
    except Exception:
        logger.exception("Could not report task run %s", run.pk)

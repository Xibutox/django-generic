"""Operations: the work behind a button, and what it has to say.

A page that simplifies things - one button for "recompute this
customer's invoices" - usually hides work that is not simple: many
records, rules that can fail one by one, sometimes minutes of it. The
person who pressed the button needs three things from it, and an
operation is the declaration giving all three::

    from generic.tasks import operation

    @operation(label=_("Recompute invoices"), background=True)
    def recompute_invoices(run, ids):
        for customer in Customer.objects.filter(pk__in=ids):
            with run.report.section(str(customer), isolated=True) as part:
                count = customer.recompute()
                part.success(gettext("%(count)s invoices") % ...)

                if not customer.address:
                    part.warning(gettext("No address: nothing was sent."))

1. **When it is done** - at once when it ran in the request, or later,
   when it ran elsewhere: the page that started it is told the moment
   it ends (an ``operation.finished`` event to that person), and so is
   the person if they went away (a notification leading to the run).
2. **What went wrong**, as a tree: sections that fold, each showing the
   worst level inside it (:mod:`generic.reports`).
3. **A record** of it: one ``TaskRun`` with its report, its steps and
   its error, whose page the notification leads to.

An operation is a task (:func:`generic.tasks.managed_task`) that the
Tasks page does not list, that reports only to whoever started it, and
that is started from code with the arguments its page chose::

    @action(description=_("Recompute"), icon="calculate")
    def recompute(self, request, queryset):
        return recompute_invoices.start(
            request, ids=list(queryset.values_list("pk", flat=True))
        )

An action returning the run (or a :class:`generic.reports.Report`)
answers with it, and the table, the summary page - or any page calling
``Generic.operations.post(url, body)`` - draws it. A view of the
project's own answers with :func:`operation_response`.

**Where the work happens.** ``background=False`` (the default): in the
request, which answers with the whole report. ``background=True``: the
request answers at once; the work goes to a Celery worker when one can
be reached, and otherwise to a thread of the process
(``GENERIC["OPERATION_FALLBACK"] = "thread"``, the default) - or stays
in the request (``"inline"``) where threads are unwelcome.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext

from generic.conf import generic_settings
from generic.reports import Report
from generic.tasks.models import TaskRun
from generic.tasks.registry import TaskDefinition, get_task
from generic.tasks.runner import FALLBACKS, launch


def operation(
    function: Callable[..., Any] | None = None,
    *,
    name: str = "",
    label: str = "",
    description: str = "",
    icon: str = "bolt",
    background: bool = False,
    report: Iterable[str] = ("notification",),
    permission: str = "",
) -> Any:
    """Declare an operation: a task its page starts, reporting to the
    person who started it.

    ``background`` is the default for :func:`start_operation`.
    ``report`` is how that person hears the end of a background run when
    the page is gone (``notification``, ``mail``, ``page`` - the run's
    page and nothing else); a run done in the request is answered, not
    notified. ``permission``, when given, is checked on every start.

    The decorated function gets ``.start(request_or_user, **arguments)``.
    Arguments are stored on the run and must be JSON: primary keys, not
    records.
    """
    from generic.tasks import managed_task

    def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
        managed_task(
            target,
            name=name,
            label=label,
            description=description,
            icon=icon,
            # The page that started it says it has started.
            announce=("page",),
            report=report,
            audience="trigger",
            permission=permission,
            catalogue=False,
            background=background,
        )
        target.start = (  # type: ignore[attr-defined]
            lambda who, **arguments: start_operation(target, who, **arguments)
        )

        return target

    if function is not None:
        return decorate(function)

    return decorate


def definition_of(target: Any) -> TaskDefinition:
    """The task an operation, a task function or a name stands for."""
    definition = getattr(target, "definition", None)

    if isinstance(definition, TaskDefinition):
        return definition

    return get_task(str(target))


def start_operation(
    target: Any,
    who: Any,
    *,
    background: bool | None = None,
    **arguments: Any,
) -> TaskRun:
    """Start an operation for a request (or a user) and return its run.

    Finished when it ran in the request; pending or running when it went
    to the background - the answer says which, and the page follows.
    """
    definition = definition_of(target)
    user = getattr(who, "user", who)

    if definition.permission and not (
        user is not None and user.has_perm(definition.permission)
    ):
        raise PermissionDenied(
            gettext("You may not run %(task)s.") % {"task": definition.title}
        )

    try:
        json.dumps(arguments)
    except (TypeError, ValueError) as error:
        raise TypeError(
            f"{definition.name}: the arguments of an operation are stored "
            f"on its run and must be JSON - pass primary keys, not "
            f"records ({error})."
        ) from error

    if background is None:
        background = definition.background

    fallback = generic_settings.OPERATION_FALLBACK

    if fallback not in FALLBACKS:
        raise ValueError(
            f"GENERIC['OPERATION_FALLBACK'] must be one of "
            f"{', '.join(FALLBACKS)}, not {fallback!r}."
        )

    return launch(
        definition.name,
        user=user,
        trigger=TaskRun.Trigger.MANUAL,
        arguments=arguments,
        inline=not background,
        fallback=fallback,
        # Whoever is waiting on the request reads the report in the
        # answer: a notification of it as well would be said twice.
        deliver=False,
    )


def operation_payload(result: Any, message: Any = "") -> dict[str, Any]:
    """What a page is answered: a headline, a level and the operation.

    ``message`` and ``level`` are what any toast reads, so a page that
    knows nothing of operations still says something sensible; the
    ``operation`` key is what ``Generic.operations`` draws and follows.
    """
    if isinstance(result, Report):
        answer = result.as_client(message)

        return {
            "message": answer["message"],
            "level": answer["level"],
            "operation": {
                "id": None,
                "label": answer["message"],
                "finished": True,
                "status": TaskRun.Status.SUCCESS,
                "level": answer["level"],
                "summary": answer["message"],
                "report": answer["report"],
                "counts": answer["counts"],
                "error": "",
                "url": "",
            },
        }

    if not isinstance(result, TaskRun):
        raise TypeError(
            "operation_payload() takes a TaskRun or a Report, "
            f"not {type(result).__name__}."
        )

    run = result
    label = run.label or run.task

    if run.status == TaskRun.Status.FAILURE:
        headline = gettext("%(task)s failed: %(error)s") % {
            "task": label,
            "error": run.summary or run.error,
        }
    elif run.is_finished:
        headline = run.summary or gettext("%(task)s has finished.") % {
            "task": label
        }
    else:
        headline = gettext(
            "%(task)s is running in the background. You will be told "
            "when it is done."
        ) % {"task": label}

    return {
        "message": str(message or headline),
        "level": run.level,
        "operation": run.as_client(),
    }


def operation_response(result: Any, message: Any = "") -> Any:
    """A DRF response for a view of the project's own.

    ``202 Accepted`` while the work goes on elsewhere, ``200`` once it
    is done - and the same body either way.
    """
    from rest_framework import status
    from rest_framework.response import Response

    payload = operation_payload(result, message)
    finished = payload["operation"]["finished"]

    return Response(
        payload,
        status=status.HTTP_200_OK if finished else status.HTTP_202_ACCEPTED,
    )

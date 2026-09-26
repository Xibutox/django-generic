"""What the desk knows how to run on its own.

Declared with ``@managed_task``, so each one is announced when it
starts, keeps a run with everything it produced, and reports when it is
done - the framework does all four, the function below only does the
work.

The framework imports this module at start-up (``autodiscover_modules
("tasks")``), which is also where Celery finds it.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from example.models import Ticket
from generic.tasks import managed_task


@managed_task(
    name="example.overdue_digest",
    label=_("Overdue ticket digest"),
    description=_(
        "Counts the tickets that are past their date and says which "
        "team each one belongs to."
    ),
    icon="assignment_late",
    # Step 1: everyone who runs the desk hears that it started, in the
    # bell - and as a toast on every page they have open.
    announce=("notification",),
    # Step 4: the same people hear how it went. Add "mail" to have it
    # in an inbox as well.
    report=("notification",),
    audience="staff",
)
def overdue_digest(run: Any) -> dict[str, Any]:
    """Every ticket past its date, counted by team."""
    run.note(gettext("Looking for tickets past their date"))

    today = timezone.localdate()
    overdue = (
        Ticket.objects.filter(due_on__lt=today)
        .exclude(status=Ticket.Status.CLOSED)
        .select_related("team")
    )

    by_team: dict[str, int] = {}

    for ticket in overdue:
        name = ticket.team.name if ticket.team_id else gettext("No team")
        by_team[name] = by_team.get(name, 0) + 1

    run.note(
        gettext("%(count)s found, over %(teams)s team(s)")
        % {"count": len(overdue), "teams": len(by_team)}
    )

    # Step 3: what the run concatenates. Returning it is the short way;
    # a longer task can call run.add() as it goes instead.
    return {
        "summary": gettext("%(count)s overdue ticket(s)")
        % {"count": len(overdue)},
        "results": [
            {"label": team, "value": count}
            for team, count in sorted(
                by_team.items(), key=lambda pair: -pair[1]
            )
        ],
    }

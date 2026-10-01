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

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from example.models import Customer, Ticket
from generic.tasks import managed_task, operation


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


# -- Operations: the work behind a button -------------------------------
#
# Started by the desk's pages (the "Check" and "Review" actions in
# resources.py), with what the page chose; answered with a report tree
# the page draws - at once, or when the work ends elsewhere.


def _ticket_url(ticket: Ticket) -> str:
    return reverse("site:example_ticket_detail", args=[ticket.pk])


@operation(
    name="example.check_tickets",
    label=_("Check tickets"),
    description=_("Looks for what is missing on each selected ticket."),
    icon="fact_check",
)
def check_tickets(run: Any, ids: list[Any]) -> str:
    """In the request: the page waits and reads the report at once."""
    today = timezone.localdate()
    tickets = Ticket.objects.filter(pk__in=ids).select_related(
        "assignee", "customer", "team"
    )

    for ticket in tickets:
        # A section per ticket, linking to it: the browser folds the
        # ones that are fine and opens the others.
        with run.report.section(
            f"{ticket.reference} - {ticket.title}", url=_ticket_url(ticket)
        ) as section:
            problems = 0

            if ticket.status == Ticket.Status.CLOSED:
                section.info(gettext("Closed: nothing to check."))
                continue

            if ticket.assignee_id is None:
                section.warning(gettext("Nobody is working on it."))
                problems += 1

            if ticket.due_on and ticket.due_on < today:
                section.error(
                    gettext("Past its date, by %(days)s day(s).")
                    % {"days": (today - ticket.due_on).days},
                    gettext("Due on %(date)s.") % {"date": ticket.due_on},
                )
                problems += 1

            if ticket.customer_id is None:
                section.warning(gettext("No customer: it cannot be billed."))
                problems += 1

            if not problems:
                section.success(gettext("Nothing to correct."))

    return gettext("%(count)s ticket(s) checked.") % {"count": len(tickets)}


@operation(
    name="example.review_customers",
    label=_("Review customers"),
    description=_(
        "Goes through the selected customers' tickets and says which "
        "need attention."
    ),
    icon="manage_search",
    # The page is answered at once; the work goes to a worker - or a
    # thread, without one - and the page is told when it is done.
    background=True,
)
def review_customers(run: Any, ids: list[Any]) -> None:
    """In the background, one customer at a time."""
    today = timezone.localdate()
    customers = Customer.objects.filter(pk__in=ids).select_related(
        "account_manager"
    )

    run.note(gettext("Reviewing %(count)s customer(s)") % {"count": len(ids)})

    for customer in customers:
        # isolated: a customer whose review raises is rolled back and
        # written down as an error, and the next one goes on.
        with run.report.section(
            str(customer),
            url=reverse("site:example_customer_detail", args=[customer.pk]),
            isolated=True,
        ) as section:
            open_tickets = customer.tickets.exclude(
                status=Ticket.Status.CLOSED
            )
            late = open_tickets.filter(due_on__lt=today)

            section.info(
                gettext("%(count)s open ticket(s).")
                % {"count": open_tickets.count()}
            )

            for ticket in late.order_by("due_on")[:10]:
                section.error(
                    gettext("%(reference)s is past its date.")
                    % {"reference": ticket.reference},
                    ticket.title,
                    url=_ticket_url(ticket),
                )

            if customer.account_manager_id is None:
                section.warning(gettext("No account manager."))

            if not customer.is_active and open_tickets.exists():
                section.warning(gettext("Inactive, with tickets still open."))

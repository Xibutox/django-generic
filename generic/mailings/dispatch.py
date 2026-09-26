"""The dispatcher: every mailing whose time has come, sent once.

One task for all of them, run every few minutes by the scheduler - or
by cron, through ``manage.py send_scheduled_mailings`` - rather than a
schedule per mailing: a mailing is a row, and adding one needs nothing
of Celery beat.

Each mailing is claimed under a row lock and its next time moved on
*before* anything is sent, so two workers running the dispatcher at
once never send the same mailing twice. A mailing that fails is not
retried until its next time: a mail twice is worse than a mail late.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from generic.tasks import managed_task

#: The dispatcher's name, for a schedule to point at.
TASK = "generic.send_scheduled_mailings"


def claim(pk: Any, now: Any) -> Any:
    """The mailing, if it is still due and nobody else took it."""
    from generic.mailings.models import ScheduledMailing
    from generic.mailings.schedule import next_run

    with transaction.atomic():
        mailing = (
            ScheduledMailing.objects.select_for_update(skip_locked=True)
            .filter(pk=pk, is_active=True, next_run_at__lte=now)
            .first()
        )

        if mailing is None:
            return None

        mailing.next_run_at = next_run(mailing, after=now)
        mailing.save(update_fields=["next_run_at"])

    return mailing


def dispatch(run: Any = None) -> int:
    """Send what is due. Returns how many mailings went out."""
    from generic.mailings.models import ScheduledMailing
    from generic.mailings.sending import send

    now = timezone.now()
    due = list(
        ScheduledMailing.objects.filter(
            is_active=True, next_run_at__lte=now
        ).values_list("pk", flat=True)
    )
    count = 0

    for pk in due:
        mailing = claim(pk, now)

        if mailing is None:
            continue

        outcome = send(mailing)
        count += 1

        if run is not None:
            run.add(mailing.name, outcome.describe())

    return count


@managed_task(
    name=TASK,
    label=_("Send scheduled mailings"),
    description=_(
        "Sends every scheduled mailing whose time has come. Run it every "
        "few minutes."
    ),
    icon="forward_to_inbox",
    # Every few minutes: its runs are its record, nobody's news.
    announce=("page",),
    report=("page",),
)
def send_scheduled_mailings(run: Any) -> str:
    count = dispatch(run)

    return gettext("%(count)s mailings sent.") % {"count": count}

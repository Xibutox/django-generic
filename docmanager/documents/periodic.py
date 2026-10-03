"""Periodic reviews: a document read again when its date comes.

Every document has a *next review on* date - set by hand, or once
approved from its type's *reviewed every (months)*. Run once a day
(``tasks.py``: the *Periodic reviews* task, or ``manage.py
run_periodic_reviews`` from cron), :func:`run`:

* reminds the document's author and its team's leaders
  ``DOCUMENT_REVIEW_NOTICE_DAYS`` days before (30 by default), once
  per date;
* on the date, starts the type's *periodic review workflow* - when it
  has one and no review of the document is already open. Without one,
  they are reminded again on the day, and the document stays in the
  list's *Due for a review* view until somebody acts.

Nothing is blocked: the document stays readable and changeable all
along, like during any review.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext

from documents import workflows
from documents.models import Document, Review
from generic.delivery import NotificationLevel
from generic.teams import leaders_of


@dataclass
class Outcome:
    reminded: int = 0
    started: int = 0

    def describe(self) -> str:
        return gettext(
            "%(reminded)s reminded, %(started)s reviews started."
        ) % {"reminded": self.reminded, "started": self.started}


def notice_days() -> int:
    return int(getattr(settings, "DOCUMENT_REVIEW_NOTICE_DAYS", 30))


def due(today: datetime.date | None = None) -> Any:
    """Live documents whose review is within the notice."""
    today = today or timezone.localdate()

    return (
        Document.objects.filter(
            deleted_at__isnull=True,
            review_on__isnull=False,
            review_on__lte=today + datetime.timedelta(days=notice_days()),
        )
        .exclude(status=Document.Status.OBSOLETE)
        .select_related("folder__team", "document_type__review_workflow")
    )


def remind(document: Document, today: datetime.date) -> bool:
    """Tell the author and the team's leaders the review is coming -
    once per date, again on the day itself."""
    on_the_day = document.review_on <= today

    if document.review_notice_for == document.review_on and not on_the_day:
        return False

    people = {user.pk: user for user in leaders_of(document.team)}
    author = document.created_by

    if author is not None and author.is_active:
        people[author.pk] = author

    if not people:
        return False

    when = document.review_on

    def message():
        return (
            gettext("%(document)s is due for its review")
            % {"document": document},
            gettext("Its next review is on %(date)s.")
            % {"date": date_format(when, "SHORT_DATE_FORMAT")},
            (
                NotificationLevel.WARNING
                if on_the_day
                else NotificationLevel.INFO
            ),
        )

    from generic.sites import site

    workflows.tell(
        list(people.values()),
        message,
        url=site.get_resource(Document).get_detail_url(document.pk),
        about=document,
    )
    Document.objects.filter(pk=document.pk).update(
        review_notice_for=document.review_on
    )

    return True


@transaction.atomic
def start(document: Document) -> Review | None:
    """Start the type's periodic review workflow, unless one is open
    or there is none."""
    kind = document.document_type
    workflow = kind.review_workflow if kind is not None else None

    if workflow is None or not workflow.is_active:
        return None

    if document.reviews.filter(
        status__in=(Review.Status.PREPARING, Review.Status.IN_PROGRESS)
    ).exists():
        return None

    review = Review.objects.create(
        document=document,
        workflow=workflow,
        message=gettext("Periodic review, due on %(date)s.")
        % {"date": date_format(document.review_on, "SHORT_DATE_FORMAT")},
    )
    workflows.copy_steps(review, workflow.steps.all())

    try:
        return workflows.start(review, user=None)
    except workflows.WorkflowError:
        review.delete()

        return None


def run(today: datetime.date | None = None, task_run: Any = None) -> Outcome:
    today = today or timezone.localdate()
    outcome = Outcome()

    for document in due(today):
        started = None

        if document.review_on <= today:
            started = start(document)

        if started is not None:
            outcome.started += 1

            if task_run is not None:
                task_run.add(str(document), gettext("review started"))

            continue

        if remind(document, today):
            outcome.reminded += 1

            if task_run is not None:
                task_run.add(str(document), gettext("reminded"))

    return outcome


__all__ = ["Outcome", "run"]

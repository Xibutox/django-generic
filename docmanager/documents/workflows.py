"""Reviews: a document taken through a circuit, step by step.

A review is prepared with its steps - copied from a workflow, or drawn
on the spot - then started. Each step in turn asks its people for one
thing (review, approve, or read) and waits for one of them, or each of
them, to answer; a refusal ends the review. Whoever is asked gets a
notification and an e-mail with a link to their task; whoever started
the review and the team's leaders are told how it goes, step by step.

Nothing here blocks the work on the document: a step nobody can answer
is skipped, the document's file may still be replaced, a task may be
handed to someone else, and the review's starter, the team's leaders
and the managers may answer for someone, skip a step, add one or
cancel the review.

Every change goes through the functions below, under a lock on the
review: two answers at once never close a step twice.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable, Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext

from documents.models import (
    Document,
    Review,
    ReviewStep,
    ReviewTask,
    StepKind,
    StepRule,
    WorkflowStep,
)
from generic.delivery import NotificationLevel, deliver
from generic.teams import leaders_of, sees_every_team

#: Copied from a workflow's step into a review's.
STEP_FIELDS = (
    "position",
    "name",
    "kind",
    "rule",
    "days",
    "team_leaders",
    "team_members",
)

#: What a task asks, in the words of its step's kind.
ASKS = {
    StepKind.REVIEW: lambda: gettext("Review requested"),
    StepKind.APPROVAL: lambda: gettext("Approval requested"),
    StepKind.ACKNOWLEDGEMENT: lambda: gettext("Please read"),
}


class WorkflowError(Exception):
    """What cannot be done to a review, said to the person who tried."""


def channels() -> tuple[str, ...]:
    """Where the reviews' messages go: ``DOCUMENT_REVIEW_CHANNELS``,
    a notification and an e-mail by default."""
    return tuple(
        getattr(
            settings,
            "DOCUMENT_REVIEW_CHANNELS",
            ("notification", "mail"),
        )
    )


# -- who ----------------------------------------------------------------------


def participants(step: Any, document: Document) -> list[Any]:
    """The active people a step asks, each once, by name."""
    User = get_user_model()
    team = document.folder.team
    asked = Q(pk__in=step.users.values("pk")) | Q(
        groups__in=step.groups.values("pk")
    )

    if step.team_leaders:
        asked |= Q(pk__in=leaders_of(team).values("pk"))

    if step.team_members:
        asked |= Q(pk__in=team.members.values("pk"))

    found = User._default_manager.filter(asked, is_active=True).values("pk")

    return list(
        User._default_manager.filter(pk__in=found).order_by(
            User.USERNAME_FIELD
        )
    )


def may_steer(user: Any, review: Review) -> bool:
    """Who may skip a step, add one, answer for someone, or cancel: the
    review's starter, the team's leaders, whoever sees every team."""
    if not getattr(user, "is_authenticated", False):
        return False

    if sees_every_team(user) or review.started_by_id == user.pk:
        return True

    return review.document.folder.team.leaders.filter(pk=user.pk).exists()


def may_answer(user: Any, task: ReviewTask) -> bool:
    """A task still to do, by its assignee - or for them, by whoever
    steers the review."""
    if task.status != ReviewTask.Status.PENDING:
        return False

    if getattr(user, "pk", None) == task.assignee_id:
        return True

    return may_steer(user, task.review)


def followers(review: Review, *, besides: Any = None) -> list[Any]:
    """Told how the review goes: its starter and the team's leaders."""
    people = {user.pk: user for user in leaders_of(review.document.team)}
    starter = review.started_by

    if starter is not None and starter.is_active:
        people[starter.pk] = starter

    people.pop(getattr(besides, "pk", None), None)

    return list(people.values())


# -- telling ------------------------------------------------------------------


def tell(
    users: Iterable[Any],
    message: Callable[[], tuple[str, str, int]],
    *,
    url: str,
    about: Any,
) -> None:
    """Say it once the work is saved: a message about a step that was
    rolled back would be a lie."""
    users = list(users)

    if not users:
        return

    transaction.on_commit(
        lambda: deliver(
            users,
            channels=channels(),
            message=message,
            url=url,
            content_object=about,
            context=f"review {about.pk}",
        )
    )


def review_url(review: Review) -> str:
    from generic.sites import site

    return site.get_resource(Review).get_detail_url(review.pk)


def task_url(task: ReviewTask) -> str:
    from generic.sites import site

    # Its page: the document to open, and the Answer button.
    return site.get_resource(ReviewTask).get_detail_url(task.pk)


def name_of(user: Any) -> str:
    if user is None:
        return gettext("Someone")

    return user.get_full_name() or user.get_username()


def progress(step: ReviewStep) -> dict[str, Any]:
    return {
        "position": list(step.review.steps.values_list("pk", flat=True)).index(
            step.pk
        )
        + 1,
        "count": step.review.steps.count(),
        "step": step.name,
    }


def ask(tasks: list[ReviewTask]) -> None:
    """Tell each assignee what is asked of them."""
    for task in tasks:
        step, review = task.step, task.review
        where = progress(step)
        due = task.due_on
        version = review.document.version

        def message(
            step=step, review=review, where=where, due=due, version=version
        ):
            lines = [
                gettext(
                    "%(who)s asks you at step %(position)s of %(count)s, "
                    "%(step)s."
                )
                % {"who": name_of(review.started_by), **where}
            ]

            if review.message:
                lines.append(review.message)

            if version:
                lines.append(
                    gettext("Version %(number)s of the file.")
                    % {"number": version}
                )

            if due:
                lines.append(
                    gettext("Due on %(date)s.")
                    % {"date": date_format(due, "SHORT_DATE_FORMAT")}
                )

            return (
                f"{ASKS[step.kind]()}: {review.document}",
                "\n".join(lines),
                NotificationLevel.INFO,
            )

        tell([task.assignee], message, url=task_url(task), about=review)


def announce(
    review: Review,
    happened: Callable[[], str],
    *,
    actor: Any = None,
    level: int = NotificationLevel.INFO,
) -> None:
    """Tell the followers what happened, and where the review stands."""
    review.refresh_from_db()
    active = review.steps.filter(status=ReviewStep.Status.ACTIVE).first()
    waiting_on = (
        [
            name_of(task.assignee)
            for task in active.tasks.filter(
                status=ReviewTask.Status.PENDING
            ).select_related("assignee")
        ]
        if active
        else []
    )
    where = progress(active) if active else None
    status = review.status

    def message():
        lines = [happened()]

        if where:
            lines.append(
                gettext(
                    "Now at step %(position)s of %(count)s, %(step)s - "
                    "waiting on %(people)s."
                )
                % {**where, "people": ", ".join(waiting_on)}
            )
        elif status == Review.Status.APPROVED:
            lines.append(gettext("Every step is done."))

        return (
            gettext("Review of %(document)s") % {"document": review.document},
            "\n".join(lines),
            level,
        )

    tell(
        followers(review, besides=actor),
        message,
        url=review_url(review),
        about=review,
    )


# -- the circuit --------------------------------------------------------------


def copy_steps(review: Review, steps: Iterable[WorkflowStep]) -> None:
    for source in steps:
        step = ReviewStep.objects.create(
            review=review,
            **{name: getattr(source, name) for name in STEP_FIELDS},
        )
        step.users.set(source.users.all())
        step.groups.set(source.groups.all())


def lock(review: Review) -> Review:
    return (
        Review.objects.select_for_update(of=("self",))
        .select_related("document__folder__team", "started_by")
        .get(pk=review.pk)
    )


def has_approval(review: Review) -> bool:
    return review.steps.filter(kind=StepKind.APPROVAL).exists()


@transaction.atomic
def start(review: Review, *, user: Any) -> Review:
    """Start a prepared review: its first step asks its people."""
    review = lock(review)

    if review.status != Review.Status.PREPARING:
        raise WorkflowError(gettext("This review has already started."))

    if not review.steps.exists() and review.workflow_id:
        copy_steps(review, review.workflow.steps.all())

    if not review.steps.exists():
        raise WorkflowError(
            gettext("Add a step to the review, or choose a workflow.")
        )

    document = Document.objects.select_for_update().get(pk=review.document_id)
    review.status = Review.Status.IN_PROGRESS
    review.started_at = timezone.now()
    review.started_by = review.started_by or user
    review.version = document.version
    review.previous_status = document.status
    review.save()

    # Read only: the document's status says nothing new.
    if review.steps.exclude(kind=StepKind.ACKNOWLEDGEMENT).exists():
        set_status(document, Document.Status.REVIEW)

    advance(review)
    announce(
        review,
        lambda: gettext("%(who)s started the review.")
        % {"who": name_of(review.started_by)},
        actor=user,
    )

    return review


def advance(review: Review) -> ReviewStep | None:
    """Open the next waiting step - skipping those nobody can answer -
    or end the review when none is left."""
    while True:
        step = (
            review.steps.filter(status=ReviewStep.Status.WAITING)
            .order_by("position", "pk")
            .first()
        )

        if step is None:
            finish(review, Review.Status.APPROVED)

            return None

        people = participants(step, review.document)
        step.started_at = timezone.now()

        if not people:
            # Nobody to ask: the step must not stop the review.
            step.status = ReviewStep.Status.SKIPPED
            step.finished_at = step.started_at
            step.save()
            continue

        step.status = ReviewStep.Status.ACTIVE
        step.due_on = (
            timezone.localdate() + datetime.timedelta(days=step.days)
            if step.days
            else None
        )
        step.save()
        ask(
            [
                ReviewTask.objects.create(
                    step=step,
                    review=review,
                    document_id=review.document_id,
                    assignee=person,
                    due_on=step.due_on,
                )
                for person in people
            ]
        )

        return step


def close(step: ReviewStep, status: str) -> None:
    """End a step: whoever has not answered need not any more."""
    step.tasks.filter(status=ReviewTask.Status.PENDING).update(
        status=ReviewTask.Status.SKIPPED
    )
    step.status = status
    step.finished_at = timezone.now()
    step.save(update_fields=("status", "finished_at"))


def set_status(document: Document, status: str) -> None:
    if status and document.status != status:
        document.status = status
        document.save(update_fields=("status", "updated_at"))


def finish(review: Review, status: str) -> None:
    """End the review, and say so on the document."""
    for step in review.steps.filter(
        status__in=(ReviewStep.Status.WAITING, ReviewStep.Status.ACTIVE)
    ):
        close(step, ReviewStep.Status.SKIPPED)

    review.status = status
    review.finished_at = timezone.now()
    review.save(update_fields=("status", "finished_at"))
    document = Document.objects.select_for_update().get(pk=review.document_id)

    if status == Review.Status.APPROVED and has_approval(review):
        set_status(document, Document.Status.APPROVED)
    elif status == Review.Status.REJECTED:
        set_status(document, Document.Status.DRAFT)
    elif document.status == Document.Status.REVIEW:
        set_status(document, review.previous_status or Document.Status.DRAFT)


@transaction.atomic
def decide(
    task: ReviewTask, *, user: Any, approve: bool, comment: str = ""
) -> ReviewTask:
    """Answer a task: approved (reviewed, read) or rejected."""
    review = lock(task.review)
    task = ReviewTask.objects.select_related("step", "assignee").get(
        pk=task.pk
    )
    task.review = review

    if task.status != ReviewTask.Status.PENDING:
        raise WorkflowError(gettext("This task has already been answered."))

    if not may_answer(user, task):
        raise WorkflowError(gettext("This task is not yours to answer."))

    step = task.step

    if not approve and step.kind == StepKind.ACKNOWLEDGEMENT:
        raise WorkflowError(gettext("A document to read is only read."))

    task.status = (
        ReviewTask.Status.APPROVED if approve else ReviewTask.Status.REJECTED
    )
    task.comment = comment or task.comment
    task.decided_at = timezone.now()
    task.decided_by = user
    task.save()
    answer = {
        "who": name_of(user),
        "for": name_of(task.assignee),
        "step": step.name,
        "comment": task.comment,
    }
    on_behalf = user.pk != task.assignee_id

    if not approve:
        close(step, ReviewStep.Status.REJECTED)
        finish(review, Review.Status.REJECTED)

        def rejected():
            text = gettext("%(who)s rejected it at step %(step)s.") % answer

            if on_behalf:
                text += " " + gettext("(for %(for)s)") % answer

            if answer["comment"]:
                text += "\n" + answer["comment"]

            return text

        announce(review, rejected, actor=user, level=NotificationLevel.WARNING)

        return task

    pending = step.tasks.filter(status=ReviewTask.Status.PENDING)

    if step.rule == StepRule.ANY or not pending.exists():
        close(step, ReviewStep.Status.DONE)
        advance(review)

    def approved():
        text = {
            StepKind.REVIEW: gettext("%(who)s reviewed it at step %(step)s."),
            StepKind.APPROVAL: gettext(
                "%(who)s approved it at step %(step)s."
            ),
            StepKind.ACKNOWLEDGEMENT: gettext(
                "%(who)s read it at step %(step)s."
            ),
        }[step.kind] % answer

        if on_behalf:
            text += " " + gettext("(for %(for)s)") % answer

        if answer["comment"]:
            text += "\n" + answer["comment"]

        return text

    announce(
        review,
        approved,
        actor=user,
        level=(
            NotificationLevel.SUCCESS
            if review.status == Review.Status.APPROVED
            else NotificationLevel.INFO
        ),
    )

    return task


def steerable(review: Review, user: Any) -> Review:
    review = lock(review)

    if not may_steer(user, review):
        raise WorkflowError(
            gettext(
                "Only whoever started the review, the team's leaders and "
                "the managers may do this."
            )
        )

    if review.status != Review.Status.IN_PROGRESS:
        raise WorkflowError(gettext("This review is not in progress."))

    return review


@transaction.atomic
def skip_step(review: Review, *, user: Any) -> ReviewStep | None:
    """Close the current step unanswered, and go on."""
    review = steerable(review, user)
    step = review.steps.filter(status=ReviewStep.Status.ACTIVE).first()

    if step is not None:
        close(step, ReviewStep.Status.SKIPPED)

    advance(review)
    announce(
        review,
        lambda: gettext("%(who)s skipped the step %(step)s.")
        % {"who": name_of(user), "step": step.name if step else "-"},
        actor=user,
    )

    return step


@transaction.atomic
def cancel(review: Review, *, user: Any) -> Review:
    review = lock(review)

    if not may_steer(user, review):
        raise WorkflowError(
            gettext(
                "Only whoever started the review, the team's leaders and "
                "the managers may do this."
            )
        )

    if not review.is_open:
        raise WorkflowError(gettext("This review is already over."))

    started = review.status == Review.Status.IN_PROGRESS
    finish(review, Review.Status.CANCELLED)

    if started:
        announce(
            review,
            lambda: gettext("%(who)s cancelled the review.")
            % {"who": name_of(user)},
            actor=user,
            level=NotificationLevel.WARNING,
        )

    return review


@transaction.atomic
def delegate(task: ReviewTask, *, user: Any, to: Any) -> ReviewTask:
    """Hand a task to someone else: the same step, their task now."""
    review = lock(task.review)
    task = ReviewTask.objects.select_related("step").get(pk=task.pk)
    task.review = review

    if not may_answer(user, task):
        raise WorkflowError(gettext("This task is not yours to hand over."))

    if to is None or not to.is_active or to.pk == task.assignee_id:
        raise WorkflowError(gettext("Choose someone else to hand it to."))

    task.status = ReviewTask.Status.DELEGATED
    task.delegated_to = to
    task.decided_at = timezone.now()
    task.decided_by = user
    task.save()
    handed, created = ReviewTask.objects.get_or_create(
        step=task.step,
        review=review,
        assignee=to,
        status=ReviewTask.Status.PENDING,
        defaults={"due_on": task.due_on, "document_id": review.document_id},
    )

    if created:
        ask([handed])

    announce(
        review,
        lambda: gettext("%(who)s handed the step %(step)s to %(to)s.")
        % {"who": name_of(user), "step": task.step.name, "to": name_of(to)},
        actor=user,
    )

    return handed


@transaction.atomic
def refresh(step: ReviewStep) -> list[ReviewTask]:
    """A running step changed: ask whoever it names now and was not
    asked yet."""
    review = lock(step.review)
    step = ReviewStep.objects.get(pk=step.pk)

    if step.status != ReviewStep.Status.ACTIVE:
        return []

    asked = set(step.tasks.values_list("assignee_id", flat=True))
    tasks = [
        ReviewTask.objects.create(
            step=step,
            review=review,
            document_id=review.document_id,
            assignee=person,
            due_on=step.due_on,
        )
        for person in participants(step, review.document)
        if person.pk not in asked
    ]
    ask(tasks)

    return tasks


def remind(tasks: Iterable[ReviewTask]) -> int:
    """Ask again whoever has not answered yet."""
    pending = [
        task
        for task in tasks
        if task.status == ReviewTask.Status.PENDING
        and task.review.status == Review.Status.IN_PROGRESS
    ]

    with transaction.atomic():
        ask(pending)
        ReviewTask.objects.filter(pk__in=[task.pk for task in pending]).update(
            reminded_at=timezone.now()
        )

    return len(pending)


__all__ = [
    "WorkflowError",
    "advance",
    "cancel",
    "copy_steps",
    "decide",
    "delegate",
    "may_answer",
    "may_steer",
    "participants",
    "refresh",
    "remind",
    "skip_step",
    "start",
]

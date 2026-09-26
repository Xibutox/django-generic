"""A channel of the example's own: each team's queue, live.

The tables need nothing of this: each follows a channel per model by
itself. A channel is for a page of the project's own that must stay
true while it is open - here, the count of a team's open tickets on the
*Live updates* page. Three steps, and this module holds the first two:

1. declare the channel, and who may listen (``register_topic``);
2. publish on it when what it is about changes (``publish_to_topic``);
3. a page subscribes and redraws (``Generic.events.subscribe``).

Nobody is notified: nothing is stored, nothing is addressed to anyone.
A page that is not open hears nothing, and loses nothing - it reads the
count afresh when it opens.

Declared from ``ExampleConfig.ready()``, so the channel exists before
the first WebSocket connects.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from example.models import Ticket
from generic.events import (
    allow_authenticated,
    publish_to_topic,
    register_topic,
)

#: The channel: one per team.
TEAM_QUEUE = "team.{team_id}"

#: What the page counts.
IN_THE_QUEUE = (Ticket.Status.OPEN, Ticket.Status.PENDING)


def member_of_team(
    user: Any,
    topic: str,
    parameters: dict[str, str],
) -> bool:
    """Only agents on the team may follow its queue.

    Runs where database access is allowed, so it can ask the ORM.
    """
    if not allow_authenticated(user, topic, parameters):
        return False

    if user.is_superuser:
        return True

    from example.models import Agent

    return Agent.objects.filter(
        team_id=parameters["team_id"],
        email__iexact=user.email,
    ).exists()


register_topic(
    TEAM_QUEUE,
    permission=member_of_team,
    description="One team's queue: how many of its tickets are open.",
)


def queue_size(team_id: Any) -> int:
    return Ticket.objects.filter(
        team_id=team_id, status__in=IN_THE_QUEUE
    ).count()


def tell_teams(team_ids: Iterable[Any]) -> None:
    """Publish each team's count on its channel, once the save commits."""
    for team_id in {team_id for team_id in team_ids if team_id}:
        publish_to_topic(
            TEAM_QUEUE,
            "team.queue",
            {"team": team_id, "open": queue_size(team_id)},
            parameters={"team_id": str(team_id)},
        )


@receiver(pre_save, sender=Ticket, dispatch_uid="example.queue.before")
def remember_team(sender: Any, instance: Ticket, **kwargs: Any) -> None:
    """The team a ticket leaves, if it moves: its queue shrinks too."""
    instance._team_before = (
        Ticket.objects.filter(pk=instance.pk)
        .values_list("team_id", flat=True)
        .first()
        if instance.pk
        else None
    )


@receiver(post_save, sender=Ticket, dispatch_uid="example.queue.saved")
def ticket_saved(sender: Any, instance: Ticket, **kwargs: Any) -> None:
    tell_teams([instance.team_id, getattr(instance, "_team_before", None)])


@receiver(post_delete, sender=Ticket, dispatch_uid="example.queue.deleted")
def ticket_deleted(sender: Any, instance: Ticket, **kwargs: Any) -> None:
    tell_teams([instance.team_id])

"""Sending a message: who it reaches, and through what.

    from generic.events.messages import recipients, send

    message = Message.objects.create(title="...", everyone=True)
    send(message)

The screen does both when a message is saved; project code that writes
a message itself calls :func:`send` the same way. Whoever it reaches
hears through :mod:`generic.delivery`, like a watch or a task: a
notification, an e-mail or both, in their own language.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from django.contrib.auth import get_user_model
from django.db.models import Q

from generic import delivery
from generic.events.models import Message

logger = logging.getLogger(__name__)


def recipients(
    *,
    everyone: bool = False,
    users: Iterable[Any] = (),
    groups: Iterable[Any] = (),
) -> Any:
    """The active accounts a message with these addressees reaches.

    A queryset, with each account's preferences joined in: the delivery
    reads them for every recipient, and this way the lot costs one
    query rather than one per person.
    """
    model = get_user_model()
    people = model._default_manager.select_related("generic_preferences")
    fields = {field.name for field in model._meta.get_fields()}

    if "is_active" in fields:
        people = people.filter(is_active=True)

    if everyone:
        return people.order_by("pk")

    chosen = Q(pk__in=[getattr(user, "pk", user) for user in users])
    group_ids = [getattr(group, "pk", group) for group in groups]

    # A custom user model may belong to no group at all.
    if group_ids and "groups" in fields:
        chosen |= Q(groups__in=group_ids)

    return people.filter(chosen).distinct().order_by("pk")


def recipients_of(message: Message) -> Any:
    """The accounts a saved message reaches, as it stands now."""
    return recipients(
        everyone=message.everyone,
        users=message.users.all(),
        groups=message.groups.all(),
    )


def channels_for(message: Message, people: list[Any]) -> dict:
    """The recipients grouped by the channels each one hears through."""
    if message.delivery == Message.Delivery.PREFERENCE:
        return delivery.by_preference(people)

    return {delivery.BY_PREFERENCE[message.delivery]: people}


def send(message: Message) -> int:
    """Deliver a saved message to everyone it names.

    Records how many people it reached on the message, and returns it.
    """
    people = list(recipients_of(message))

    for channels, group in channels_for(message, people).items():
        delivery.deliver(
            group,
            channels=channels,
            # The sender's own words, the same in every language.
            message=lambda: (message.title, message.body, message.level),
            url=message.url,
            content_object=message,
            context=f"message {message.pk}",
        )

    message.recipient_count = len(people)
    message.save(update_fields=["recipient_count"])

    return len(people)


__all__ = ["channels_for", "recipients", "recipients_of", "send"]

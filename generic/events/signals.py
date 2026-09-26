"""Signal receivers turning model changes into events."""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from generic.events.bus import Event, publish
from generic.events.models import Notification


@receiver(post_save, sender=Notification, dispatch_uid="generic.notify")
def publish_notification(
    sender: type[Notification],
    instance: Notification,
    created: bool,
    **kwargs: Any,
) -> None:
    """Push a notification to its recipient as soon as it is stored.

    Updates are published too, so a notification marked read in one tab
    stops showing as unread in the others.
    """
    from generic.events.serializers import serialize_notification

    publish(
        Event(
            type=(
                "notification.created" if created else "notification.updated"
            ),
            payload=serialize_notification(instance),
        ),
        users=[instance.user_id],
    )


@receiver(
    post_delete,
    sender=Notification,
    dispatch_uid="generic.notify.deleted",
)
def publish_notification_deleted(
    sender: type[Notification],
    instance: Notification,
    **kwargs: Any,
) -> None:
    publish(
        Event(
            type="notification.deleted",
            payload={"id": instance.pk},
        ),
        users=[instance.user_id],
    )

"""Publishing side of the event system.

``publish`` is the only function project code needs. Everything below it
- resolving groups, reaching the channel layer, deferring to commit - is
an implementation detail that can change without touching callers.

Channels is an optional dependency. Without it, publishing is a no-op
that logs once, so a project can adopt the rest of the framework without
running an ASGI server.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Iterable, Sequence

from asgiref.sync import async_to_sync
from django.db import transaction
from django.utils import timezone

from generic.conf import generic_settings
from generic.events.registry import registry

logger = logging.getLogger(__name__)

#: Message type the consumer dispatches on. Channels turns this into the
#: ``generic_event`` handler method.
MESSAGE_TYPE = "generic.event"

_channel_layer_warning_emitted = False


def user_group(user_id: Any) -> str:
    return f"generic.user.{user_id}"


def broadcast_group() -> str:
    return generic_settings.EVENTS_BROADCAST_GROUP


@dataclasses.dataclass(frozen=True)
class Event:
    """One thing that happened, on its way to connected clients."""

    #: Dotted name the client switches on, such as
    #: ``notification.created`` or ``table.changed``.
    type: str
    payload: dict[str, Any] = dataclasses.field(default_factory=dict)
    #: ISO timestamp, filled in at publication.
    timestamp: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp or timezone.now().isoformat(),
        }


def get_channel_layer() -> Any:
    """The configured channel layer, or ``None``.

    ``None`` means events are dropped: either Channels is not installed
    or no ``CHANNEL_LAYERS`` is configured.
    """
    global _channel_layer_warning_emitted

    try:
        from channels.layers import get_channel_layer as _get_layer
    except ImportError:
        if not _channel_layer_warning_emitted:
            logger.warning(
                "Channels is not installed; events are not delivered. "
                "Install the 'events' extra to enable them."
            )
            _channel_layer_warning_emitted = True

        return None

    layer = _get_layer()

    if layer is None and not _channel_layer_warning_emitted:
        logger.warning(
            "No CHANNEL_LAYERS configured; events are not delivered."
        )
        _channel_layer_warning_emitted = True

    return layer


async def asend_to_groups(
    groups: Sequence[str],
    event: Event,
) -> None:
    """Hand one event to the channel layer, once per group.

    The async primitive: use it from a consumer or an async view, where
    wrapping the sync variant would deadlock on the running loop.
    """
    layer = get_channel_layer()

    if layer is None or not groups:
        return

    message = {"type": MESSAGE_TYPE, "event": event.as_dict()}

    for group in dict.fromkeys(groups):
        try:
            await layer.group_send(group, message)
        except Exception:
            # A delivery failure must never take down the request that
            # produced the event.
            logger.exception(
                "Failed to publish event '%s' to group '%s'.",
                event.type,
                group,
            )


def send_to_groups(groups: Sequence[str], event: Event) -> None:
    """Synchronous wrapper over :func:`asend_to_groups`."""
    async_to_sync(asend_to_groups)(groups, event)


def publish(
    event: Event,
    *,
    groups: Sequence[str] = (),
    users: Iterable[Any] = (),
    topics: Iterable[tuple[str, dict[str, str]]] = (),
    broadcast: bool = False,
    on_commit: bool | None = None,
) -> None:
    """Publish one event to any combination of destinations.

    ``users``
        User instances or primary keys; each gets their private stream.
    ``topics``
        ``(name, parameters)`` pairs, resolved through the registry.
    ``broadcast``
        Everyone currently connected.

    Delivery is deferred until the surrounding transaction commits, so
    clients are never told about a row a rollback then removes. Pass
    ``on_commit=False`` for an event that is not about stored data.
    """
    resolved = list(groups)

    for user in users:
        user_id = getattr(user, "pk", user)
        resolved.append(user_group(user_id))

    for name, parameters in topics:
        topic = registry.get(name)

        if topic is None:
            raise ValueError(
                f"Topic '{name}' is not registered. Declare it with "
                f"generic.events.register_topic()."
            )

        resolved.append(topic.group_name(parameters))

    if broadcast:
        resolved.append(broadcast_group())

    if not resolved:
        return

    if on_commit is None:
        on_commit = generic_settings.EVENTS_DISPATCH_ON_COMMIT

    if on_commit:
        transaction.on_commit(lambda: send_to_groups(resolved, event))
    else:
        send_to_groups(resolved, event)


def publish_to_users(
    users: Iterable[Any],
    event_type: str,
    payload: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    publish(
        Event(type=event_type, payload=payload or {}),
        users=users,
        **kwargs,
    )


def publish_to_topic(
    name: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    parameters: dict[str, str] | None = None,
    **kwargs: Any,
) -> None:
    publish(
        Event(type=event_type, payload=payload or {}),
        topics=[(name, parameters or {})],
        **kwargs,
    )


def broadcast_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    publish(
        Event(type=event_type, payload=payload or {}),
        broadcast=True,
        **kwargs,
    )


def publish_notifications(notifications: Iterable[Any]) -> None:
    """Publish notifications created outside the ORM signal path.

    ``bulk_create`` does not fire ``post_save``, so the manager's
    ``notify`` helper returns its rows for this function to announce.
    """
    from generic.events.serializers import serialize_notification

    for notification in notifications:
        publish(
            Event(
                type="notification.created",
                payload=serialize_notification(notification),
            ),
            users=[notification.user_id],
        )

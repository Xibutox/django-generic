"""WebSocket consumer delivering events to the browser.

Protocol, client to server::

    {"action": "subscribe",   "topic": "project.12"}
    {"action": "unsubscribe", "topic": "project.12"}
    {"action": "ping"}

Server to client::

    {"type": "connection.ready", "payload": {"unread": 3}}
    {"type": "subscription.accepted", "payload": {"topic": "..."}}
    {"type": "subscription.denied",   "payload": {"topic": "..."}}
    {"type": "notification.created",  "payload": {...}}

Every subscription is checked against the topic registry, so a client
cannot join a stream simply by naming its group.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.serializers.json import DjangoJSONEncoder

from generic.events.bus import broadcast_group, user_group
from generic.events.registry import registry

#: Refuse to hold an unbounded number of groups for one socket.
MAX_SUBSCRIPTIONS = 50

#: WebSocket close codes.
CLOSE_UNAUTHORIZED = 4001

logger = logging.getLogger(__name__)


class EventConsumer(AsyncJsonWebsocketConsumer):
    """One socket per connected browser tab."""

    async def connect(self) -> None:
        user = self.scope.get("user")

        if user is None or not user.is_authenticated:
            # Closing with a code rather than accepting-then-closing
            # lets the client tell "signed out" from "server restarted"
            # and avoid a reconnect storm.
            await self.close(code=CLOSE_UNAUTHORIZED)
            return

        self.user = user
        self.subscriptions: set[str] = set()

        self.private_group = user_group(user.pk)
        self.broadcast_group = broadcast_group()

        await self.channel_layer.group_add(
            self.private_group,
            self.channel_name,
        )
        await self.channel_layer.group_add(
            self.broadcast_group,
            self.channel_name,
        )

        await self.accept()

        await self.send_json(
            {
                "type": "connection.ready",
                "payload": {"unread": await self.get_unread_count()},
            }
        )

    async def disconnect(self, code: int) -> None:
        groups = getattr(self, "subscriptions", set()) | {
            getattr(self, "private_group", None),
            getattr(self, "broadcast_group", None),
        }

        for group in groups:
            if group:
                await self.channel_layer.group_discard(
                    group,
                    self.channel_name,
                )

    # -- inbound ------------------------------------------------------

    async def receive_json(
        self,
        content: Any,
        **kwargs: Any,
    ) -> None:
        if not isinstance(content, dict):
            await self.send_error("A JSON object is expected.")
            return

        action = content.get("action")

        if action == "ping":
            await self.send_json({"type": "pong", "payload": {}})
            return

        if action in {"subscribe", "unsubscribe"}:
            await self.handle_subscription(action, content)
            return

        await self.send_error(f"Unknown action: {action!r}.")

    async def handle_subscription(
        self,
        action: str,
        content: dict[str, Any],
    ) -> None:
        name = content.get("topic")

        if not isinstance(name, str) or not name:
            await self.send_error("A topic name is required.")
            return

        resolved = registry.resolve(name)

        if resolved is None:
            await self.deny_subscription(name, "Unknown topic.")
            return

        topic, parameters = resolved

        if action == "unsubscribe":
            group = topic.group_name(parameters)
            self.subscriptions.discard(group)
            await self.channel_layer.group_discard(
                group,
                self.channel_name,
            )
            await self.send_json(
                {
                    "type": "subscription.removed",
                    "payload": {"topic": name},
                }
            )
            return

        if len(self.subscriptions) >= MAX_SUBSCRIPTIONS:
            await self.deny_subscription(name, "Too many subscriptions.")
            return

        allowed = await database_sync_to_async(topic.allows)(
            self.user,
            parameters,
        )

        if not allowed:
            await self.deny_subscription(name, "Not allowed.")
            return

        group = topic.group_name(parameters)
        self.subscriptions.add(group)
        await self.channel_layer.group_add(group, self.channel_name)

        await self.send_json(
            {
                "type": "subscription.accepted",
                "payload": {"topic": name},
            }
        )

    # -- outbound -----------------------------------------------------

    @classmethod
    async def encode_json(cls, content: Any) -> str:
        """Serialise with Django's own encoder.

        Event payloads routinely carry things the standard library
        cannot encode: a lazy translation, a date, a Decimal, a UUID.
        ``DjangoJSONEncoder`` handles all four, and without it a single
        lazy string raises inside the consumer and takes the socket
        down with it.
        """
        return json.dumps(content, cls=DjangoJSONEncoder)

    async def generic_event(self, message: dict[str, Any]) -> None:
        """Handler for messages sent with type ``generic.event``."""
        try:
            await self.send_json(message["event"])
        except TypeError:
            # One unserialisable payload must not disconnect a client
            # from every other event it is waiting for.
            logger.exception(
                "Dropping an event that could not be serialised: %r",
                message.get("event", {}).get("type"),
            )

    async def send_error(self, message: str) -> None:
        await self.send_json({"type": "error", "payload": {"detail": message}})

    async def deny_subscription(
        self,
        topic: str,
        reason: str,
    ) -> None:
        await self.send_json(
            {
                "type": "subscription.denied",
                "payload": {"topic": topic, "detail": reason},
            }
        )

    # -- database -----------------------------------------------------

    @database_sync_to_async
    def get_unread_count(self) -> int:
        from generic.events.models import Notification

        return Notification.objects.for_user(self.user).unread().count()

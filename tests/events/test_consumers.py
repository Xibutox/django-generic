"""The WebSocket consumer, driven end to end through Channels."""

from __future__ import annotations

import asyncio

import pytest
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from generic.events.bus import (
    Event,
    asend_to_groups,
    broadcast_group,
    user_group,
)
from generic.events.consumers import CLOSE_UNAUTHORIZED, EventConsumer
from generic.events.registry import allow_staff

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.asyncio,
]


def build_communicator(user) -> WebsocketCommunicator:
    communicator = WebsocketCommunicator(
        EventConsumer.as_asgi(),
        "/ws/events/",
    )
    communicator.scope["user"] = user

    return communicator


async def connect(user) -> WebsocketCommunicator:
    communicator = build_communicator(user)
    connected, _ = await communicator.connect()

    assert connected

    # Drain the handshake frame.
    await communicator.receive_json_from()

    return communicator


class TestConnection:
    async def test_an_anonymous_visitor_is_refused(self):
        communicator = build_communicator(AnonymousUser())
        connected, code = await communicator.connect()

        assert connected is False
        assert code == CLOSE_UNAUTHORIZED

    async def test_a_signed_in_user_is_accepted(self, user):
        communicator = build_communicator(user)
        connected, _ = await communicator.connect()

        assert connected is True

        await communicator.disconnect()

    async def test_the_handshake_carries_the_unread_count(
        self,
        user,
        notification,
    ):
        communicator = build_communicator(user)
        await communicator.connect()

        message = await communicator.receive_json_from()

        assert message["type"] == "connection.ready"
        assert message["payload"]["unread"] == 1

        await communicator.disconnect()


class TestDelivery:
    async def test_a_user_receives_their_own_events(self, user):
        communicator = await connect(user)

        await asend_to_groups(
            [user_group(user.pk)],
            Event(type="notification.created", payload={"id": 1}),
        )

        message = await communicator.receive_json_from()

        assert message["type"] == "notification.created"
        assert message["payload"] == {"id": 1}

        await communicator.disconnect()

    async def test_a_user_does_not_receive_another_users_events(
        self,
        user,
    ):
        communicator = await connect(user)

        await asend_to_groups(
            [user_group(user.pk + 999)],
            Event(type="secret"),
        )

        assert await communicator.receive_nothing() is True

        await communicator.disconnect()

    async def test_broadcasts_reach_everyone(self, user):
        communicator = await connect(user)

        await asend_to_groups(
            [broadcast_group()],
            Event(type="maintenance.scheduled"),
        )

        message = await communicator.receive_json_from()

        assert message["type"] == "maintenance.scheduled"

        await communicator.disconnect()

    async def test_ping_is_answered(self, user):
        communicator = await connect(user)

        await communicator.send_json_to({"action": "ping"})
        message = await communicator.receive_json_from()

        assert message["type"] == "pong"

        await communicator.disconnect()

    @pytest.mark.skipif(
        "RedisChannelLayer"
        not in settings.CHANNEL_LAYERS["default"]["BACKEND"],
        reason="only the Redis layer waits on a connection",
    )
    async def test_a_quiet_socket_still_hears(self, user):
        """channels-redis waits on Redis for the next event, 5 seconds
        at a time. A connection that gives up on a reply first - as
        redis-py 8 does by default - ends the consumer, and with it
        every socket left quiet that long."""
        communicator = await connect(user)

        await asyncio.sleep(get_channel_layer().brpop_timeout + 1)
        await asend_to_groups(
            [user_group(user.pk)],
            Event(type="notification.created", payload={"id": 2}),
        )

        message = await communicator.receive_json_from(timeout=5)

        assert message["payload"] == {"id": 2}

        await communicator.disconnect()


class TestSubscriptions:
    async def test_a_declared_topic_can_be_joined(
        self,
        user,
        clean_topic_registry,
    ):
        clean_topic_registry.register("project.{project_id}")
        communicator = await connect(user)

        await communicator.send_json_to(
            {"action": "subscribe", "topic": "project.7"}
        )
        message = await communicator.receive_json_from()

        assert message["type"] == "subscription.accepted"

        await asend_to_groups(
            ["generic.topic.project.7"],
            Event(type="project.changed"),
        )

        message = await communicator.receive_json_from()

        assert message["type"] == "project.changed"

        await communicator.disconnect()

    async def test_an_undeclared_topic_is_denied(
        self,
        user,
        clean_topic_registry,
    ):
        communicator = await connect(user)

        await communicator.send_json_to(
            {"action": "subscribe", "topic": "generic.user.1"}
        )
        message = await communicator.receive_json_from()

        # Naming a group directly must not be a way into it.
        assert message["type"] == "subscription.denied"

        await communicator.disconnect()

    async def test_a_topic_the_user_may_not_read_is_denied(
        self,
        user,
        clean_topic_registry,
    ):
        clean_topic_registry.register(
            "audit.log",
            permission=allow_staff,
        )
        communicator = await connect(user)

        await communicator.send_json_to(
            {"action": "subscribe", "topic": "audit.log"}
        )
        message = await communicator.receive_json_from()

        assert message["type"] == "subscription.denied"
        assert message["payload"]["detail"] == "Not allowed."

        await communicator.disconnect()

    async def test_a_staff_user_may_join_a_staff_topic(
        self,
        staff_user,
        clean_topic_registry,
    ):
        clean_topic_registry.register(
            "audit.log",
            permission=allow_staff,
        )
        communicator = await connect(staff_user)

        await communicator.send_json_to(
            {"action": "subscribe", "topic": "audit.log"}
        )
        message = await communicator.receive_json_from()

        assert message["type"] == "subscription.accepted"

        await communicator.disconnect()

    async def test_unsubscribing_stops_delivery(
        self,
        user,
        clean_topic_registry,
    ):
        clean_topic_registry.register("project.{project_id}")
        communicator = await connect(user)

        await communicator.send_json_to(
            {"action": "subscribe", "topic": "project.7"}
        )
        await communicator.receive_json_from()

        await communicator.send_json_to(
            {"action": "unsubscribe", "topic": "project.7"}
        )
        message = await communicator.receive_json_from()

        assert message["type"] == "subscription.removed"

        await asend_to_groups(
            ["generic.topic.project.7"],
            Event(type="project.changed"),
        )

        assert await communicator.receive_nothing() is True

        await communicator.disconnect()


class TestPayloadEncoding:
    """Payloads carry more than strings and numbers.

    A lazy translation used to raise inside the consumer and take the
    whole socket down with it, disconnecting the client from every
    other event it was waiting for.
    """

    async def test_a_lazy_translation_is_delivered(self, user):
        from django.utils.translation import gettext_lazy

        communicator = await connect(user)

        await asend_to_groups(
            [user_group(user.pk)],
            Event(
                type="notification.created",
                payload={"title": gettext_lazy("Needs attention")},
            ),
        )

        message = await communicator.receive_json_from()

        assert message["payload"]["title"] == "Needs attention"

        await communicator.disconnect()

    async def test_dates_and_decimals_are_delivered(self, user):
        import datetime
        from decimal import Decimal
        from uuid import UUID

        communicator = await connect(user)

        await asend_to_groups(
            [user_group(user.pk)],
            Event(
                type="row.changed",
                payload={
                    "on": datetime.date(2026, 3, 15),
                    "amount": Decimal("12.50"),
                    "id": UUID("12345678-1234-5678-1234-567812345678"),
                },
            ),
        )

        payload = (await communicator.receive_json_from())["payload"]

        assert payload["on"] == "2026-03-15"
        assert payload["amount"] == "12.50"
        assert payload["id"].startswith("12345678")

        await communicator.disconnect()

    async def test_an_unserialisable_payload_keeps_the_socket_open(
        self,
        user,
    ):
        communicator = await connect(user)

        # Nothing can encode an arbitrary object; the event is dropped.
        await asend_to_groups(
            [user_group(user.pk)],
            Event(type="broken", payload={"value": object()}),
        )

        assert await communicator.receive_nothing() is True

        # The connection survives, and the next event still arrives.
        await asend_to_groups(
            [user_group(user.pk)],
            Event(type="fine", payload={"value": 1}),
        )

        assert (await communicator.receive_json_from())["type"] == "fine"

        await communicator.disconnect()


class TestProtocolErrors:
    async def test_an_unknown_action_is_reported(self, user):
        communicator = await connect(user)

        await communicator.send_json_to({"action": "drop-tables"})
        message = await communicator.receive_json_from()

        assert message["type"] == "error"

        await communicator.disconnect()

    async def test_a_subscription_without_a_topic_is_reported(
        self,
        user,
    ):
        communicator = await connect(user)

        await communicator.send_json_to({"action": "subscribe"})
        message = await communicator.receive_json_from()

        assert message["type"] == "error"

        await communicator.disconnect()

    async def test_a_non_object_frame_is_reported(self, user):
        communicator = await connect(user)

        await communicator.send_json_to(["subscribe"])
        message = await communicator.receive_json_from()

        assert message["type"] == "error"

        await communicator.disconnect()

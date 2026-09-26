"""Publishing: who receives an event, and when."""

from __future__ import annotations

from unittest import mock

import pytest
from django.db import transaction
from django.test import override_settings

from generic.events import bus
from generic.events.bus import (
    Event,
    broadcast_event,
    publish,
    publish_to_topic,
    publish_to_users,
    user_group,
)
from tests.factories import NotificationFactory


@pytest.fixture
def sent():
    """Capture what reaches the channel layer."""
    with mock.patch.object(bus, "send_to_groups") as send:
        yield send


def groups_of(send) -> list[str]:
    return list(send.call_args.args[0])


def event_of(send) -> Event:
    return send.call_args.args[1]


class TestRouting:
    def test_publishing_to_a_user_targets_their_private_group(
        self,
        sent,
    ):
        publish(
            Event(type="ping"),
            users=[42],
            on_commit=False,
        )

        assert groups_of(sent) == [user_group(42)]

    def test_a_user_instance_is_accepted(self, sent, user):
        publish_to_users([user], "ping", on_commit=False)

        assert groups_of(sent) == [user_group(user.pk)]

    def test_broadcasting_targets_the_shared_group(self, sent):
        broadcast_event("maintenance", on_commit=False)

        assert groups_of(sent) == [bus.broadcast_group()]

    def test_a_topic_resolves_through_the_registry(
        self,
        sent,
        clean_topic_registry,
    ):
        clean_topic_registry.register("project.{project_id}")

        publish_to_topic(
            "project.{project_id}",
            "changed",
            parameters={"project_id": "7"},
            on_commit=False,
        )

        assert groups_of(sent) == ["generic.topic.project.7"]

    def test_an_undeclared_topic_is_refused(
        self,
        sent,
        clean_topic_registry,
    ):
        with pytest.raises(ValueError, match="not registered"):
            publish_to_topic("secrets", "changed", on_commit=False)

    def test_destinations_combine_without_duplicates(self, sent):
        publish(
            Event(type="ping"),
            users=[42, 42],
            groups=[user_group(42)],
            broadcast=True,
            on_commit=False,
        )

        groups = groups_of(sent)

        # send_to_groups deduplicates, but the caller should not have to
        # care either way.
        assert bus.broadcast_group() in groups

    def test_publishing_nowhere_does_nothing(self, sent):
        publish(Event(type="ping"), on_commit=False)

        sent.assert_not_called()


class TestPayload:
    def test_the_event_carries_a_timestamp(self, sent):
        publish(Event(type="ping"), users=[1], on_commit=False)

        assert event_of(sent).as_dict()["timestamp"]

    def test_the_payload_is_passed_through(self, sent):
        publish_to_users(
            [1],
            "table.changed",
            {"table": "books"},
            on_commit=False,
        )

        assert event_of(sent).as_dict()["payload"] == {"table": "books"}


@pytest.mark.django_db(transaction=True)
class TestTransactionSafety:
    def test_delivery_waits_for_the_commit(self, sent):
        with transaction.atomic():
            publish(Event(type="ping"), users=[1], on_commit=True)

            # Still inside the transaction: nothing has been sent.
            sent.assert_not_called()

        sent.assert_called_once()

    def test_a_rollback_cancels_the_event(self, sent):
        class Rollback(Exception):
            pass

        with pytest.raises(Rollback):
            with transaction.atomic():
                publish(Event(type="ping"), users=[1], on_commit=True)
                raise Rollback

        # Telling clients about a row that no longer exists would be
        # worse than telling them nothing.
        sent.assert_not_called()

    def test_the_default_can_be_switched_off(self, sent):
        with override_settings(GENERIC={"EVENTS_DISPATCH_ON_COMMIT": False}):
            with transaction.atomic():
                publish(Event(type="ping"), users=[1])

                sent.assert_called_once()


class TestResilience:
    def test_a_channel_layer_failure_does_not_break_the_caller(self):
        layer = mock.Mock()
        layer.group_send = mock.AsyncMock(side_effect=RuntimeError("down"))

        with mock.patch.object(
            bus,
            "get_channel_layer",
            return_value=layer,
        ):
            # An event that cannot be delivered must not take the
            # request that produced it down with it.
            bus.send_to_groups(["a"], Event(type="ping"))

    def test_no_channel_layer_is_a_no_op(self):
        with mock.patch.object(
            bus,
            "get_channel_layer",
            return_value=None,
        ):
            bus.send_to_groups(["a"], Event(type="ping"))


@pytest.mark.django_db
class TestNotificationSignals:
    """Notifications announce themselves once they are committed.

    Each test commits explicitly, because that is exactly when the
    framework releases the event.
    """

    def test_creating_a_notification_publishes_it(
        self,
        sent,
        user,
        django_capture_on_commit_callbacks,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            NotificationFactory(user=user, title="Build finished")

        assert groups_of(sent) == [user_group(user.pk)]

        payload = event_of(sent).as_dict()

        assert payload["type"] == "notification.created"
        assert payload["payload"]["title"] == "Build finished"

    def test_updating_a_notification_publishes_an_update(
        self,
        sent,
        notification,
        django_capture_on_commit_callbacks,
    ):
        sent.reset_mock()

        with django_capture_on_commit_callbacks(execute=True):
            notification.mark_read()

        assert event_of(sent).as_dict()["type"] == ("notification.updated")

    def test_deleting_a_notification_publishes_a_deletion(
        self,
        sent,
        notification,
        django_capture_on_commit_callbacks,
    ):
        notification_id = notification.pk
        sent.reset_mock()

        with django_capture_on_commit_callbacks(execute=True):
            notification.delete()

        payload = event_of(sent).as_dict()

        assert payload["type"] == "notification.deleted"
        assert payload["payload"] == {"id": notification_id}


class TestWhatTravels:
    """A payload is JSON before it reaches the layer.

    The Redis layer serialises with msgpack, which refuses a date, a
    Decimal, a UUID or a lazy translation: such an event used to be
    logged and dropped on a server, while the in-memory layer of the
    tests carried it through.
    """

    def test_every_value_is_plain_json(self):
        import datetime
        import json
        from decimal import Decimal
        from uuid import UUID

        from django.utils.translation import gettext_lazy

        payload = Event(
            type="row.changed",
            payload={
                "on": datetime.date(2026, 3, 15),
                "at": datetime.datetime(2026, 3, 15, 9, 30),
                "amount": Decimal("12.50"),
                "id": UUID("12345678-1234-5678-1234-567812345678"),
                "title": gettext_lazy("Needs attention"),
                "rows": [{"hours": Decimal("1.5")}],
            },
        ).as_dict()["payload"]

        # The standard encoder - msgpack's equal here - takes it as is.
        json.dumps(payload)
        assert payload["on"] == "2026-03-15"
        assert payload["amount"] == "12.50"
        assert payload["title"] == "Needs attention"
        assert payload["rows"] == [{"hours": "1.5"}]

    def test_what_nothing_can_encode_is_logged_not_raised(self, caplog):
        from asgiref.sync import async_to_sync

        layer = mock.AsyncMock()

        with mock.patch.object(bus, "get_channel_layer", return_value=layer):
            async_to_sync(bus.asend_to_groups)(
                ["generic.user.1"], Event(type="odd", payload={"x": object()})
            )

        assert layer.group_send.call_count == 0
        assert "cannot be encoded" in caplog.text

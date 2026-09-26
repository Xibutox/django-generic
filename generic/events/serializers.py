"""Serialization of notifications, for both REST and WebSocket."""

from __future__ import annotations

from typing import Any

from django.utils.encoding import force_str
from rest_framework import serializers

from generic.api.columns import (
    CharColumn,
    ChoiceColumn,
    DateTimeColumn,
)
from generic.api.serializers import DataTableModelSerializer
from generic.events.models import Notification, NotificationLevel


def serialize_notification(notification: Notification) -> dict[str, Any]:
    """Compact payload pushed over the socket.

    Deliberately hand written rather than routed through DRF: this runs
    on every publish, and the socket payload should stay stable even if
    the REST representation grows.
    """
    return {
        "id": notification.pk,
        # force_str, because an unsaved instance still holds whatever
        # was passed in - often a lazy translation, which is not JSON.
        "title": force_str(notification.title),
        "body": force_str(notification.body),
        "level": notification.level,
        "levelLabel": force_str(NotificationLevel(notification.level).label),
        "url": force_str(notification.url),
        "createdAt": notification.created_at.isoformat(),
        "readAt": (
            notification.read_at.isoformat() if notification.read_at else None
        ),
    }


class NotificationSerializer(DataTableModelSerializer):
    """Notification as a table row and as a REST resource."""

    title = CharColumn(title="Title", read_only=True)

    body = CharColumn(
        title="Message",
        read_only=True,
        allow_blank=True,
    )

    level = ChoiceColumn(
        title="Level",
        choices=NotificationLevel.choices,
        read_only=True,
        value_type="integer",
    )

    created_at = DateTimeColumn(title="Received", read_only=True)

    read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            "id",
            "title",
            "body",
            "level",
            "url",
            "created_at",
            "read_at",
            "read",
        )
        read_only_fields = fields

    def get_read(self, instance: Notification) -> bool:
        return instance.is_read

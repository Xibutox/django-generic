"""The announcement as a form and as JSON."""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from generic.api.forms import FormModelSerializer
from generic.maintenance.models import RestartAnnouncement


class RestartAnnouncementSerializer(FormModelSerializer):
    """What the page posts: the whole announcement, in one form."""

    class Meta:
        model = RestartAnnouncement
        fields = (
            "scheduled_at",
            "duration_minutes",
            "is_manual",
            "comment_en",
            "comment_fr",
        )

    form_sections = (
        {
            "name": "general",
            "title": _("When"),
            "description": _(
                "Everyone connected is warned now, a minute before, and "
                "seconds before."
            ),
            "position": 0,
        },
        {
            "name": "message",
            "title": _("What people are told"),
            "description": _(
                "Each person reads the comment of the language they use."
            ),
            "position": 1,
        },
    )
    form_overrides = {
        "scheduled_at": {"position": 0, "width": 6},
        "duration_minutes": {"position": 1, "width": 6},
        "is_manual": {"position": 2, "width": 12},
        # The positions run across the form, not within each section.
        "comment_en": {"section": "message", "position": 3, "rows": 3},
        "comment_fr": {"section": "message", "position": 4, "rows": 3},
    }

    def validate_scheduled_at(self, value: Any) -> Any:
        """An hour already past warns nobody in time."""
        if value <= timezone.now():
            raise serializers.ValidationError(
                _("Choose an hour that is still ahead.")
            )

        return value


class RestartAnnouncementStateSerializer(serializers.Serializer):
    """The read side: what a page needs to draw the banner."""

    id = serializers.IntegerField(read_only=True)
    phase = serializers.CharField(read_only=True)
    scheduledAt = serializers.CharField(read_only=True)
    durationMinutes = serializers.IntegerField(read_only=True)
    isManual = serializers.BooleanField(read_only=True)
    secondsUntil = serializers.IntegerField(read_only=True)
    comment = serializers.DictField(read_only=True)

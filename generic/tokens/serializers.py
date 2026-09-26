from __future__ import annotations

import datetime
from typing import Any

from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from generic.conf import generic_settings
from generic.tokens.models import ApiToken


class ApiTokenSerializer(serializers.ModelSerializer):
    """A token as its owner sees it - never the token itself."""

    id = serializers.CharField(source="pk", read_only=True)
    prefix = serializers.CharField(source="token_key", read_only=True)
    days = serializers.IntegerField(
        write_only=True,
        required=False,
        allow_null=True,
        min_value=1,
        label=_("Valid for (days)"),
    )

    class Meta:
        model = ApiToken
        fields = (
            "id",
            "name",
            "scope",
            "prefix",
            "created",
            "expiry",
            "last_used_at",
            "days",
        )
        read_only_fields = ("created", "expiry", "last_used_at")

    def validate_days(self, value: Any) -> Any:
        limit = generic_settings.API_TOKEN_MAX_DAYS

        if value is None and limit is not None:
            raise serializers.ValidationError(
                gettext("Every token expires, within %(days)s days.")
                % {"days": limit}
            )

        if value is not None and limit is not None and value > limit:
            raise serializers.ValidationError(
                gettext("At most %(days)s days.") % {"days": limit}
            )

        return value

    def expiry_of(self) -> datetime.timedelta | None:
        days = self.validated_data.get(
            "days", generic_settings.API_TOKEN_DEFAULT_DAYS
        )

        return datetime.timedelta(days=days) if days else None

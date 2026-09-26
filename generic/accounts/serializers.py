"""Serializers for the per-user endpoints."""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from generic.accounts.models import (
    APPEARANCE_PARAMETERS,
    SavedView,
    UserPreferences,
)
from generic.api.forms import FormModelSerializer
from generic.i18n import offered_languages

#: A saved table layout is a handful of names and values; anything much
#: larger is not a layout.
MAX_STATE_SIZE = 20_000

#: The appearance preferences, drawn as sliders by the appearance card
#: rather than as inputs of the preferences form.
APPEARANCE_FIELDS = tuple(
    name for name, _css, _scale, _range in APPEARANCE_PARAMETERS
)


def is_external_account(user: Any) -> bool:
    """Whether the account is managed by LDAP, SSO or the like.

    Such accounts have no usable local password, which is also what
    marks them: their name and password live with the provider.
    """
    # Anonymous has neither: nothing to be managed elsewhere.
    if not getattr(user, "is_authenticated", False):
        return False

    return not user.has_usable_password()


class PreferencesSerializer(FormModelSerializer):
    class Meta:
        model = UserPreferences
        fields = (
            "theme",
            "language",
            "navigation",
            "table_page_size",
            "remember_table_state",
            "notification_channel",
            *APPEARANCE_FIELDS,
        )

    form_sections = (
        {"name": "general", "title": "", "description": "", "position": 0},
    )
    form_overrides = {
        # The appearance card draws the theme and the colours, with
        # live previews; the endpoint still takes all of them.
        "theme": {"enabled": False},
        "language": {"position": 0, "width": 6},
        "navigation": {"position": 1, "width": 6},
        "table_page_size": {"position": 2, "width": 6},
        "notification_channel": {"position": 3, "width": 6},
        "remember_table_state": {"position": 4, "width": 12},
        **{name: {"enabled": False} for name in APPEARANCE_FIELDS},
    }

    def get_fields(self) -> dict[str, serializers.Field]:
        """Offer the project's languages, and only those.

        The stored value is a plain string - the offered languages are a
        setting, which a migration must not have to follow - so the list
        is built here, per request, and anything outside it is refused.
        """
        fields = super().get_fields()
        language = fields.get("language")

        if language is not None:
            fields["language"] = serializers.ChoiceField(
                choices=offered_languages(),
                required=False,
                allow_blank=True,
                label=language.label,
                help_text=language.help_text,
            )

        return fields


def _profile_fields() -> tuple[str, ...]:
    """The usual profile fields the project's user model actually has."""
    model = get_user_model()
    names = {field.name for field in model._meta.get_fields()}
    wanted = ("first_name", "last_name", "email")

    return (model.USERNAME_FIELD, *[name for name in wanted if name in names])


class ProfileSerializer(FormModelSerializer):
    """The signed-in user's own name and address."""

    class Meta:
        model = get_user_model()
        fields = _profile_fields()
        read_only_fields = (get_user_model().USERNAME_FIELD,)

    form_sections = (
        {"name": "general", "title": "", "description": "", "position": 0},
    )
    form_overrides = {
        get_user_model().USERNAME_FIELD: {"position": 0, "width": 12},
        "first_name": {"position": 1, "width": 6},
        "last_name": {"position": 2, "width": 6},
        "email": {"position": 3, "width": 12},
    }

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        request = self.context.get("request")

        # An externally managed account gets its identity from the
        # provider; editing it here would be overwritten at next login.
        if request is not None and is_external_account(request.user):
            for field in fields.values():
                field.read_only = True

        return fields


class SavedViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedView
        fields = (
            "id",
            "table",
            "name",
            "state",
            "is_default",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_state(self, value: Any) -> Any:
        if not isinstance(value, dict):
            raise serializers.ValidationError(_("A JSON object is expected."))

        if len(json.dumps(value)) > MAX_STATE_SIZE:
            raise serializers.ValidationError(_("This layout is too large."))

        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        request = self.context.get("request")
        instance = self.instance
        table = attrs.get("table", getattr(instance, "table", None))
        name = attrs.get("name", getattr(instance, "name", None))

        if request is not None and table and name:
            clash = SavedView.objects.filter(
                user=request.user,
                table=table,
                name=name,
            )

            if instance is not None:
                clash = clash.exclude(pk=instance.pk)

            if clash.exists():
                raise serializers.ValidationError(
                    {"name": _("You already have a view with this name.")}
                )

        return attrs

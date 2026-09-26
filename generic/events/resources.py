"""Messages, as an ordinary screen.

Whoever holds ``generic.add_message`` writes one - to some people, some
groups, or everyone - and each recipient finds it among their
notifications, or in their inbox, as they chose. The list is the record
of what was said, by whom, to how many, and how many have read it.

A message is not edited once sent: the notifications it left are
copies, and changing the original would leave them saying something
else. Deleting one withdraws those notifications.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models import Count, Q
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from generic.accounts.resources import GROUP
from generic.conf import generic_settings
from generic.events.messages import recipients, send
from generic.events.models import Message, NotificationLevel
from generic.sites import ModelResource, TagStyle, display, site

logger = logging.getLogger(__name__)

#: The colours the notification levels are drawn in everywhere else.
LEVEL_COLORS = {
    NotificationLevel.INFO: "#2563eb",
    NotificationLevel.SUCCESS: "#16a34a",
    NotificationLevel.WARNING: "#d97706",
    NotificationLevel.CRITICAL: {"background": "#dc2626", "color": "#ffffff"},
}


def is_link(value: str) -> bool:
    """An address on this site, or a full web address - nothing else."""
    if not value:
        return True

    if value.startswith("/"):
        # Not "//host": that is another site, written to look like ours.
        return not value.startswith("//")

    return value.startswith(("https://", "http://"))


class MessageResource(ModelResource):
    """What was said to whom, and a form to say something new."""

    icon = "campaign"
    group = GROUP
    order = 3
    description = _(
        "Tell some people something, or everyone: each of them finds it "
        "among their notifications, or in their inbox, as they chose."
    )

    list_display = (
        "title",
        "level",
        "audience",
        "sender",
        "sent_at",
        "recipient_count",
        "read",
    )
    list_display_links = ("title",)
    list_select_related = ("sender",)
    list_prefetch_related = ("users", "groups")
    search_fields = ("title", "body")
    ordering = ("-sent_at", "-pk")
    tag_fields = {"level": TagStyle(colors=LEVEL_COLORS)}

    fieldsets = (
        (None, {"fields": ("title", "body", ("level", "url"))}),
        (
            _("Recipients"),
            {
                "fields": ("everyone", ("users", "groups"), "delivery"),
                "description": _(
                    "Everyone, or the people and groups chosen: a person "
                    "in two of them hears it once."
                ),
            },
        ),
    )
    form_overrides = {
        "body": {"rows": 6},
        "url": {"placeholder": "/tickets/"},
    }

    detail_stats = ("recipient_count", "read")
    detail_fieldsets = (
        (None, {"fields": ("title", "body", ("level", "url"))}),
        (
            _("Recipients"),
            {"fields": ("everyone", ("users", "groups"), "delivery")},
        ),
        (_("Sent"), {"fields": (("sender", "sent_at"),)}),
    )

    # Written once and never changed: a version history would hold one
    # version, and nobody watches what they wrote themselves.
    history = False
    watchable = False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def get_list_queryset(self, request: Any) -> Any:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                read_total=Count(
                    "notifications",
                    filter=Q(notifications__read_at__isnull=False),
                )
            )
        )

    @display(description=_("To"))
    def audience(self, message: Message) -> str:
        if message.everyone:
            return gettext("Everyone")

        names = [str(group) for group in message.groups.all()]
        names += [str(user) for user in message.users.all()]

        return ", ".join(names)

    @display(description=_("Read"), ordering="read_total")
    def read(self, message: Message) -> int:
        """How many of the notifications it left have been read."""
        total = getattr(message, "read_total", None)

        if total is None:
            total = message.notifications.filter(read_at__isnull=False).count()

        return total

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        data = serializer.validated_data

        if not is_link(data.get("url", "")):
            raise serializers.ValidationError(
                {
                    "url": [
                        gettext(
                            "Give an address on this site, starting with "
                            "/, or one starting with https://."
                        )
                    ]
                }
            )

        addressees = recipients(
            everyone=data.get("everyone", False),
            users=data.get("users", ()),
            groups=data.get("groups", ()),
        )

        if not addressees.exists():
            raise serializers.ValidationError(
                {
                    "users": [
                        gettext(
                            "Nobody would receive it: choose people, "
                            "groups with active members, or everyone."
                        )
                    ]
                }
            )

        message = serializer.save(sender=request.user)

        # Once it is stored: a message that a rollback removes must not
        # have reached anybody's inbox already.
        transaction.on_commit(lambda: deliver(message))

        return message


def deliver(message: Message) -> None:
    """Send it; a failure is logged, and shows as nobody reached."""
    try:
        send(message)
    except Exception:
        logger.exception("Could not send message %s", message.pk)


def register_screens() -> None:
    """Put the messages screen on the site.

    Called from ``GenericConfig.ready()`` after every app's
    ``resources.py``; ``SHOW_MESSAGES = False`` leaves it out, and a
    project that registers ``Message`` itself keeps its own.
    """
    if not generic_settings.SHOW_MESSAGES:
        return

    if not site.is_registered(Message):
        site.register(Message, MessageResource)

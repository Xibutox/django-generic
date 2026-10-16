"""The security events, as a screen of their own.

Open to whoever holds ``generic.view_securityevent``: who signed in
from where is about people, and the screen is for whoever answers for
the security of the site.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from generic.audit.models import SecurityEvent
from generic.sites import ModelResource, TagStyle, site

KIND_COLORS = {
    SecurityEvent.Kind.SIGNED_IN: "#16a34a",
    SecurityEvent.Kind.SIGNED_OUT: "#64748b",
    SecurityEvent.Kind.SIGN_IN_FAILED: "#d97706",
    SecurityEvent.Kind.LOCKED_OUT: "#dc2626",
    SecurityEvent.Kind.PASSWORD_CHANGED: "#2563eb",
    SecurityEvent.Kind.TOKEN_CREATED: "#7c3aed",
    SecurityEvent.Kind.TOKEN_DELETED: "#7c3aed",
    SecurityEvent.Kind.ACCESS_GRANTED: "#0891b2",
    SecurityEvent.Kind.ACCESS_REFUSED: "#d97706",
    SecurityEvent.Kind.EXPORTED: "#db2777",
}


class SecurityEventResource(ModelResource):
    """Every sign-in, refusal, right given and export."""

    icon = "shield_person"
    group = _("History")
    label = _("security event")
    label_plural = _("security events")
    description = _(
        "Who signed in, failed to or was locked out, from where; "
        "passwords changed, API tokens, rights granted, exports."
    )

    list_display = (
        "at",
        "kind",
        "username",
        "actor_label",
        "detail",
        "address",
    )
    list_display_links = ("at",)
    search_fields = ("username", "actor_label", "detail", "address")
    ordering = ("-at", "-pk")
    tag_fields = {"kind": TagStyle(colors=KIND_COLORS)}
    list_select_related = ("user",)
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    ("kind", "at"),
                    ("user", "username"),
                    "actor_label",
                    "detail",
                    ("address", "user_agent"),
                )
            },
        ),
    )

    # A log is read, never written from a screen - and keeps no log of
    # its own reading.
    history = False
    watchable = False
    realtime = False
    actions = ()

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False


def register_screens() -> None:
    """Put the security events on the site, unless the log is off."""
    from generic.audit import is_on

    if is_on() and not site.is_registered(SecurityEvent):
        site.register(SecurityEvent, SecurityEventResource)

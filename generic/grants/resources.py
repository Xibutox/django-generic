"""The access requests, as a screen of their own.

Read by superusers and by whoever holds
``generic.validate_accessrequest`` (or ``view_accessrequest``, to read
without deciding); granted or refused from the list or a request's
page. On the site only where the project gives a right on request.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from generic import grants
from generic.grants.models import AccessRequest
from generic.sites import ModelResource, TagStyle, action, display, site

STATUS_COLORS = {
    AccessRequest.Status.PENDING: "#d97706",
    AccessRequest.Status.GRANTED: "#16a34a",
    AccessRequest.Status.REFUSED: "#dc2626",
}

KIND_COLORS = {
    AccessRequest.Kind.EXPORT: "#2563eb",
    AccessRequest.Kind.DOWNLOAD: "#7c3aed",
}


class AccessRequestResource(ModelResource):
    """Every request for a right given on request, decided or not."""

    icon = "key"
    group = _("People")
    label = _("access request")
    label_plural = _("access requests")
    description = _(
        "People asking to export tables or download files: grant or "
        "refuse each request."
    )

    list_display = (
        "last_asked_at",
        "who",
        "kind",
        "status",
        "message",
        "times_asked",
        "asked_at",
        "decided_by",
        "decided_at",
    )
    list_display_links = ("last_asked_at",)
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "message",
    )
    ordering = ("-last_asked_at", "-pk")
    list_select_related = ("user", "decided_by")
    tag_fields = {
        "status": TagStyle(colors=STATUS_COLORS),
        "kind": TagStyle(colors=KIND_COLORS),
    }
    presets = {
        _("Waiting"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "any_of",
                        "value": [AccessRequest.Status.PENDING],
                    }
                ],
            },
        },
    }
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    ("user", "kind"),
                    ("status", "times_asked"),
                    "message",
                    "page",
                    ("asked_at", "last_asked_at"),
                    "notified_at",
                    ("decided_by", "decided_at"),
                )
            },
        ),
    )
    actions = ("grant_selected", "refuse_selected")

    # Decided through the two actions only, never written in a form.
    watchable = False
    mailing = False

    def has_view_permission(self, request: Any, obj: Any = None) -> bool:
        return grants.may_validate(
            request.user
        ) or super().has_view_permission(request, obj)

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    @display(description=_("Asked by"), ordering="user__username")
    def who(self, access_request: AccessRequest) -> str:
        from generic.sites.site import user_display_name

        return user_display_name(access_request.user)

    def decide(self, request: Any, queryset: Any, granted: bool) -> Any:
        done = sum(
            grants.decide(entry, by=request.user, granted=granted)
            for entry in queryset.filter(
                status=AccessRequest.Status.PENDING
            ).select_related("user")
        )

        if not done:
            return {
                "message": gettext(
                    "Nothing to decide: these requests were decided "
                    "already, or are your own."
                ),
                "level": "warning",
            }

        if granted:
            return ngettext(
                "%(count)d request granted.",
                "%(count)d requests granted.",
                done,
            ) % {"count": done}

        return ngettext(
            "%(count)d request refused.",
            "%(count)d requests refused.",
            done,
        ) % {"count": done}

    @action(
        description=_("Grant"),
        icon="check_circle",
        permissions=(grants.VALIDATE,),
        help=_("Give each person the right they asked for, and tell them."),
    )
    def grant_selected(self, request: Any, queryset: Any) -> Any:
        return self.decide(request, queryset, granted=True)

    @action(
        description=_("Refuse"),
        icon="block",
        variant="danger",
        permissions=(grants.VALIDATE,),
        confirm=_("Refuse the selected requests?"),
        help=_("Refuse each request, and tell the person who asked."),
    )
    def refuse_selected(self, request: Any, queryset: Any) -> Any:
        return self.decide(request, queryset, granted=False)


def register_screens() -> None:
    """Put the access requests on the site when a right is given on
    request; a project registering ``AccessRequest`` keeps its own."""
    if not grants.gated() or site.is_registered(AccessRequest):
        return

    site.register(AccessRequest, AccessRequestResource)

"""The access log, as a screen of its own.

Open to whoever holds ``generic.view_accessentry`` - a table of every
look at every record is a table of records the reader may not be
allowed to see - and only in a project where some resource declares
``access_log``.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from generic.access import key_of
from generic.access.models import AccessEntry
from generic.sites import ModelResource, TagStyle, display, site

ACTION_COLORS = {
    AccessEntry.Action.VIEWED: "#2563eb",
    AccessEntry.Action.DOWNLOADED: "#7c3aed",
}


class AccessEntryResource(ModelResource):
    """Every recorded look at a record."""

    icon = "visibility"
    group = _("History")
    label = _("access")
    label_plural = _("access log")
    description = _("Who opened which record, and who downloaded which file.")

    list_display = (
        "at",
        "content_type",
        "label",
        "action",
        "detail",
        "who",
        "address",
        "record_key",
    )
    list_display_links = ("at",)
    search_fields = ("label", "user_label", "detail", "record_key")
    ordering = ("-at", "-pk")
    tag_fields = {"action": TagStyle(colors=ACTION_COLORS)}
    list_select_related = ("content_type", "user")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    ("content_type", "object_id"),
                    "label",
                    ("action", "detail"),
                    ("user", "user_label"),
                    ("address", "at"),
                )
            },
        ),
    )

    # A log of reads is read, never written - and keeps no log of its
    # own reading.
    history = False
    watchable = False
    realtime = False
    actions = ()

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    @display(description=_("By"), ordering="user_label")
    def who(self, entry: AccessEntry) -> str:
        return entry.user_label or str(entry.user or "")


def record_url(obj: Any) -> str:
    """The access log's list, showing ``obj``'s accesses only."""
    resource = site.get_resource(AccessEntry)

    if resource is None:
        return ""

    filters = {
        "match": "all",
        "conditions": [
            {
                "column": "record_key",
                "operator": "equals",
                "value": key_of(obj),
            }
        ],
    }

    return f"{resource.get_list_url()}?filters={quote(json.dumps(filters))}"


def record_link(request: Any, resource: Any, obj: Any) -> Any:
    """The *Access log* button of a record's page, for who may read it."""
    from generic.views.toolbar import ToolbarItem

    if not getattr(resource, "access_log", False):
        return None

    log = site.get_resource(AccessEntry)

    if log is None or not log.has_view_permission(request):
        return None

    url = record_url(obj)

    if not url:
        return None

    return ToolbarItem(
        url=url,
        label=gettext("Access log"),
        icon="visibility",
        variant="ghost",
    )


def register_screens() -> None:
    """Put the access log on the site when a resource keeps one."""
    if site.is_registered(AccessEntry):
        return

    if any(
        getattr(resource, "access_log", False)
        for resource in site.get_resources()
    ):
        site.register(AccessEntry, AccessEntryResource)

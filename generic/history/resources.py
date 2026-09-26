"""The history, as a screen of its own.

The tab on a record answers "what happened to this?". This answers
"what happened?" - every recorded change, newest first, with the
filters, the search and the exports every other table has.

It is a different question with a different door: the tab is open to
whoever may read the record, this list to whoever holds
``generic.view_historyentry``, because a single table of everything is
a table of records the reader may not be allowed to see.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from generic.conf import generic_settings
from generic.history.models import HistoryEntry
from generic.sites import ModelResource, TagStyle, display, site

#: A change says what kind of change it was before anything else.
ACTION_COLORS = {
    HistoryEntry.Action.CREATED: "#16a34a",
    HistoryEntry.Action.UPDATED: "#2563eb",
    HistoryEntry.Action.DELETED: {"background": "#dc2626", "color": "#fff"},
}


class HistoryEntryResource(ModelResource):
    """Every recorded change, whatever it was made to."""

    icon = "manage_history"
    group = _("History")
    # The noun, not the button: the framework's own "Change" is the
    # row action, and one catalog entry cannot hold both.
    label = pgettext_lazy("a recorded change", "Change")
    label_plural = pgettext_lazy("a recorded change", "Changes")
    description = _("Every change that was recorded, and who made it.")

    list_display = (
        "at",
        "content_type",
        "label",
        "action",
        "version",
        "who",
        "source",
    )
    list_display_links = ("at",)
    search_fields = ("label", "user_label", "source", "object_id")
    ordering = ("-at", "-pk")
    tag_fields = {"action": TagStyle(colors=ACTION_COLORS)}
    list_select_related = ("content_type", "user")

    detail_stats = ("action", "version", "who")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    ("content_type", "object_id"),
                    "label",
                    ("user", "user_label"),
                    ("source", "at"),
                    "values",
                )
            },
        ),
    )

    # A history nobody can write is the only kind worth keeping, and it
    # keeps none of itself: recording a recording has no end.
    history = False
    watchable = False

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    @display(description=_("By"), ordering="user_label")
    def who(self, entry: HistoryEntry) -> str:
        return entry.who


def register_screens() -> None:
    """Put the history list on the site, unless history is switched off.

    Called from ``GenericConfig.ready()`` after every app's
    ``resources.py``, like the task screens: a project gets the page
    without declaring anything, and never sees it without the
    permission.
    """
    if not generic_settings.HISTORY:
        return

    if not site.is_registered(HistoryEntry):
        site.register(HistoryEntry, HistoryEntryResource)

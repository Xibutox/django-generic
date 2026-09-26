"""API tokens on the People screens: everyone's, for whoever may.

Read and revoke only. A token is created by its owner, on the account
page, where it is shown once; nobody else ever sees it, administrators
included.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from generic.accounts.resources import GROUP
from generic.sites import ModelResource, site
from generic.tokens.models import ApiToken


class ApiTokenResource(ModelResource):
    icon = "key"
    group = GROUP
    order = 3
    description = _(
        "Tokens scripts call the API with, as the person who made them."
    )

    list_display = (
        "name",
        "user",
        "scope",
        "created",
        "expiry",
        "last_used_at",
    )
    search_fields = ("name", "user__username", "token_key")
    ordering = ("-last_used_at", "name")
    fields = ("name", "scope")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "user",
                    "scope",
                    "token_key",
                    "created",
                    "expiry",
                    "last_used_at",
                )
            },
        ),
    )
    actions = ("delete_selected",)
    watchable = False
    mailing = False
    # The token's bookkeeping is no one's news; revoking is, and the
    # deletion is what the history keeps.
    history_exclude = ("last_used_at",)

    def get_queryset(self, request: Any) -> QuerySet:
        return super().get_queryset(request).select_related("user")

    def has_add_permission(self, request: Any) -> bool:
        # Made on the account page, by its owner, and shown only there.
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False


def register_screens() -> None:
    if not site.is_registered(ApiToken):
        site.register(ApiToken, ApiTokenResource)

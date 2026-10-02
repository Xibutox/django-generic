"""Who may merge: ``GENERIC["DOCX_MERGE_PERMISSION"]``."""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission

from generic.conf import generic_settings
from generic.sites.site import NavigationLink


def may_merge(user: Any) -> bool:
    """Whether ``user`` may open the merge page and use its endpoint.

    The setting reads like a navigation link's ``permission``: ``None``
    for any signed-in user, a permission string, several, or
    ``callable(user)``.
    """
    link = NavigationLink(
        label="", permission=generic_settings.DOCX_MERGE_PERMISSION
    )

    return link.is_visible(user)


class MayMerge(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return may_merge(request.user)

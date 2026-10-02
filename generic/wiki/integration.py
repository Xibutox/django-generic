"""Where the wiki joins the site: the menu, the dashboard, the search."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from generic.conf import generic_settings
from generic.search import text_lookup
from generic.wiki.models import Wiki, WikiPage
from generic.wiki.sanitize import safe_html

#: Pinned pages shown on the dashboard, at most.
DASHBOARD_LIMIT = 6


def readable(user: Any) -> Any:
    """The pages of the wikis ``user`` sees."""
    return WikiPage.objects.filter(wiki__in=Wiki.objects.readable_by(user))


def pinned_pages(request: Any) -> dict[str, Any]:
    """The pages pinned to the dashboard, ready to render."""
    if not getattr(request.user, "is_authenticated", False):
        return {}

    pages = (
        readable(request.user)
        .filter(show_on_dashboard=True)
        .select_related("wiki")
        .order_by("wiki__position", "wiki__name", "position", "title")
    )[:DASHBOARD_LIMIT]

    return {
        "wiki_pinned": [
            {
                "title": page.title,
                "url": page.get_absolute_url(),
                # Cleaned on the way out as well as on the way in.
                "content": safe_html(page.content),
            }
            for page in pages
        ]
    }


def search_pages(request: Any, term: str) -> list[dict[str, Any]]:
    """Wiki pages for the command palette."""
    if not getattr(request.user, "is_authenticated", False):
        return []

    pages = (
        readable(request.user)
        .filter(
            Q(**{text_lookup("title"): term})
            | Q(**{text_lookup("content"): term})
        )
        .select_related("wiki")
        .order_by("wiki__position", "wiki__name", "position", "title")
    )[: generic_settings.SEARCH_RESULTS_PER_RESOURCE]

    items = [
        {
            "label": page.title,
            "url": page.get_absolute_url(),
            "icon": "article",
            # Which wiki, when there are several.
            "description": page.wiki.name,
        }
        for page in pages
    ]

    if not items:
        return []

    return [{"label": _("Wiki"), "icon": "auto_stories", "items": items}]


def connect(site: Any) -> None:
    site.add_link(
        _("Wiki"),
        route="generic_wiki:index",
        icon="auto_stories",
        order=0,
    )
    site.index_context(pinned_pages)
    site.search_provider(search_pages)

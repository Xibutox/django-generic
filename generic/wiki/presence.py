"""Who is editing a page right now.

An open editor tells the server every ``BEAT`` seconds (``POST
pages/<id>/editing/``) and when it closes (``{"active": false}``); an
editor not heard from for ``TTL`` seconds has left. The answer names the
others, so whoever opens the editor is warned that someone else already
writes there - the save's ``version`` check still stops one from
overwriting the other.

Whoever reads the page hears of it as it happens through the
``wiki.page.{page_id}`` topic (generic.events): ``wiki.editing``, with
the editors, and ``wiki.comments`` when a comment comes or goes. Without
Channels nothing is pushed, and the page says what it knew when it was
opened.

The editors are kept in Django's cache: a cache shared by the workers
(Redis, Memcached, the database) is what makes them seen across them.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from django.core.cache import cache

from generic.wiki.models import Wiki, WikiPage

logger = logging.getLogger(__name__)

#: Seconds between an open editor's beats.
BEAT = 20

#: Seconds an editor not heard from is still counted.
TTL = 45

#: The topic a page's readers follow.
TOPIC = "wiki.page.{page_id}"


def _key(page: WikiPage) -> str:
    return f"generic.wiki.editing.{page.pk}"


def _live(entries: dict[str, Any], now: float) -> dict[str, Any]:
    return {
        user_id: entry
        for user_id, entry in entries.items()
        if isinstance(entry, dict) and entry.get("until", 0) > now
    }


def editors(page: WikiPage, exclude: Any = None) -> list[dict[str, Any]]:
    """Who has the page open in the editor: ``[{"id", "name"}]``."""
    entries = _live(cache.get(_key(page)) or {}, time.time())

    return [
        {"id": int(user_id), "name": entry["name"]}
        for user_id, entry in sorted(entries.items())
        if exclude is None or str(user_id) != str(exclude)
    ]


def beat(page: WikiPage, user: Any, active: bool = True) -> list[dict]:
    """``user`` is editing the page - or stopped. Answers the others."""
    from generic.wiki.serializers import display_name

    now = time.time()
    before = _live(cache.get(_key(page)) or {}, now)
    entries = dict(before)

    if active:
        entries[str(user.pk)] = {
            "name": display_name(user),
            "until": now + TTL,
        }
    else:
        entries.pop(str(user.pk), None)

    cache.set(_key(page), entries, TTL * 2)

    if set(entries) != set(before):
        tell(page, "wiki.editing", {"editors": editors(page)})

    return editors(page, exclude=user.pk)


def tell(page: WikiPage, kind: str, payload: dict[str, Any]) -> None:
    """An event for whoever reads the page."""
    from generic.events.bus import publish_to_topic

    try:
        publish_to_topic(
            TOPIC,
            kind,
            {"page": page.pk, **payload},
            parameters={"page_id": str(page.pk)},
            on_commit=False,
        )
    except Exception:
        logger.exception("Could not tell the readers of page %s", page.pk)


def may_follow(user: Any, topic: str, parameters: dict[str, str]) -> bool:
    """Whether ``user`` reads the page a topic is about."""
    if not getattr(user, "is_authenticated", False):
        return False

    page_id = parameters.get("page_id", "")

    return (
        page_id.isdigit()
        and WikiPage.objects.filter(
            pk=int(page_id), wiki__in=Wiki.objects.readable_by(user)
        ).exists()
    )


def register() -> None:
    """Declare the topic (``WikiConfig.ready``)."""
    from generic.events.registry import register_topic, registry

    registry.unregister(TOPIC)
    register_topic(
        TOPIC,
        permission=may_follow,
        description="Who edits a wiki page, and its comments.",
        parameters=("page_id",),
    )

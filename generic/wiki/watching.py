"""Being told when a wiki's pages change, and what changed lately.

A reader watches a page - told when it is changed or deleted - or a
whole wiki - told when any of its pages is created, changed or
deleted. The watches are the framework's own (``generic.watch``), so
they are tuned and stopped on the *Watching* page like any other, and
reach each reader the way they chose: a notification, an e-mail, both.

Nobody is told of their own change, and nobody is told of a wiki they
can no longer read: who reads it is asked again for every message.
Telling happens after the save commits, and never breaks it.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils.translation import gettext as _

from generic import delivery
from generic.delivery import NotificationLevel
from generic.wiki.models import Wiki, WikiPage

logger = logging.getLogger(__name__)

#: What a change is called, in a message: ``created``, ``updated``,
#: ``deleted``.
CHANGES = ("created", "updated", "deleted")


def watches_of(thing: Any) -> Any:
    """The watches on ``thing``, a page or a wiki."""
    from generic.watch.models import Watch

    return Watch.objects.filter(
        content_type=ContentType.objects.get_for_model(type(thing)),
        object_id=str(thing.pk),
    ).select_related("user")


def is_watching(user: Any, thing: Any) -> bool:
    return watches_of(thing).filter(user=user).exists()


def toggle(user: Any, thing: Any) -> bool:
    """Start watching ``thing``, or stop. Answers whether watching."""
    from generic.watch import unwatch, watch

    if is_watching(user, thing):
        unwatch(user, thing)

        return False

    # A wiki is watched for what happens to its pages - each one new,
    # changed or gone - whatever events a record's watch would take.
    watch(user, thing)

    return True


def sentence(change: str, page: WikiPage, actor: Any) -> str:
    from generic.wiki.serializers import display_name

    values = {
        "name": display_name(actor) if actor is not None else _("Someone"),
        "title": page.title,
        "wiki": page.wiki.name,
    }

    if change == "created":
        return _("%(name)s wrote “%(title)s” in %(wiki)s.") % values

    if change == "deleted":
        return _("%(name)s deleted “%(title)s” from %(wiki)s.") % values

    if change == "commented":
        return _("%(name)s commented on “%(title)s” in %(wiki)s.") % values

    return _("%(name)s changed “%(title)s” in %(wiki)s.") % values


def announce(page: WikiPage, change: str, actor: Any = None) -> None:
    """Tell whoever watches ``page`` or its wiki, once the save is in:
    ``change`` is ``created``, ``updated``, ``deleted`` - or
    ``commented``, for the page's watchers only."""
    transaction.on_commit(lambda: _announce(page, change, actor))


def _announce(page: WikiPage, change: str, actor: Any) -> int:
    try:
        # A comment is news for the page's watchers, not the wiki's.
        found = [] if change == "commented" else list(watches_of(page.wiki))

        if change != "created":
            wanted = "updated" if change == "commented" else change
            found += [
                watch for watch in watches_of(page) if watch.wants(wanted)
            ]
    except Exception:
        logger.exception("Could not read the watches of page %s", page.pk)

        return 0

    told: set[Any] = set()
    url = page.get_absolute_url() if change != "deleted" else ""

    for watch in found:
        user = watch.user

        if (
            user.pk in told
            or (actor is not None and user.pk == actor.pk)
            or not user.is_active
            or not Wiki.objects.readable_by(user)
            .filter(pk=page.wiki_id)
            .exists()
        ):
            continue

        told.add(user.pk)

        try:
            delivery.deliver(
                [user],
                channels=watch.resolve_channels(),
                message=lambda watch=watch: (
                    sentence(change, page, actor),
                    _("You are watching %(what)s.")
                    % {"what": watch.target_label},
                    (
                        NotificationLevel.WARNING
                        if change == "deleted"
                        else NotificationLevel.INFO
                    ),
                ),
                url=url,
                content_object=None,
                context=f"wiki watch {watch.pk}",
            )
        except Exception:
            logger.exception("Could not deliver wiki watch %s", watch.pk)

    return len(told)


def recent_changes(user: Any, wiki: Wiki | None = None, limit: int = 30):
    """The pages last written, newest first - in ``wiki``, or in every
    wiki ``user`` reads."""
    pages = WikiPage.objects.filter(wiki__in=Wiki.objects.readable_by(user))

    if wiki is not None:
        pages = pages.filter(wiki=wiki)

    return pages.select_related("wiki", "updated_by").order_by(
        "-updated_at", "-pk"
    )[:limit]

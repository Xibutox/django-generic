"""Pages and wikis copied into new ones.

A page's *Duplicate* asks for the copy's title and whether its subpages
come along, then writes the copy beside it (same parent, same wiki) and
opens it in the editor. A wiki's *Duplicate* asks for the copy's name and
description and whether its pages come along, every one under the same
parent as before.

The text is copied as it stands; the history is not - a copy starts its
own. Images and files are shared, not copied: an upload belongs to
whichever page links to it (``WikiPage.attachments``). A copy is never
pinned to the dashboard.

Who reads a wiki is the project's to say (``GENERIC["WIKI_ACCESS"]``), and
a new wiki is nobody's yet: a project that ties wikis to teams, say,
listens to ``wiki_duplicated`` and gives the copy the source's readers -
in the same transaction, before anyone can open it (docmanager does).
"""

from __future__ import annotations

from typing import Any, Iterable

from django.db import transaction
from django.dispatch import Signal

from generic.wiki.models import Wiki, WikiPage
from generic.wiki.serializers import unique_slug

#: Sent, inside the copy's transaction, once a wiki and its pages are
#: copied: ``sender=Wiki``, ``source``, ``copy``, ``user``.
wiki_duplicated = Signal()


def subtree(pages: Iterable[WikiPage], root: Any) -> list[WikiPage]:
    """The pages under ``root`` (a page's key, None for the top),
    parents before their children, each once - a loop in the data
    cannot hold the copy up."""
    children: dict[Any, list[WikiPage]] = {}

    for page in pages:
        children.setdefault(page.parent_id, []).append(page)

    found: list[WikiPage] = []
    seen = set()
    queue = [root]

    while queue:
        for child in children.get(queue.pop(0), []):
            if child.pk not in seen:
                seen.add(child.pk)
                found.append(child)
                queue.append(child.pk)

    return found


def copy_page(page: WikiPage, wiki: Wiki, parent: Any, user: Any, **values):
    """One page written again in ``wiki`` under ``parent``."""
    title = values.get("title") or page.title

    return WikiPage.objects.create(
        wiki=wiki,
        title=title,
        slug=unique_slug(title, wiki=wiki),
        parent=parent,
        position=page.position,
        content=page.content,
        show_on_dashboard=False,
        created_by=user,
        updated_by=user,
    )


def copy_subpages(
    pages: list[WikiPage],
    root: Any,
    wiki: Wiki,
    parent: Any,
    user: Any,
) -> int:
    """The pages under ``root`` copied under ``parent`` in ``wiki``,
    the tree kept. Answers how many."""
    copies = {root: parent}
    count = 0

    for page in subtree(pages, root):
        copies[page.pk] = copy_page(
            page, wiki, copies.get(page.parent_id, parent), user
        )
        count += 1

    return count


def ordered(pages: Any) -> list[WikiPage]:
    return list(pages.order_by("position", "title", "pk"))


@transaction.atomic
def duplicate_page(
    page: WikiPage,
    user: Any,
    title: str,
    subpages: bool = False,
) -> WikiPage:
    """A copy of ``page`` beside it, titled ``title``; its subpages too
    when asked."""
    copy = copy_page(page, page.wiki, page.parent, user, title=title)

    if subpages:
        copy_subpages(
            ordered(WikiPage.objects.filter(wiki=page.wiki)),
            page.pk,
            page.wiki,
            copy,
            user,
        )

    return copy


@transaction.atomic
def duplicate_wiki(
    wiki: Wiki,
    user: Any,
    serializer: Any,
    pages: bool = True,
) -> Wiki:
    """A copy of ``wiki`` - name and description from ``serializer``,
    validated - with its pages when asked."""
    copy = serializer.save(position=wiki.position)

    if pages:
        copy_subpages(
            ordered(WikiPage.objects.filter(wiki=wiki)), None, copy, None, user
        )

    wiki_duplicated.send(sender=Wiki, source=wiki, copy=copy, user=user)

    return copy

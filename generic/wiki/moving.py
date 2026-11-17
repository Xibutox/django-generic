"""A page put somewhere else: elsewhere in its wiki's menu, or in
another wiki.

    place(page, parent, before)    # under ``parent``, before ``before``
    move_to_wiki(page, wiki)       # with its subpages, to another wiki

The menu is dragged and dropped (``POST pages/<id>/place/``): a page
dropped on another becomes its subpage, a page dropped between two
takes its place among them; its new siblings are numbered again, in
their order. Nothing of the text changes, so no version is kept.

A page moved to another wiki (``POST pages/<id>/move/``) takes its
subpages with it, to the end of that wiki's menu, keeping its history.
An address the other wiki already uses gets a number; the old addresses
keep leading to the pages (``WikiRedirect``). Its images and files stay
where they were uploaded: whoever reads a page showing one may open it
(``access.may_open``).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from generic.wiki.duplicates import subtree
from generic.wiki.models import Wiki, WikiPage, WikiRedirect
from generic.wiki.serializers import unique_slug


class MoveError(ValueError):
    """Why a page cannot go there; the message is for the reader."""


def under_itself(page: WikiPage, parent: WikiPage | None) -> bool:
    """Whether ``parent`` is ``page`` or one of its subpages."""
    seen: set[Any] = set()
    node = parent

    while node is not None and node.pk not in seen:
        if node.pk == page.pk:
            return True

        seen.add(node.pk)
        node = node.parent

    return False


def place(
    page: WikiPage,
    parent: WikiPage | None,
    before: WikiPage | None = None,
) -> list[WikiPage]:
    """``page`` under ``parent`` (None: the top of the menu), before
    ``before`` - one of the new siblings - or last. Answers the
    siblings, in their new order."""
    if parent is not None and parent.wiki_id != page.wiki_id:
        raise MoveError(_("The parent page is in another wiki."))

    if under_itself(page, parent):
        raise MoveError(_("A page cannot be placed under itself."))

    parent_id = parent.pk if parent is not None else None

    if before is not None and (
        before.pk == page.pk
        or before.wiki_id != page.wiki_id
        or before.parent_id != parent_id
    ):
        before = None

    with transaction.atomic():
        siblings = [
            sibling
            for sibling in WikiPage.objects.filter(
                wiki_id=page.wiki_id, parent_id=parent_id
            )
            .exclude(pk=page.pk)
            .order_by("position", "title", "pk")
        ]
        index = (
            next(
                (
                    number
                    for number, sibling in enumerate(siblings)
                    if sibling.pk == before.pk
                ),
                len(siblings),
            )
            if before is not None
            else len(siblings)
        )
        page.parent = parent
        siblings.insert(index, page)

        for position, sibling in enumerate(siblings):
            if sibling is page or sibling.position != position:
                sibling.position = position
                WikiPage.objects.filter(pk=sibling.pk).update(
                    position=position,
                    parent_id=parent_id,
                )

    return siblings


def move_to_wiki(page: WikiPage, wiki: Wiki) -> list[WikiPage]:
    """``page`` and its subpages, to the end of ``wiki``'s menu. Answers
    the pages moved, ``page`` first."""
    if wiki.pk == page.wiki_id:
        raise MoveError(_("The page is already in this wiki."))

    source = page.wiki

    with transaction.atomic():
        moved = [
            page,
            *subtree(WikiPage.objects.filter(wiki=source), page.pk),
        ]
        last = (
            WikiPage.objects.filter(wiki=wiki, parent=None)
            .order_by("-position")
            .values_list("position", flat=True)
            .first()
        )

        for node in moved:
            old_slug = node.slug
            slug = (
                old_slug
                if not WikiPage.all_objects.filter(
                    wiki=wiki, slug=old_slug
                ).exists()
                else unique_slug(node.title or old_slug, wiki=wiki)
            )
            fields = {"wiki_id": wiki.pk, "slug": slug}

            if node is page:
                fields["parent_id"] = None
                fields["position"] = 0 if last is None else last + 1

            WikiPage.objects.filter(pk=node.pk).update(**fields)

            for name, value in fields.items():
                setattr(node, name, value)

            node.wiki = wiki

            # The old address, in the old wiki, leads here still; the
            # new one is the page's, not a redirect's.
            WikiRedirect.objects.filter(wiki=wiki, slug=slug).delete()
            WikiRedirect.objects.update_or_create(
                wiki=source, slug=old_slug, defaults={"page": node}
            )

    return moved

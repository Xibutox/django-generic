"""Who may do what in a wiki: its owner, its members, and everyone else.

A wiki's ``access`` says who reads it and who writes in it:

==============  ======================  ================================
``access``      Reads it                Writes its pages
==============  ======================  ================================
``open``        everyone signed in      whoever holds the page
                                        permissions; its editors,
                                        managers and owner
``protected``   everyone signed in      its editors, managers and owner
``private``     its members and owner   its editors, managers and owner
==============  ======================  ================================

A member is a person or a group (``WikiMember``) with a role: a reader,
an editor, a manager. The role is enough to write: an editor of a wiki
needs no group giving ``add_wikipage`` - a wiki's people are named on
the wiki. Superusers read and write every wiki. The project's
``WIKI_ACCESS`` and ``WIKI_EDIT_ACCESS`` still narrow all of this.

Uploads - the images and files of the pages - are read by whoever
reads the wiki they were uploaded into, or a page showing them
(:func:`may_open`).
"""

from __future__ import annotations

from typing import Any

from generic.wiki.models import (
    ROLE_OWNER,
    ROLES,
    WRITER_ROLES,
    Wiki,
    WikiPage,
    WikiRevision,
    memberships,
)

PAGE_ACTIONS = ("add", "change", "delete")


def has_perm(user: Any, action: str, model: str = "wikipage") -> bool:
    """The model permission, for someone signed in."""
    return bool(
        user
        and user.is_authenticated
        and user.has_perm(f"generic_wiki.{action}_{model}")
    )


def roles_of(user: Any) -> dict[Any, str]:
    """``{wiki id: role}`` for every wiki ``user`` is a member of -
    the highest role, when a group and the person both hold one."""
    if not getattr(user, "is_authenticated", False):
        return {}

    roles: dict[Any, str] = {}

    for wiki_id, role in memberships(user).values_list("wiki", "role"):
        held = roles.get(wiki_id)

        if held is None or ROLES.index(role) > ROLES.index(held):
            roles[wiki_id] = role

    return roles


def role_in(user: Any, wiki: Wiki, roles: dict | None = None) -> str:
    """``"owner"``, a member's role, or ``""``."""
    if not getattr(user, "is_authenticated", False):
        return ""

    if wiki.owner_id is not None and wiki.owner_id == user.pk:
        return ROLE_OWNER

    if roles is None:
        roles = roles_of(user)

    return roles.get(wiki.pk, "")


def writes_pages(role: str) -> bool:
    return role == ROLE_OWNER or role in WRITER_ROLES


def manages(role: str) -> bool:
    return role in (ROLE_OWNER, ROLES[-1])


def page_rights(
    user: Any,
    wiki: Wiki,
    roles: dict | None = None,
    writable: bool | None = None,
) -> dict[str, bool]:
    """What ``user`` may do to the pages of ``wiki``: ``add``,
    ``change``, ``delete``.

    Nothing where they may not write (``writable_by``); everything for
    its owner, its managers and its editors; the model permissions for
    anyone else - which is an open wiki, the only one they write in.
    """
    if writable is None:
        writable = Wiki.objects.writable_by(user).filter(pk=wiki.pk).exists()

    if not writable:
        return dict.fromkeys(PAGE_ACTIONS, False)

    if writes_pages(role_in(user, wiki, roles)):
        return dict.fromkeys(PAGE_ACTIONS, True)

    return {name: has_perm(user, name) for name in PAGE_ACTIONS}


def wiki_rights(
    user: Any, wiki: Wiki, roles: dict | None = None
) -> dict[str, bool]:
    """What ``user`` may do to ``wiki`` itself, a wiki they read:
    ``change`` (its name, its description), ``members`` (its access and
    who its members are), ``delete``."""
    role = role_in(user, wiki, roles)
    change = manages(role) or has_perm(user, "change", "wiki")

    return {
        "change": change,
        "members": change,
        "delete": role == ROLE_OWNER or has_perm(user, "delete", "wiki"),
    }


def writes_somewhere(user: Any) -> bool:
    """Whether ``user`` may write pages in some wiki at all: what an
    upload sent without naming its wiki asks."""
    if not getattr(user, "is_authenticated", False):
        return False

    if has_perm(user, "add") or has_perm(user, "change"):
        return True

    return (
        Wiki.objects.filter(owner=user).exists()
        or memberships(user).filter(role__in=WRITER_ROLES).exists()
    )


def may_open(user: Any, upload: Any) -> bool:
    """Whether ``user`` may open ``upload``, an image or a file.

    Whoever reads the wiki it was uploaded into; whoever uploaded it -
    it is in their editor before any page is saved; and whoever reads a
    page, or a version of one, showing it: a copy of a wiki shares its
    uploads, and those from before uploads had a wiki have none.
    """
    if not getattr(user, "is_authenticated", False):
        return False

    readable = Wiki.objects.readable_by(user)

    if (
        upload.wiki_id is not None
        and readable.filter(pk=upload.wiki_id).exists()
    ):
        return True

    if upload.uploaded_by_id is not None and upload.uploaded_by_id == user.pk:
        return True

    # Its address ends with "/": 7's is never found in 71's.
    address = upload.get_absolute_url()

    return (
        WikiPage.objects.filter(
            wiki__in=readable, content__contains=address
        ).exists()
        or WikiRevision.objects.filter(
            page__deleted_at__isnull=True,
            page__wiki__in=readable,
            content__contains=address,
        ).exists()
    )

"""Who reads and who writes one document, beyond its team.

A document is read by its team (its folder's), as every record of a
team is. Its access list (``DocumentAccess``) adds people and groups,
each reading or writing it:

- **shared** - not ``restricted``: the team as before, and whoever the
  list names besides, in any team or none;
- **restricted** - the list alone: the team no longer reads it.

Who sees every team - the administrators, the managers - reads and
writes every document, restricted or not. Whoever a review asks reads
the document they are asked about (``workflows.py``). Writing still
takes the model permission (``documents.change_document``): the list
narrows and widens who, never what a role may do.

The rules are written twice: as a ``Q`` for the querysets (lists,
searches, merges, what hangs on a document) and as a test of one
document (its form, its files, its actions).
"""

from __future__ import annotations

from typing import Any

from django.db.models import Exists, OuterRef, Q, QuerySet

from documents.models import Document, DocumentAccess, ReviewTask
from generic.teams import sees_every_team
from generic.teams.scoping import is_member, own_teams

#: The documents' permission that makes one an author: who holds it
#: writes the documents they may write, and reads their drafts.
AUTHOR_PERMISSION = "documents.change_document"

#: Every document, and none - kept apart from ``Q()``, which an ``|``
#: would drop.
EVERYTHING = ~Q(pk__in=[])
NOTHING = Q(pk__in=[])


def listed(user: Any, path: str = "", write: bool = False) -> Q:
    """The documents at ``path`` whose access list names ``user`` - or
    one of their groups - (with ``write``: as a writer)."""
    entries = DocumentAccess.objects.filter(
        document=OuterRef(f"{path}pk"),
    ).filter(
        Q(user=user.pk) | Q(group__in=user.groups.values("pk")),
    )

    if write:
        entries = entries.filter(level=DocumentAccess.Level.WRITE)

    return Q(Exists(entries))


def asked(user: Any, path: str = "") -> Q:
    """The documents at ``path`` a review asks ``user`` about."""
    return Q(
        Exists(
            ReviewTask.objects.filter(
                document=OuterRef(f"{path}pk"), assignee=user.pk
            )
        )
    )


def in_team(user: Any, path: str = "") -> Q:
    return Q(**{f"{path}folder__team__in": own_teams(user).values("pk")})


def readable(user: Any, path: str = "") -> Q:
    """The documents ``user`` reads: their team's unrestricted ones,
    the ones listing them, the ones a review asks them about."""
    if sees_every_team(user):
        return EVERYTHING

    if not is_member(user):
        return NOTHING

    restricted = Q(**{f"{path}restricted": True})

    return (
        (in_team(user, path) & ~restricted)
        | listed(user, path)
        | asked(user, path)
    )


def writable(user: Any, path: str = "") -> Q:
    """The documents ``user`` writes - their team's unrestricted ones
    and the ones listing them as a writer - provided they are an
    author. Nothing for anyone else."""
    if not is_member(user) or not user.has_perm(AUTHOR_PERMISSION):
        return NOTHING

    if sees_every_team(user):
        return EVERYTHING

    restricted = Q(**{f"{path}restricted": True})

    return (in_team(user, path) & ~restricted) | listed(user, path, write=True)


def drafts(user: Any, path: str = "") -> Q:
    """The documents whose working file ``user`` reads: the ones they
    write, and the ones a review asks them about. Everyone else reads
    the published version."""
    if not is_member(user):
        return NOTHING

    return writable(user, path) | asked(user, path)


def of(queryset: QuerySet, condition: Q) -> QuerySet:
    """``queryset`` - documents - narrowed to ``condition``, through a
    subquery: the joins of the rules never duplicate a row."""
    if condition == EVERYTHING:
        return queryset

    return queryset.filter(
        pk__in=Document._default_manager.filter(condition).values("pk")
    )


def holds(condition: Q, document: Document) -> bool:
    if condition == EVERYTHING:
        return True

    return (
        Document._default_manager.filter(condition)
        .filter(pk=document.pk)
        .exists()
    )


def may_read(user: Any, document: Document) -> bool:
    return holds(readable(user), document)


def may_write(user: Any, document: Document) -> bool:
    return holds(writable(user), document)


def sees_drafts(user: Any, document: Document) -> bool:
    return holds(drafts(user), document)


def keep_writer(user: Any, document: Document) -> None:
    """Whoever restricts a document stays among its writers: nobody
    shuts themselves out of what they were writing."""
    if not document.restricted or not is_member(user):
        return

    if sees_every_team(user) or may_write(user, document):
        return

    DocumentAccess.objects.get_or_create(
        document=document,
        user=user,
        defaults={"level": DocumentAccess.Level.WRITE},
    )
    DocumentAccess.objects.filter(
        document=document, user=user, level=DocumentAccess.Level.READ
    ).update(level=DocumentAccess.Level.WRITE)


def summary(document: Document) -> str:
    """``Restricted: Bob (read and write), Quality (read)``."""
    from django.utils.translation import gettext

    entries = [
        f"{entry.user or entry.group} ({entry.get_level_display().lower()})"
        for entry in document.accesses.select_related("user", "group")
    ]

    if document.restricted:
        return gettext("Restricted to %(who)s") % {
            "who": ", ".join(entries) or gettext("nobody")
        }

    if entries:
        return gettext("Its team, and %(who)s") % {"who": ", ".join(entries)}

    return gettext("Its team")


__all__ = [
    "AUTHOR_PERMISSION",
    "drafts",
    "keep_writer",
    "may_read",
    "may_write",
    "of",
    "readable",
    "sees_drafts",
    "summary",
    "writable",
]

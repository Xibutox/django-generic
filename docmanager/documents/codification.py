"""Numbering documents: each team's pattern, filled in once per document.

A document is *codified* when it is given its number - at its creation
when its team asks for it (``Codification.on_create``), or later, from
the *Codify* action. It needs no file for that: a number may be
reserved for a document still to be written. The number never changes
afterwards, whatever is moved or renamed.

The counting itself is the framework's (``generic.numbering``): each
series - the pattern filled in but for its running number - counts on
its own, under a lock.
"""

from __future__ import annotations

import re
from typing import Any

from django.db import transaction
from django.utils import timezone

from documents.models import DEFAULT_PATTERN, Codification, Document
from generic.numbering import allocate, peek
from generic.teams.models import Team

#: The ``{type}`` of a document of no type.
NO_TYPE = "DOC"


def team_code(team: Team) -> str:
    """``LEG`` for *Legal*, when the team has not said: its first
    letters."""
    letters = re.sub(r"[^A-Za-z0-9]", "", team.name).upper()

    return letters[:3] or "TEAM"


def rules_of(team: Team) -> tuple[str, str, bool]:
    """``(pattern, team code, on create)`` for a team."""
    found = Codification.objects.filter(team=team).first()

    if found is None:
        return DEFAULT_PATTERN, team_code(team), False

    return found.pattern, found.code or team_code(team), found.on_create


def values_for(document: Document, code: str) -> dict[str, str]:
    kind = document.document_type

    return {"team": code, "type": kind.code if kind else NO_TYPE}


def taken(code: str) -> bool:
    return Document.objects.filter(code=code).exists()


def codify(document: Document) -> str:
    """Give ``document`` its number, if it has none yet; the number."""
    with transaction.atomic():
        document = (
            Document.objects.select_for_update()
            .select_related("folder__team", "document_type")
            .get(pk=document.pk)
        )

        if document.code:
            return document.code

        pattern, code, _on_create = rules_of(document.folder.team)
        document.code = allocate(
            pattern,
            namespace="documents",
            exists=taken,
            **values_for(document, code),
        )
        document.codified_at = timezone.now()
        document.save(update_fields=("code", "codified_at", "updated_at"))

        return document.code


def numbered_on_create(document: Document) -> bool:
    return rules_of(document.folder.team)[2]


def next_number(codification: Codification, kind: Any = None) -> str:
    """The number the team's next document of ``kind`` would get - only
    shown, never taken."""
    return peek(
        codification.pattern,
        namespace="documents",
        team=codification.code or team_code(codification.team),
        type=kind.code if kind else NO_TYPE,
    )

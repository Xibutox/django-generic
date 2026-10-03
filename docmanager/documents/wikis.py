"""Who reads and who writes which wiki: ``GENERIC["WIKI_ACCESS"]`` and
``GENERIC["WIKI_EDIT_ACCESS"]`` (docs/wiki.md).

A ``TeamWiki`` row says it, wiki by wiki:

* its ``team`` reads it - and nobody else; no team, everyone does;
* its ``editing_teams`` write in it - and read it, whoever reads it
  otherwise; none, whoever reads it may write in it.

A wiki without a row is everyone's to read and write. Whoever sees
every team - superusers, ``generic_teams.see_every_team`` - reads and
writes them all. What one may do in a wiki one writes in - add, change,
delete a page - is still the page permissions' (the groups).
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from documents.models import TeamWiki
from generic.teams import sees_every_team, teams_of


def edited_by_my_teams(user: Any) -> QuerySet:
    return TeamWiki.objects.filter(
        editing_teams__in=teams_of(user).values("pk")
    ).values("wiki")


def wikis_of_my_teams(user: Any, wikis: QuerySet) -> QuerySet:
    if sees_every_team(user):
        return wikis

    return wikis.filter(
        Q(team_link__isnull=True)
        | Q(team_link__team__isnull=True)
        | Q(team_link__team__in=teams_of(user).values("pk"))
        | Q(pk__in=edited_by_my_teams(user))
    )


def wikis_my_teams_write(user: Any, wikis: QuerySet) -> QuerySet:
    if sees_every_team(user):
        return wikis

    restricted = TeamWiki.objects.filter(editing_teams__isnull=False).values(
        "wiki"
    )

    return wikis.filter(
        Q(pk__in=edited_by_my_teams(user)) | ~Q(pk__in=restricted)
    )

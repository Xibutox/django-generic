"""Who reads which wiki: ``GENERIC["WIKI_ACCESS"]`` (docs/wiki.md).

A wiki linked to a team (``TeamWiki``) is read by its members only; a
wiki of no team is everyone's. Whoever sees every team - superusers,
``generic_teams.see_every_team`` - reads them all. The wiki's list,
pages, API, search, dashboard and PDF all go through this.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from generic.teams import sees_every_team, teams_of


def wikis_of_my_teams(user: Any, wikis: QuerySet) -> QuerySet:
    if sees_every_team(user):
        return wikis

    return wikis.filter(
        Q(team_link__isnull=True)
        | Q(team_link__team__in=teams_of(user).values("pk"))
    )

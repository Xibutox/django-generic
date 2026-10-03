"""Teams: records split between groups of people (``generic.teams``).

Install the app, then name on a resource the field leading to the team:

::

    INSTALLED_APPS = [..., "generic", "generic.teams", ...]

    @register(Folder)
    class FolderResource(ModelResource):
        team_field = "team"

    @register(Document)
    class DocumentResource(ModelResource):
        team_field = "folder__team"

See ``docs/teams.md``. The helpers below import the models lazily, so
this module may be imported before the apps are ready.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "in_teams_of",
    "leaders_of",
    "scope_to_teams",
    "sees_every_team",
    "teams_of",
]


def scope_to_teams(queryset: Any, user: Any, path: str) -> Any:
    from generic.teams.scoping import scope_to_teams

    return scope_to_teams(queryset, user, path)


def teams_of(user: Any) -> Any:
    from generic.teams.scoping import teams_of

    return teams_of(user)


def leaders_of(teams: Any) -> Any:
    from generic.teams.scoping import leaders_of

    return leaders_of(teams)


def sees_every_team(user: Any) -> bool:
    from generic.teams.scoping import sees_every_team

    return sees_every_team(user)


def in_teams_of(user: Any, obj: Any, path: str) -> bool:
    from generic.teams.scoping import in_teams_of

    return in_teams_of(user, obj, path)

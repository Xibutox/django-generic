"""Which records a person reaches through their teams.

Usable anywhere - a resource, a view of a project's own, a task:

::

    from generic.teams import scope_to_teams, teams_of

    documents = scope_to_teams(Document.objects.all(), user, "folder__team")
    teams_of(user)              # the teams a select may offer

A resource says it once, ``team_field = "folder__team"``, and every
screen and endpoint of it is narrowed (``ModelResource.get_queryset``).
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import Model, QuerySet
from django.db.models.constants import LOOKUP_SEP

from generic.teams.models import SEE_EVERY_TEAM, Team


def is_member(user: Any) -> bool:
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
    )


def sees_every_team(user: Any) -> bool:
    """Superusers and holders of ``generic_teams.see_every_team``."""
    return is_member(user) and bool(user.has_perm(SEE_EVERY_TEAM))


def teams_of(user: Any) -> QuerySet:
    """The teams ``user`` works in: all of them, for who sees every team."""
    if not is_member(user):
        return Team.objects.none()

    if sees_every_team(user):
        return Team.objects.all()

    return Team.objects.filter(members=user)


def crosses_many(model: type[Model], path: str) -> bool:
    """Whether ``path`` walks a many-valued relation.

    Filtering through one would repeat a record once per team it
    reaches, so such a path is filtered through a subquery instead.
    Raises ``ImproperlyConfigured`` on a name the model does not have:
    the path is a declaration, and a typo must not read as "no rows".
    """
    if path == "pk":
        if model is not Team:
            raise ImproperlyConfigured(
                f"team_field 'pk' of {model.__name__}: only a team is "
                f"its own team."
            )

        return False

    current = model
    many = False

    for name in path.split(LOOKUP_SEP):
        try:
            field = current._meta.get_field(name)
        except FieldDoesNotExist as error:
            raise ImproperlyConfigured(
                f"team_field '{path}' of {model.__name__}: "
                f"{current.__name__} has no field '{name}'."
            ) from error

        if field.related_model is None:
            raise ImproperlyConfigured(
                f"team_field '{path}' of {model.__name__} must lead to a "
                f"team, and '{name}' is not a relation."
            )

        many = many or field.many_to_many or field.one_to_many
        current = field.related_model

    if current is not Team:
        raise ImproperlyConfigured(
            f"team_field '{path}' of {model.__name__} leads to "
            f"{current.__name__}, not to generic_teams.Team."
        )

    return many


def scope_to_teams(queryset: QuerySet, user: Any, path: str) -> QuerySet:
    """``queryset`` narrowed to the records of ``user``'s teams.

    ``path`` leads from the model to its team: ``"team"``,
    ``"folder__team"``, ``"teams"`` (a record shared by several), or
    ``"pk"`` for the teams themselves. Nobody signed in reaches nothing.
    """
    many = crosses_many(queryset.model, path)

    if not is_member(user):
        return queryset.none()

    if sees_every_team(user):
        return queryset

    lookup = {
        f"{path}{LOOKUP_SEP}in": Team.objects.filter(members=user).values("pk")
    }

    if many:
        return queryset.filter(
            pk__in=queryset.model._default_manager.filter(**lookup).values(
                "pk"
            )
        )

    return queryset.filter(**lookup)


def in_teams_of(user: Any, obj: Any, path: str) -> bool:
    """Whether ``obj`` belongs to one of ``user``'s teams."""
    if obj is None or getattr(obj, "pk", None) is None:
        return sees_every_team(user)

    queryset = type(obj)._default_manager.filter(pk=obj.pk)

    return scope_to_teams(queryset, user, path).exists()

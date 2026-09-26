"""Nobody hands out what they do not hold themselves.

Managing users is managing who may do what, so the screens that do it
are the ones where a mistake is worst. Django's own admin lets anyone
holding ``change_user`` tick *superuser*, which turns a narrow
permission into every permission; these screens refuse that, on one
rule:

    what you grant, you must already have.

So a desk supervisor who may edit accounts can add people to the groups
they are in themselves and no others, can never tick a flag they do not
carry, and can never touch a superuser - whose password they could
otherwise set and then sign in as.

A superuser is exempt, holding everything by definition. The rule is
checked on the way in, before anything is written, so a refusal names
the field and the form shows it there.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.utils.translation import gettext
from rest_framework import serializers


def codename_of(permission: Any) -> str:
    """``app.codename``, as ``has_perm`` spells it."""
    return f"{permission.content_type.app_label}.{permission.codename}"


def permissions_of(*sources: Iterable[Any]) -> set[str]:
    """Every permission these groups and permissions add up to."""
    found: set[str] = set()

    for source in sources:
        for entry in source or ():
            if hasattr(entry, "permissions"):
                found.update(
                    codename_of(permission)
                    for permission in entry.permissions.all()
                )
            else:
                found.update([codename_of(entry)])

    return found


def held_by(user: Any, instance: Any) -> set[str]:
    """What the record already grants, so only additions are checked."""
    if instance is None or instance.pk is None:
        return set()

    if hasattr(instance, "permissions"):
        return permissions_of(instance.permissions.all())

    return permissions_of(
        instance.groups.all(),
        instance.user_permissions.all(),
    )


def refuse(field: str, message: str) -> None:
    raise serializers.ValidationError({field: [message]})


def check_grant(
    actor: Any,
    field: str,
    wanted: Iterable[Any],
    already: set[str],
) -> None:
    """Refuse a grant of anything ``actor`` does not hold."""
    if actor.is_superuser:
        return

    gained = sorted(permissions_of(wanted) - already)
    missing = [name for name in gained if not actor.has_perm(name)]

    if missing:
        refuse(
            field,
            gettext(
                "You cannot grant %(permission)s, which you do not have "
                "yourself."
            )
            % {"permission": missing[0]},
        )


def check_flag(
    actor: Any,
    data: dict[str, Any],
    instance: Any,
    field: str,
    holds: bool,
) -> None:
    """Refuse turning on a flag the actor does not carry."""
    if actor.is_superuser or field not in data:
        return

    was = bool(getattr(instance, field, False)) if instance else False

    if data[field] and not was and not holds:
        refuse(
            field,
            gettext("Only an account that has this itself can grant it."),
        )


def check_user(request: Any, serializer: Any) -> None:
    """Everything the user form is not allowed to do."""
    actor = request.user
    data = serializer.validated_data
    instance = serializer.instance
    already = held_by(actor, instance)

    check_flag(actor, data, instance, "is_superuser", actor.is_superuser)
    check_flag(
        actor,
        data,
        instance,
        "is_staff",
        bool(actor.is_superuser or actor.is_staff),
    )

    if "groups" in data:
        check_grant(actor, "groups", data["groups"], already)

    if "user_permissions" in data:
        check_grant(
            actor, "user_permissions", data["user_permissions"], already
        )

    # Locking yourself out is not a change anybody meant to make, and
    # only another administrator could undo it.
    if (
        instance is not None
        and instance.pk == actor.pk
        and data.get("is_active") is False
    ):
        refuse("is_active", gettext("You cannot deactivate your own account."))


def check_group(request: Any, serializer: Any) -> None:
    """The same rule, where a group is what does the granting."""
    if "permissions" not in serializer.validated_data:
        return

    check_grant(
        request.user,
        "permissions",
        serializer.validated_data["permissions"],
        held_by(request.user, serializer.instance),
    )


def may_manage(request: Any, obj: Any) -> bool:
    """Whether ``request.user`` may edit or delete this account.

    A superuser can be edited only by a superuser: whoever may change
    an account may set its password, and therefore becomes it.
    """
    user = getattr(request, "user", None)

    if obj is None or user is None:
        return True

    return bool(user.is_superuser or not getattr(obj, "is_superuser", False))


__all__ = [
    "check_group",
    "check_user",
    "codename_of",
    "may_manage",
    "permissions_of",
]

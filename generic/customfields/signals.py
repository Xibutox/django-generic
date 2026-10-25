"""What keeps custom values in step with their records, and the
permission managing a model's fields."""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete

from generic.customfields.definitions import (
    declaration,
    enabled_resources,
    permission_codename,
)


def _dispatch_uid(resource: Any) -> str:
    return f"generic.customfields.{resource.site.name}.{resource.label_lower}"


def connect(resource: Any) -> None:
    """Delete a record's values with it - the history keeps them."""
    if declaration(resource) is None:
        return

    model = resource.model

    def deleted(sender: Any, instance: Any, **kwargs: Any) -> None:
        from generic.customfields.values import delete_values

        if instance.pk is not None:
            delete_values(model, instance.pk)

    post_delete.connect(
        deleted,
        sender=model,
        weak=False,
        dispatch_uid=_dispatch_uid(resource),
    )


def disconnect(resource: Any) -> None:
    post_delete.disconnect(
        sender=resource.model, dispatch_uid=_dispatch_uid(resource)
    )


def create_permissions(
    sender: Any = None,
    using: str = "default",
    **kwargs: Any,
) -> None:
    """``<app>.customize_<model>`` for each model open to custom fields.

    Attached to the model's own content type, it is listed beside *Can
    change* in a group's permissions. Run after every ``migrate``, like
    Django's own permissions; a resource naming a permission of its own
    (``CustomFields(permission=...)``) gets none.
    """
    if sender is not None and getattr(sender, "name", "") != "generic":
        return

    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType
    from django.db import DatabaseError

    from generic.sites import site

    wanted = []

    for resource in enabled_resources(site):
        declared = declaration(resource)

        if declared is None or declared.permission:
            continue

        wanted.append(resource.model)

    if not wanted:
        return

    manager = Permission.objects.db_manager(using)

    try:
        types = ContentType.objects.db_manager(using).get_for_models(
            *wanted, for_concrete_models=False
        )
        held = set(
            manager.filter(
                content_type__in=types.values(),
                codename__startswith="customize_",
            ).values_list("content_type", "codename")
        )
        # bulk_create, like Django's own: no post_save, so nothing is
        # published from a migrate or a test's flush.
        manager.bulk_create(
            [
                Permission(
                    content_type=types[model],
                    codename=permission_codename(model),
                    name=f"Can customize {model._meta.verbose_name_raw}"[:255],
                )
                for model in wanted
                if (types[model].pk, permission_codename(model)) not in held
            ]
        )
    except DatabaseError:  # pragma: no cover - tables not there yet
        return


__all__ = ["connect", "create_permissions", "disconnect"]

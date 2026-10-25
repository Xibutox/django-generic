"""Which custom fields a model has, and who may do what with them.

Definitions are read from the database once per request and model -
they change while the application runs, so nothing here is kept for
the life of the process. Without a request (a task, a command) they
are read each time they are asked for.
"""

from __future__ import annotations

from typing import Any

from django.db import DatabaseError
from django.utils.encoding import force_str

from generic.conf import generic_settings
from generic.customfields import CustomFields

#: Where a request keeps the definitions it read.
CACHE_ATTRIBUTE = "_generic_custom_fields"


def declaration(resource: Any) -> CustomFields | None:
    """``resource.custom_fields`` as a :class:`CustomFields`, ``None``
    when the model is not open to custom fields."""
    from django.core.exceptions import ImproperlyConfigured

    if not getattr(generic_settings, "CUSTOM_FIELDS", True):
        return None

    declared = getattr(resource, "custom_fields", False)

    if declared is True:
        return CustomFields()

    if not declared:
        return None

    if isinstance(declared, CustomFields):
        return declared

    raise ImproperlyConfigured(
        f"{type(resource).__name__}.custom_fields must be True, False or "
        f"a CustomFields(...), not {declared!r}."
    )


def is_enabled(resource: Any) -> bool:
    return declaration(resource) is not None


def permission_codename(model: Any) -> str:
    return f"customize_{model._meta.model_name}"


def permission_name(resource: Any) -> str:
    """``app.codename`` letting somebody manage the model's fields."""
    declared = declaration(resource)

    if declared is not None and declared.permission:
        return declared.permission

    model = resource.model

    return f"{model._meta.app_label}.{permission_codename(model)}"


def may_customize(resource: Any, request: Any) -> bool:
    """Whether the reader may add and change the model's fields."""
    if not is_enabled(resource):
        return False

    user = getattr(request, "user", None)

    return bool(
        user is not None
        and user.is_authenticated
        and user.has_perm(permission_name(resource))
    )


def max_fields(resource: Any) -> int:
    declared = declaration(resource)

    if declared is not None and declared.max_fields:
        return declared.max_fields

    return int(getattr(generic_settings, "CUSTOM_FIELDS_MAX_PER_MODEL", 50))


def _cache(request: Any) -> dict | None:
    if request is None:
        return None

    # A DRF request keeps what is set on it to itself; the Django one
    # under it is the same for the page and every endpoint it calls.
    target = getattr(request, "_request", request)

    try:
        return target.__dict__.setdefault(CACHE_ATTRIBUTE, {})
    except AttributeError:  # pragma: no cover - an object with no dict
        return None


def forget(request: Any) -> None:
    """Drop what ``request`` read: its definitions just changed."""
    cache = _cache(request)

    if cache is not None:
        cache.clear()


def definitions(
    resource: Any,
    request: Any = None,
    archived: bool = False,
) -> list[Any]:
    """The model's custom fields, in their order.

    The archived ones too with ``archived``: a version of the record
    may hold a value of one, and the history still names it.
    """
    if not is_enabled(resource):
        return []

    cache = _cache(request)
    key = (resource.label_lower, archived)

    if cache is not None and key in cache:
        return cache[key]

    found = read(resource.model, archived)

    if cache is not None:
        cache[key] = found

    return found


def read(model: Any, archived: bool = False) -> list[Any]:
    from django.contrib.contenttypes.models import ContentType

    from generic.customfields.models import CustomField

    try:
        content_type = ContentType.objects.get_for_model(model)
        queryset = CustomField.objects.filter(content_type=content_type)

        if not archived:
            queryset = queryset.filter(archived=False)

        return list(queryset.order_by("position", "pk"))
    except DatabaseError:
        # Before the framework's tables exist: a migrate, a check.
        return []


def holds(request: Any, permission: str) -> bool:
    user = getattr(request, "user", None)

    return bool(user is not None and user.has_perm(permission))


def hidden_names(resource: Any, request: Any) -> frozenset[str]:
    """The public names of the fields this reader may not see."""
    return frozenset(
        definition.name
        for definition in definitions(resource, request)
        if definition.view_permission
        and not holds(request, definition.view_permission)
    )


def locked_names(resource: Any, request: Any) -> frozenset[str]:
    """The public names of the fields this reader may not change."""
    return frozenset(
        definition.name
        for definition in definitions(resource, request)
        if definition.change_permission
        and not holds(request, definition.change_permission)
    )


def visible(resource: Any, request: Any, archived: bool = False) -> list:
    """The fields this reader may see."""
    hidden = {
        definition.name
        for definition in definitions(resource, request, archived)
        if definition.view_permission
        and not holds(request, definition.view_permission)
    }

    return [
        definition
        for definition in definitions(resource, request, archived)
        if definition.name not in hidden
    ]


def enabled_resources(site: Any) -> list[Any]:
    """The resources of ``site`` open to custom fields."""
    return [
        resource
        for resource in site._registry.values()
        if is_enabled(resource)
    ]


def customizable(site: Any, request: Any) -> list[Any]:
    """The resources whose fields this reader may manage."""
    return [
        resource
        for resource in enabled_resources(site)
        if may_customize(resource, request)
    ]


def resource_label(resource: Any) -> str:
    return force_str(resource.get_label_plural()).capitalize()


__all__ = [
    "customizable",
    "declaration",
    "definitions",
    "enabled_resources",
    "forget",
    "hidden_names",
    "is_enabled",
    "locked_names",
    "max_fields",
    "may_customize",
    "permission_name",
    "visible",
]

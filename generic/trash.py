"""Deleted records kept in a trash, until restored or emptied.

A resource declaring ``trash = True`` no longer deletes: *Delete* moves
the record to its trash - the record stays in its table, stamped with
when and by whom, and every screen, search, relation and endpoint of
the resource stops showing it. The resource's *Trash* page lists what
is there, to whoever may delete: *Restore* puts records back, *Delete
for good* deletes them. After ``GENERIC["TRASH_DAYS"]`` days,
:func:`empty` - the ``empty_trash`` command, the ``generic.empty_trash``
task - deletes them for good::

    from generic.trash import Trashable

    class Document(Trashable):      # deleted_at, deleted_by
        ...

    @register(Document)
    class DocumentResource(ModelResource):
        trash = True

The model needs a ``deleted_at`` field (a nullable ``DateTimeField``);
``deleted_by`` (a nullable foreign key to the user) is read when there.
``Trashable`` holds both.
"""

from __future__ import annotations

import datetime
from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

#: The query parameter of the trash's table, its actions and its facets.
TRASH_PARAM = "_trash"

#: Where a record says it was moved to the trash, and by whom.
DELETED_AT = "deleted_at"
DELETED_BY = "deleted_by"


class Trashable(models.Model):
    """The two fields a model in a trash needs."""

    deleted_at = models.DateTimeField(
        _("deleted at"), null=True, blank=True, editable=False, db_index=True
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("deleted by"),
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        abstract = True


def has_field(model: Any, name: str) -> bool:
    try:
        model._meta.get_field(name)
    except Exception:  # noqa: BLE001 - FieldDoesNotExist, whatever its kind
        return False

    return True


def is_trashed(obj: Any) -> bool:
    return getattr(obj, DELETED_AT, None) is not None


def in_trash(request: Any) -> bool:
    """Whether ``request`` is about the trash's rows rather than the
    live ones: its table, its actions."""
    params = getattr(request, "GET", None)

    return bool(params is not None and params.get(TRASH_PARAM) == "1")


def move_to_trash(obj: Any, user: Any = None) -> None:
    """Stamp ``obj`` as deleted - one save, so its history and whoever
    watches it hear of it like of any change."""
    setattr(obj, DELETED_AT, timezone.now())
    fields = [DELETED_AT]

    if has_field(type(obj), DELETED_BY):
        setattr(obj, DELETED_BY, user if getattr(user, "pk", None) else None)
        fields.append(DELETED_BY)

    if has_field(type(obj), "updated_at"):
        fields.append("updated_at")

    obj.save(update_fields=fields)


def restore(obj: Any) -> None:
    """Back from the trash, as it was."""
    setattr(obj, DELETED_AT, None)
    fields = [DELETED_AT]

    if has_field(type(obj), DELETED_BY):
        setattr(obj, DELETED_BY, None)
        fields.append(DELETED_BY)

    obj.save(update_fields=fields)


def trashed_resources(site: Any = None) -> list[Any]:
    """Every resource of ``site`` keeping a trash."""
    if site is None:
        from generic.sites import site as default_site

        site = default_site

    return [
        resource
        for resource in site.get_resources()
        if getattr(resource, "trash", False)
    ]


def empty(days: int | None = None, site: Any = None) -> int:
    """Delete for good what has been in a trash longer than ``days``.

    ``None`` reads ``GENERIC["TRASH_DAYS"]``; when that is ``None`` too,
    nothing goes. A record something protects stays, to be dealt with
    by hand. Returns how many records went.
    """
    from django.db.models import ProtectedError, RestrictedError

    from generic.conf import generic_settings

    if days is None:
        days = generic_settings.TRASH_DAYS

    if days is None:
        return 0

    cutoff = timezone.now() - datetime.timedelta(days=int(days))
    count = 0

    for resource in trashed_resources(site):
        manager = resource.model._default_manager

        for obj in manager.filter(**{f"{DELETED_AT}__lt": cutoff}):
            try:
                with transaction.atomic():
                    obj.delete()
            except (ProtectedError, RestrictedError):
                continue

            count += 1

    return count


def register_task() -> None:
    """Declare ``generic.empty_trash`` once a resource keeps a trash.

    Called from ``GenericConfig.ready()`` after every ``resources.py``:
    a project without a trash never sees the task.
    """
    from django.utils.translation import gettext

    from generic.tasks import managed_task
    from generic.tasks.registry import registry

    if not trashed_resources() or registry.get(TASK) is not None:
        return

    @managed_task(
        name=TASK,
        label=_("Empty the trash"),
        description=_(
            "Deletes for good what has been in a trash longer than "
            "GENERIC['TRASH_DAYS']. Run it once a day."
        ),
        icon="delete_sweep",
        announce=("page",),
        report=("page",),
    )
    def empty_trash(run: Any) -> str:
        count = empty()

        return gettext("%(count)s records deleted for good.") % {
            "count": count
        }


#: The task's name, for a schedule to point at.
TASK = "generic.empty_trash"


__all__ = [
    "TASK",
    "TRASH_PARAM",
    "Trashable",
    "empty",
    "in_trash",
    "is_trashed",
    "move_to_trash",
    "restore",
]

"""Who opened which record, and who downloaded which file.

A resource declaring ``access_log = True`` records, for each reader,
every opening of a record's page and every download of one of its
files - the questions an auditor asks first, which the history (what
changed) does not answer::

    @register(Contract)
    class ContractResource(ModelResource):
        access_log = True

Read on the *Access log* screen (``generic.view_accessentry``), and
from a record's page by its *Access log* button. A project records its
own accesses - a preview it serves itself - with :func:`record`::

    from generic.access import record

    record(request, contract, action="viewed", detail="preview")

``GENERIC["ACCESS_LOG_RETENTION_DAYS"]`` and :func:`prune` keep it to
a size.
"""

from __future__ import annotations

import datetime
from typing import Any

#: The same reader opening the same page again within this long is one
#: opening: a page that refreshes itself is not read twice.
QUIET = datetime.timedelta(minutes=10)


def key_of(obj: Any) -> str:
    """``app.model:pk`` - the value the screen filters a record on."""
    opts = obj._meta

    return f"{opts.app_label}.{opts.model_name}:{obj.pk}"


def address_of(request: Any) -> str | None:
    """The reader's address as the server saw it: never a header a
    client may write (``X-Forwarded-For``) - a proxy that knows better
    sets ``REMOTE_ADDR`` itself."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_ipv46_address

    meta = getattr(request, "META", None) or {}
    value = meta.get("REMOTE_ADDR") or ""

    try:
        validate_ipv46_address(value)
    except ValidationError:
        return None

    return value


def record(
    request: Any,
    obj: Any,
    *,
    action: str = "viewed",
    detail: str = "",
) -> Any:
    """Record that ``request``'s reader opened ``obj`` - or downloaded
    ``detail``, one of its files. Returns the entry, or ``None`` when
    nobody is signed in or the same opening was just recorded."""
    from django.contrib.contenttypes.models import ContentType
    from django.utils import timezone
    from django.utils.encoding import force_str

    from generic.access.models import AccessEntry

    user = getattr(request, "user", None)

    if not getattr(user, "is_authenticated", False):
        return None

    now = timezone.now()
    key = key_of(obj)

    if (
        action == AccessEntry.Action.VIEWED
        and AccessEntry.objects.filter(
            record_key=key,
            user=user,
            action=action,
            detail=detail[:255],
            at__gte=now - QUIET,
        ).exists()
    ):
        return None

    return AccessEntry.objects.create(
        content_type=ContentType.objects.get_for_model(
            obj, for_concrete_model=False
        ),
        object_id=force_str(obj.pk),
        record_key=key,
        label=force_str(obj)[:200],
        action=action,
        detail=detail[:255],
        user=user,
        user_label=(user.get_full_name() or user.get_username())[:200],
        address=address_of(request),
        at=now,
    )


def accesses_of(obj: Any) -> Any:
    """Every access recorded to ``obj``, newest first."""
    from generic.access.models import AccessEntry

    return AccessEntry.objects.filter(record_key=key_of(obj))


def prune(days: int | None = None) -> int:
    """Delete entries older than ``days`` - by default
    ``GENERIC["ACCESS_LOG_RETENTION_DAYS"]``; ``None`` keeps them all.
    Returns how many went."""
    from django.utils import timezone

    from generic.access.models import AccessEntry
    from generic.conf import generic_settings

    if days is None:
        days = generic_settings.ACCESS_LOG_RETENTION_DAYS

    if not days:
        return 0

    cutoff = timezone.now() - datetime.timedelta(days=int(days))
    deleted, _detail = AccessEntry.objects.filter(at__lt=cutoff).delete()

    return deleted


__all__ = ["QUIET", "accesses_of", "key_of", "prune", "record"]

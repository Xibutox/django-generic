"""Telling the watchers that a record changed.

Called from the same signal that already announces a change to open
tables (:mod:`generic.sites.realtime`), so there is one place where a
save becomes news and one definition of what a change is.

Two rules hold this together:

* **A watcher is told only what they could have read anyway.** The
  message repeats the record's label, so the permission to view the
  model is checked for every recipient before anything is sent. A watch
  must never become a way to learn that a record exists.
* **Telling people cannot break the save.** Everything here runs after
  the transaction commits and swallows its own failures: a mail server
  that is down must not roll back somebody's ticket.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_permission_codename
from django.contrib.contenttypes.models import ContentType
from django.utils.encoding import force_str
from django.utils.translation import gettext as _

from generic import delivery
from generic.delivery import NotificationLevel
from generic.watch.models import Watch, default_events

logger = logging.getLogger(__name__)

#: What each change is called, and how loudly.
LEVELS = {
    "created": NotificationLevel.INFO,
    "updated": NotificationLevel.INFO,
    "deleted": NotificationLevel.WARNING,
}


def sentence(change: str, label: str, model: str) -> str:
    """One line naming what happened, in the reader's language."""
    if change == "created":
        return _("%(model)s created: %(label)s") % {
            "model": model,
            "label": label,
        }

    if change == "deleted":
        return _("%(model)s deleted: %(label)s") % {
            "model": model,
            "label": label,
        }

    return _("%(model)s changed: %(label)s") % {
        "model": model,
        "label": label,
    }


def may_view(user: Any, model: Any) -> bool:
    """Whether this user holds the model's view permission.

    The model's, not the record's: object level rules live in a
    resource's ``get_queryset`` and need a request, which a signal does
    not have. A resource that restricts rows to their owner should say
    so again in ``ModelResource.may_watch``.
    """
    codename = get_permission_codename("view", model._meta)

    return bool(user.has_perm(f"{model._meta.app_label}.{codename}"))


def watchers(resource: Any, object_id: str, change: str) -> list[Watch]:
    """The watches that asked about this change to this record."""
    content_type = ContentType.objects.get_for_model(resource.model)
    found = (
        Watch.objects.filter(content_type=content_type)
        .filter(object_id__in=("", object_id))
        .select_related("user", "content_type")
    )

    return [
        watch
        for watch in found
        if watch.user.is_active
        and change in (watch.events or default_events(watch.is_whole_model))
    ]


def announce(
    resource: Any,
    obj: Any,
    change: str,
    object_id: Any = None,
) -> int:
    """Tell everyone watching ``obj`` - or its model - that it changed.

    ``object_id`` is passed in because a deletion takes it away:
    Django blanks the instance's primary key once the collector is
    done, and this runs after the commit. Whoever heard the signal
    still knows which record it was.

    Returns how many people were told, which is what the tests count.
    """
    if not getattr(resource, "watchable", True):
        return 0

    identity = force_str(
        object_id if object_id is not None else (obj.pk or "")
    )

    try:
        found = watchers(resource, identity, change)
    except Exception:  # pragma: no cover - a table that is not there yet
        logger.exception("Could not read the watches of %s", resource)

        return 0

    if not found:
        return 0

    label = force_str(resource.get_object_label(obj))[:200]
    model = force_str(resource.get_label())
    # A deleted record has no page left to point at.
    url = resource.get_detail_url(identity) if change != "deleted" else ""
    told: set[Any] = set()

    for watch in found:
        user = watch.user

        if user.pk in told or not may_view(user, resource.model):
            continue

        if not resource.may_watch(user, obj):
            continue

        told.add(user.pk)
        _tell(watch, change, label, model, url)

    return len(told)


def _tell(watch: Watch, change: str, label: str, model: str, url: str) -> None:
    try:
        delivery.deliver(
            [watch.user],
            channels=watch.resolve_channels(),
            message=lambda: (
                sentence(change, label, model),
                _("You are watching %(what)s.") % {"what": watch.target_label},
                LEVELS.get(change, NotificationLevel.INFO),
            ),
            url=url,
            # Not the record: it may be on its way out, and a
            # notification pointing at a deleted row is a broken link.
            content_object=None,
            context=f"watch {watch.pk}",
        )
    except Exception:
        # The save has already happened. Failing to talk about it is
        # not a reason to raise inside somebody else's transaction.
        logger.exception("Could not deliver watch %s", watch.pk)

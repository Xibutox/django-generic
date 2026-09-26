"""What happened to a record, and who did it.

Every registered model keeps a history: one row per version, holding
the record as it was at that point. A tab on the record's page reads it
back - what changed, who changed it and when - and the values of any
earlier version can be opened in full::

    from generic.history import acting_as, history_of

    with acting_as(user, source="Nightly import"):
        ticket.status = "closed"
        ticket.save()

    history_of(ticket)          # newest first

Two things make it work without a line of declaration:

* **A version is a snapshot, not a diff.** Each entry stores the
  record's own fields as they were. What changed is worked out when the
  history is read, by comparing an entry with the one before it, so a
  field the project starts or stops tracking never rewrites the past.
* **Who is ambient.** A signal has no request, so the acting user comes
  from the context: :class:`generic.middleware.CurrentUserMiddleware`
  sets it for the length of a request, :func:`acting_as` for a block of
  code, and nothing outside either is recorded as the system.

``ModelResource.history = False`` turns it off for one model,
``GENERIC["HISTORY"] = False`` for the whole project.
"""

from __future__ import annotations

from typing import Any

from generic.history.actor import Actor, acting_as, current_actor
from generic.history.models import HistoryEntry
from generic.history.recording import is_recorded, record


def history_of(thing: Any) -> Any:
    """Every entry kept for a record, newest first."""
    from django.contrib.contenttypes.models import ContentType
    from django.utils.encoding import force_str

    return HistoryEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(thing),
        object_id=force_str(thing.pk),
    )


def prune(days: int | None = None) -> int:
    """Delete entries older than ``days``. Returns how many went.

    ``None`` reads ``GENERIC["HISTORY_RETENTION_DAYS"]``, and keeping
    everything - the default - deletes nothing.
    """
    import datetime

    from django.utils import timezone

    from generic.conf import generic_settings

    if days is None:
        days = generic_settings.HISTORY_RETENTION_DAYS

    if not days:
        return 0

    cutoff = timezone.now() - datetime.timedelta(days=int(days))
    deleted, _detail = HistoryEntry.objects.filter(at__lt=cutoff).delete()

    return deleted


__all__ = [
    "Actor",
    "HistoryEntry",
    "acting_as",
    "current_actor",
    "history_of",
    "is_recorded",
    "prune",
    "record",
]

"""Being told when a record changes.

A user watches a record, or a whole model, and hears about it through
the channels they chose - a notification, an e-mail, or both::

    from generic.watch import Watch, watch, unwatch

    watch(user, ticket)                       # this ticket
    watch(user, Ticket)                       # every ticket
    watch(user, Ticket, events=["created"], channels=["mail"])

The messages are sent from the signal that already announces a change
to open tables, after the transaction commits, and only to people who
hold the model's view permission - a watch is never a way to learn
that a record exists.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.utils.encoding import force_str

from generic.watch.models import (
    CHANNEL_LABELS,
    EVENT_LABELS,
    EVENTS,
    Watch,
    clean_channels,
    clean_events,
    default_events,
)


def _target(thing: Any) -> tuple[Any, str, str]:
    """``(content type, object id, label)`` for a record or a model."""
    if isinstance(thing, type) and issubclass(thing, Model):
        return ContentType.objects.get_for_model(thing), "", ""

    return (
        ContentType.objects.get_for_model(thing),
        force_str(thing.pk),
        force_str(thing)[:200],
    )


def watch(
    user: Any,
    thing: Any,
    *,
    events: Iterable[str] | None = None,
    channels: Iterable[str] | None = None,
) -> Watch:
    """Start watching a record, or every record of a model."""
    content_type, object_id, label = _target(thing)
    whole_model = not object_id
    row, _created = Watch.objects.get_or_create(
        user=user,
        content_type=content_type,
        object_id=object_id,
        defaults={
            "label": label,
            "events": (
                clean_events(list(events), whole_model)
                if events is not None
                else default_events(whole_model)
            ),
            "channels": clean_channels(list(channels or [])),
        },
    )

    return row


def unwatch(user: Any, thing: Any) -> int:
    """Stop watching it. Returns how many rows went."""
    content_type, object_id, _label = _target(thing)
    deleted, _detail = Watch.objects.filter(
        user=user,
        content_type=content_type,
        object_id=object_id,
    ).delete()

    return deleted


def is_watching(user: Any, thing: Any) -> bool:
    content_type, object_id, _label = _target(thing)

    return Watch.objects.filter(
        user=user,
        content_type=content_type,
        object_id=object_id,
    ).exists()


__all__ = [
    "CHANNEL_LABELS",
    "EVENTS",
    "EVENT_LABELS",
    "Watch",
    "default_events",
    "is_watching",
    "unwatch",
    "watch",
]

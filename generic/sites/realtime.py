"""Changes to a registered model, announced to whoever is looking.

Every save and delete of a registered model publishes a
``resource.changed`` event on the model's topic. An open table
subscribed to that topic refreshes itself - whether the change came from
another user's form, a bulk action, the Django admin or a shell.

Delivery waits for the transaction to commit, so a rolled back change is
never announced. Bulk ``update()`` calls fire no signal; code doing one
should publish with :func:`announce` itself.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models.signals import post_delete, post_save
from django.utils.encoding import force_str

from generic.events.bus import Event, publish
from generic.events.registry import Topic, register_topic, registry

logger = logging.getLogger(__name__)

#: Event type the table client listens for.
EVENT_TYPE = "resource.changed"


def _dispatch_uid(resource: Any, signal: str) -> str:
    return (
        f"generic.realtime.{resource.site.name}."
        f"{resource.label_lower}.{signal}"
    )


def announce(resource: Any, change: str, pk: Any = None) -> None:
    """Tell the clients following ``resource`` that rows changed.

    ``change`` is ``created``, ``updated``, ``deleted`` or ``bulk``.
    """
    # The group is derived from the topic name rather than looked up in
    # the registry, so a test that clears the registry cannot turn an
    # ordinary save into an error.
    group = Topic(name=resource.topic_name).group_name()

    publish(
        Event(
            type=EVENT_TYPE,
            payload={
                "resource": resource.label_lower,
                "change": change,
                "id": force_str(pk) if pk is not None else None,
            },
        ),
        groups=[group],
    )


def tell_watchers(resource: Any, instance: Any, change: str) -> None:
    """Message whoever asked to hear about this record, once it sticks.

    After the commit, for the same reason the event waits: a change
    that is rolled back was never news. The primary key is read here
    rather than there because a deletion blanks it on the way out, and
    by then nothing would know which record this was.
    """
    from django.db import transaction

    if not getattr(resource, "watchable", True):
        return

    object_id = force_str(instance.pk) if instance.pk is not None else ""

    def send() -> None:
        from generic.watch.notify import announce as announce_to_watchers

        announce_to_watchers(resource, instance, change, object_id)

    transaction.on_commit(send)


def connect(resource: Any) -> None:
    """Start announcing the changes of ``resource``'s model."""
    if not resource.realtime:
        return

    registry.unregister(resource.topic_name)
    register_topic(
        resource.topic_name,
        permission=resource.topic_permission,
        description=f"Changes to {resource.opts.verbose_name_plural}.",
    )

    def saved(
        sender: Any,
        instance: Any,
        created: bool = False,
        raw: bool = False,
        **kwargs: Any,
    ) -> None:
        # A fixture being loaded is not news.
        if raw:
            return

        change = "created" if created else "updated"

        announce(resource, change, instance.pk)
        tell_watchers(resource, instance, change)

    def deleted(sender: Any, instance: Any, **kwargs: Any) -> None:
        announce(resource, "deleted", instance.pk)
        tell_watchers(resource, instance, "deleted")

    post_save.connect(
        saved,
        sender=resource.model,
        weak=False,
        dispatch_uid=_dispatch_uid(resource, "save"),
    )
    post_delete.connect(
        deleted,
        sender=resource.model,
        weak=False,
        dispatch_uid=_dispatch_uid(resource, "delete"),
    )


def disconnect(resource: Any) -> None:
    post_save.disconnect(
        sender=resource.model,
        dispatch_uid=_dispatch_uid(resource, "save"),
    )
    post_delete.disconnect(
        sender=resource.model,
        dispatch_uid=_dispatch_uid(resource, "delete"),
    )
    registry.unregister(resource.topic_name)

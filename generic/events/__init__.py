"""Real-time events and stored notifications.

Publishing::

    from generic.events import broadcast_event, publish_to_users

    publish_to_users([user], "table.changed", {"table": "tasks"})
    broadcast_event("maintenance.scheduled", {"at": "22:00"})

Declaring a topic clients may subscribe to::

    from generic.events import register_topic, allow_staff

    register_topic("audit.log", permission=allow_staff)
"""

from generic.events.bus import (
    Event,
    broadcast_event,
    broadcast_group,
    publish,
    publish_notifications,
    publish_to_topic,
    publish_to_users,
    user_group,
)
from generic.events.registry import (
    Topic,
    allow_authenticated,
    allow_staff,
    register_topic,
    registry,
)

__all__ = [
    "Event",
    "Topic",
    "allow_authenticated",
    "allow_staff",
    "broadcast_event",
    "broadcast_group",
    "publish",
    "publish_notifications",
    "publish_to_topic",
    "publish_to_users",
    "register_topic",
    "registry",
    "user_group",
]

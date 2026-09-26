"""Model discovery entry point.

The models themselves live next to the code that uses them, in
``generic.events`` and ``generic.accounts``. Django only imports
``<app>.models``, so they are re-exported here to get registered.
"""

from generic.accounts.models import SavedView, UserPreferences
from generic.events.models import (
    Message,
    Notification,
    NotificationLevel,
    NotificationManager,
    NotificationQuerySet,
)
from generic.history.models import HistoryEntry
from generic.maintenance.models import RestartAnnouncement
from generic.tasks.models import TaskRun
from generic.watch.models import Watch

__all__ = [
    "HistoryEntry",
    "Message",
    "Notification",
    "NotificationLevel",
    "NotificationManager",
    "NotificationQuerySet",
    "RestartAnnouncement",
    "SavedView",
    "TaskRun",
    "UserPreferences",
    "Watch",
]

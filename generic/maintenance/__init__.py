"""Announcing a server restart to everyone connected.

One row says what is going to happen - when, for how long, whether a
human is doing it by hand - and the framework does the rest: it warns
every connected user three times (now, a minute before, seconds before),
and, unless the operation is manual, restarts the server at the hour
that was announced.

::

    from generic.maintenance import announce_restart

    announce_restart(
        scheduled_at=when,
        duration_minutes=10,
        is_manual=False,
        comment_en="Deploying the new filters.",
        comment_fr="Deploiement des nouveaux filtres.",
        created_by=request.user,
    )
"""

from generic.maintenance.models import RestartAnnouncement
from generic.maintenance.scheduler import (
    announce_restart,
    arm_pending,
    cancel_restart,
)

__all__ = [
    "RestartAnnouncement",
    "announce_restart",
    "arm_pending",
    "cancel_restart",
]

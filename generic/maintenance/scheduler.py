"""Timing a restart: the three warnings, then the restart itself.

The timers are threads of this process, not a queue. A restart notice
lives for minutes and dies with the process it announces, so a broker
would be machinery around something that is over before it is worth
persisting - and the row survives anyway: a process coming back up arms
whatever is still pending (:func:`arm_pending`).

What each moment sends:

    announced   as soon as it is saved - a stored notification, so it
                lands in the bell and survives a reload
    reminder    a minute before (MAINTENANCE_REMINDER_SECONDS)
    imminent    seconds before (MAINTENANCE_IMMINENT_SECONDS)
    restarting  at the hour, when the operation is not manual
    cancelled   if it is called off

Every one of them is a broadcast event, so it reaches every open page
whether or not the person is looking at the bell.
"""

from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess  # nosec B404 - the command comes from the settings
import sys
import threading
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.db import connections
from django.utils import timezone

from generic.conf import generic_settings
from generic.events.bus import broadcast_event, publish_notifications
from generic.events.models import Notification, NotificationLevel
from generic.maintenance.models import RestartAnnouncement

logger = logging.getLogger(__name__)

#: Timers currently armed, by announcement id, so a cancellation can
#: take them down again.
_timers: dict[int, list[threading.Timer]] = {}
_lock = threading.Lock()


# -- publishing ---------------------------------------------------------


def _event_name(phase: str) -> str:
    return f"maintenance.{phase}"


def publish_phase(announcement: RestartAnnouncement, phase: str) -> None:
    """Tell every open page where this restart now stands."""
    broadcast_event(
        _event_name(phase),
        announcement.as_client(phase),
        # Nothing here is about a row being written, and the reminders
        # run outside any transaction.
        on_commit=False,
    )


def notify_everyone(announcement: RestartAnnouncement) -> None:
    """One stored notification per active user, in their own language.

    Stored rather than transient: someone who opens the application
    after the announcement still has to find out about it. Written in
    as many queries as there are languages in use, not as there are
    people.
    """
    by_language: dict[str, list[Any]] = {}

    for user in get_user_model()._default_manager.filter(is_active=True):
        by_language.setdefault(_language_of(user), []).append(user)

    created: list[Notification] = []

    for language, users in by_language.items():
        created.extend(
            Notification.objects.notify(
                users,
                title=_title_for(language, announcement),
                body=announcement.comment_for(language),
                level=NotificationLevel.WARNING,
            )
        )

    publish_notifications(created)


def _language_of(user: Any) -> str:
    """The language this user reads, as far as anything knows."""
    from generic.i18n import preferred_language

    return preferred_language(user) or ""


def _title_for(language: str, announcement: RestartAnnouncement) -> str:
    """The notification's own line, without a catalog lookup.

    The language is the reader's, not the announcer's, so the two
    sentences are written out rather than translated at call time.
    """
    when = timezone.localtime(announcement.scheduled_at).strftime("%H:%M")

    if str(language).lower().startswith("fr"):
        return f"Redémarrage du serveur prévu à {when}"

    return f"Server restart planned at {when}"


# -- arming -------------------------------------------------------------


def _delays(announcement: RestartAnnouncement) -> list[tuple[float, str]]:
    """``(seconds from now, phase)`` for what is still ahead."""
    remaining = announcement.seconds_until
    reminder = generic_settings.MAINTENANCE_REMINDER_SECONDS
    imminent = generic_settings.MAINTENANCE_IMMINENT_SECONDS

    moments = [
        (remaining - reminder, "reminder"),
        (remaining - imminent, "imminent"),
        (remaining, "restarting"),
    ]

    # A restart announced for two minutes' time has no hour-ahead
    # warning to give: only what is still in the future is armed.
    return [(float(delay), phase) for delay, phase in moments if delay > 0]


def schedule(announcement: RestartAnnouncement) -> None:
    """Arm the warnings, and the restart itself when it is ours to do."""
    cancel_timers(announcement.pk)

    timers = []

    for delay, phase in _delays(announcement):
        timer = threading.Timer(
            delay, _fire_in_thread, (announcement.pk, phase)
        )
        timer.daemon = True
        timer.name = f"generic-restart-{announcement.pk}-{phase}"
        timer.start()
        timers.append(timer)

    if timers:
        with _lock:
            _timers[announcement.pk] = timers


def cancel_timers(announcement_id: int) -> None:
    with _lock:
        timers = _timers.pop(announcement_id, [])

    for timer in timers:
        timer.cancel()


def _fire_in_thread(announcement_id: int, phase: str) -> None:
    """A timer's own thread: the moment, then its connections closed.

    The thread opened its own connection; leaving it around would hold
    one per warning until the process ends. Closing belongs here and
    not in :func:`_fire`, which may also run in a thread whose
    connection is somebody else's - a test's, inside its transaction.
    """
    try:
        _fire(announcement_id, phase)
    finally:
        connections.close_all()


def _fire(announcement_id: int, phase: str) -> None:
    """One moment arriving."""
    try:
        announcement = RestartAnnouncement.objects.filter(
            pk=announcement_id,
            cancelled_at__isnull=True,
        ).first()

        if announcement is None:
            return

        if phase == "restarting":
            _carry_out(announcement)
        else:
            publish_phase(announcement, phase)
    except Exception:
        # A warning that fails must not take the process down with it.
        logger.exception("Restart announcement %s failed.", announcement_id)


def _carry_out(announcement: RestartAnnouncement) -> None:
    """The announced hour, arrived."""
    if announcement.is_manual:
        # Somebody is doing it by hand: say so, touch nothing.
        publish_phase(announcement, "restarting")
        return

    RestartAnnouncement.objects.filter(pk=announcement.pk).update(
        restarted_at=timezone.now()
    )
    publish_phase(announcement, "restarting")
    restart_process()


def arm_pending() -> int:
    """Arm every announcement still ahead. Returns how many.

    Called when the process starts: the timers of the process that was
    replaced went with it, and the row is what survived.
    """
    pending = list(RestartAnnouncement.objects.pending())

    for announcement in pending:
        schedule(announcement)

    if pending:
        logger.info("Armed %s pending restart announcement(s).", len(pending))

    return len(pending)


# -- the restart itself -------------------------------------------------


def restart_process() -> None:
    """Restart this server, by whichever means this deployment has.

    In order: the command a project configured, the development
    reloader, then a plain SIGTERM - which is a restart only if
    something is watching the process, as systemd, Docker or a
    supervisor does. A project that wants none of this leaves
    ``MAINTENANCE_RESTART`` off and ticks "manual operation".
    """
    if not generic_settings.MAINTENANCE_RESTART:
        logger.warning(
            "A restart was announced but MAINTENANCE_RESTART is off; "
            "the server was left running."
        )
        return

    command = generic_settings.MAINTENANCE_RESTART_COMMAND

    if command:
        logger.warning("Restarting: running %r.", command)
        arguments = (
            shlex.split(command) if isinstance(command, str) else list(command)
        )
        subprocess.Popen(arguments)  # nosec B603 - from the settings
        return

    if _touch_for_reloader():
        return

    logger.warning("Restarting: sending SIGTERM to pid %s.", os.getpid())
    os.kill(os.getpid(), signal.SIGTERM)


def _touch_for_reloader() -> bool:
    """Nudge the development reloader, which restarts the worker for us.

    ``runserver`` watches the imported files; touching the settings
    module is the usual way of asking it for a fresh process, and it
    keeps serving throughout.
    """
    if not os.environ.get("RUN_MAIN"):
        return False

    module = sys.modules.get(os.environ.get("DJANGO_SETTINGS_MODULE", ""))
    path = getattr(module, "__file__", None)

    if not path:
        return False

    logger.warning("Restarting: touching %s for the reloader.", path)
    Path(path).touch()

    return True


# -- the public calls ---------------------------------------------------


def announce_restart(**fields: Any) -> RestartAnnouncement:
    """Save an announcement, tell everyone, and arm its warnings."""
    announcement = RestartAnnouncement.objects.create(**fields)

    notify_everyone(announcement)
    publish_phase(announcement, "announced")
    schedule(announcement)

    return announcement


def cancel_restart(announcement: RestartAnnouncement) -> RestartAnnouncement:
    """Call it off: the timers go, and every page is told."""
    announcement.cancelled_at = timezone.now()
    announcement.save(update_fields=["cancelled_at"])

    cancel_timers(announcement.pk)
    publish_phase(announcement, "cancelled")

    return announcement

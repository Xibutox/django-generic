"""What the framework keeps about people, kept only as long as asked.

Three stores grow with every day of use, and each says how long it
keeps in ``GENERIC``:

* the history of the records - ``HISTORY_RETENTION_DAYS`` (``None``:
  everything, the default - a record's history is often the evidence
  an audit asks for);
* the access log - ``ACCESS_LOG_RETENTION_DAYS`` (``None``: everything);
* the notifications - ``EVENTS_RETENTION_DAYS`` (90);
* the security events - ``SECURITY_LOG_RETENTION_DAYS`` (``None``);
* the rows a ``PersonalData`` gives a ``Retention`` - anonymized or
  deleted past it (generic.privacy).

:func:`apply` deletes what is older in each, and nothing where the
setting is ``None``. It runs as the ``apply_retention`` command - for
cron - and as the managed task ``generic.apply_retention``, to schedule
once a day from the Tasks pages::

    0 3 * * * cd /app && python manage.py apply_retention

The GDPR asks that personal data be kept no longer than needed
(storage limitation, Art. 5(1)(e)); the CNIL recommends six months to
a year for an access log. See docs/history.md#retention.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

#: The task's name, for a schedule to point at.
TASK = "generic.apply_retention"


def prune_notifications(days: int | None = None) -> int:
    """Delete notifications older than ``days`` - by default
    ``GENERIC["EVENTS_RETENTION_DAYS"]``; ``None`` keeps them all.
    Returns how many went."""
    from django.utils import timezone

    from generic.conf import generic_settings
    from generic.events.models import Notification

    if days is None:
        days = generic_settings.EVENTS_RETENTION_DAYS

    if not days:
        return 0

    cutoff = timezone.now() - datetime.timedelta(days=int(days))
    deleted, _detail = Notification.objects.filter(
        created_at__lt=cutoff
    ).delete()

    return deleted


def apply() -> dict[str, int]:
    """Apply every retention. Returns how many entries went, by store."""
    from generic import access, audit, history, privacy

    deleted = {
        "history": history.prune(),
        "access_log": access.prune(),
        "notifications": prune_notifications(),
        "security_log": audit.prune(),
        "personal_data": sum(privacy.apply_retention().values()),
    }

    if any(deleted.values()):
        # The deletion of evidence is itself worth a line in the log.
        logger.info(
            "Retention applied: %(history)s history entries, "
            "%(access_log)s access log entries, %(notifications)s "
            "notifications, %(security_log)s security events deleted; "
            "%(personal_data)s records past their personal data "
            "retention anonymized or deleted.",
            deleted,
        )

    return deleted


def register_task() -> None:
    """Declare ``generic.apply_retention``, once.

    Called from ``GenericConfig.ready()``: the task is always there to
    be scheduled, and does nothing while every retention is ``None``.
    """
    from django.utils.translation import gettext

    from generic.tasks import managed_task
    from generic.tasks.registry import registry

    if registry.get(TASK) is not None:
        return

    @managed_task(
        name=TASK,
        label=_("Apply the retention periods"),
        description=_(
            "Deletes the history, access log, notifications and "
            "security events older than GENERIC's *_RETENTION_DAYS, "
            "and anonymizes or deletes the personal data past its "
            "declared retention. Run it once a day."
        ),
        icon="auto_delete",
        announce=("page",),
        report=("page",),
    )
    def apply_retention(run: Any) -> str:
        deleted = apply()

        return (
            gettext(
                "%(history)s history entries, %(access_log)s access log "
                "entries, %(notifications)s notifications and "
                "%(security_log)s security events deleted; "
                "%(personal_data)s records past their personal data "
                "retention anonymized or deleted."
            )
            % deleted
        )


__all__ = ["TASK", "apply", "prune_notifications", "register_task"]

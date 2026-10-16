"""``manage.py apply_retention``: the history, access log and
notifications older than their retention, deleted - for cron, where no
Celery beat runs::

    0 3 * * * cd /app && python manage.py apply_retention
"""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Delete the history, access log and notifications older than "
        "GENERIC's HISTORY_RETENTION_DAYS, ACCESS_LOG_RETENTION_DAYS "
        "and EVENTS_RETENTION_DAYS. None keeps everything."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        from generic.retention import apply

        deleted = apply()
        self.stdout.write(
            f"{deleted['history']} history entr(y/ies), "
            f"{deleted['access_log']} access log entr(y/ies), "
            f"{deleted['notifications']} notification(s), "
            f"{deleted['security_log']} security event(s) deleted."
        )

"""``manage.py send_scheduled_mailings``: the dispatcher, for cron.

Where no Celery beat runs, a crontab line does the same::

    */5 * * * * cd /app && python manage.py send_scheduled_mailings
"""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send every scheduled mailing whose time has come."

    def handle(self, *args: Any, **options: Any) -> None:
        from generic.mailings.dispatch import dispatch

        count = dispatch()
        self.stdout.write(f"{count} mailing(s) sent.")

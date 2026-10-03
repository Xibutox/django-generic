"""``manage.py run_periodic_reviews``: the periodic reviews of the day,
for cron where no Celery beat runs::

    0 7 * * * cd /app && python manage.py run_periodic_reviews
"""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Remind the authors of the documents due for a review, and start "
        "the reviews due today."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        from documents import periodic

        self.stdout.write(periodic.run().describe())

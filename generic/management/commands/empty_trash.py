"""``manage.py empty_trash``: what has been in a trash too long, deleted
for good - for cron, where no Celery beat runs::

    0 3 * * * cd /app && python manage.py empty_trash
"""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Delete for good the records that have been in a trash longer "
        "than GENERIC['TRASH_DAYS'] days."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Days in the trash, instead of GENERIC['TRASH_DAYS'].",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from generic.trash import empty

        count = empty(options["days"])
        self.stdout.write(f"{count} record(s) deleted for good.")

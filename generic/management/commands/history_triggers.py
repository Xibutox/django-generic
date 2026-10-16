"""``manage.py history_triggers``: the history's PostgreSQL triggers
installed (or brought up to date, or removed) now, rather than at the
next ``migrate`` - or their SQL printed, for a database administrator
to read or apply::

    python manage.py history_triggers
    python manage.py history_triggers --sql > history_triggers.sql
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Install the triggers that record, in the history, the rows "
        "written outside the application (PostgreSQL)."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--database", default="default")
        parser.add_argument(
            "--sql",
            action="store_true",
            help="Print the SQL instead of running it.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from django.db import connections

        from generic.history import triggers

        connection = connections[options["database"]]

        if connection.vendor != "postgresql":
            raise CommandError(
                "The history's triggers are PostgreSQL's: this database "
                f"is {connection.vendor}."
            )

        if options["sql"]:
            self.stdout.write(triggers.ISO_FUNCTION)

            for resource in triggers.recorded_resources():
                self.stdout.write(triggers.trigger_sql(connection, resource))

            return

        triggers.install(connection, verbosity=options["verbosity"])

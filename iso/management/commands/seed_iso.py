"""Fill the installed ISO apps with demo data.

Creates five demo accounts - ``ciso``, ``it``, ``auditor``, ``dev``,
``sales`` - sharing the password given (``demo`` by default), and two
groups: *Security officers* (every ISO permission) and *Auditors*
(read everything, record audits). Throwaway local accounts: never run
it against a production database.

The policies get the documents shipped in ``iso/documents/`` - access
control, logging, backups, changes, incidents, vulnerabilities - in
English, or in French with ``--language fr``.

Running it again tops up what is missing and leaves the rest alone.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import translation

from iso import demo


class Command(BaseCommand):
    help = "Fill the installed ISO 27001 apps with demo data."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--password",
            default="demo",
            help="Password for new demo accounts (default: demo).",
        )
        parser.add_argument(
            "--language",
            default=None,
            help=(
                "Language of the policies' documents: en or fr "
                "(default: LANGUAGE_CODE)."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        language = options["language"] or settings.LANGUAGE_CODE
        with translation.override(language), transaction.atomic():
            users = demo.create_users(options["password"])
            records = demo.seed(users)
        apps = sorted({key.split(".")[0] for key in records})
        self.stdout.write(
            self.style.SUCCESS(
                "ISO demo data ready: " + ", ".join(apps) + ". "
                "Accounts: " + ", ".join(sorted(users)) + "."
            )
        )

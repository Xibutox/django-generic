"""``manage.py extract_text``: read the text of the versions that have
none yet - files sent before the search read inside them, or before
``pypdf`` was installed. ``--all`` reads every version again."""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Read the text of the documents' files, for the search."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--all",
            action="store_true",
            help="Every version, not only those without text.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from documents.versions import fill_text

        count = fill_text(everything=options["all"])
        self.stdout.write(f"{count} version(s) read.")

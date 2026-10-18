"""``manage.py wiki_import``: a new wiki from an archive that
``wiki_export`` or a wiki's *Export* button wrote, here or on another
site::

    python manage.py wiki_import handbook.zip
    python manage.py wiki_import handbook.zip --name "Handbook (2026)"
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Make a new wiki from a wiki archive (a zip with wiki.json)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("archive", help="The archive's path.")
        parser.add_argument(
            "--name",
            default="",
            help="The new wiki's name; by default the archive's.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from generic.wiki.archive import ArchiveError, import_archive

        try:
            with open(options["archive"], "rb") as source:
                result = import_archive(source, name=options["name"])
        except OSError as error:
            raise CommandError(str(error)) from error
        except ArchiveError as error:
            raise CommandError(str(error)) from error

        for skipped in result.skipped:
            self.stderr.write(f"Left out: {skipped}")

        self.stdout.write(
            self.style.SUCCESS(
                f"{result.wiki.name} ({result.wiki.get_absolute_url()}): "
                f"{result.pages} pages, {result.images} images, "
                f"{result.files} files."
            )
        )

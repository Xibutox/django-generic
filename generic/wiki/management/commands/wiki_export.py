"""``manage.py wiki_export``: a wiki as an archive, the same as its
*Export* button gives, for a script or a backup::

    python manage.py wiki_export handbook
    python manage.py wiki_export handbook --output /backups/handbook.zip
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Write a wiki - its pages, images and files - as a zip that "
        "wiki_import, or a wiki's Import button, reads."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("wiki", help="The wiki's address.")
        parser.add_argument(
            "--output",
            "-o",
            default=None,
            help="Where to write it; by default <address>.zip here.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from generic.wiki.archive import archive_name, write_archive
        from generic.wiki.models import Wiki

        wiki = Wiki.objects.filter(slug=options["wiki"]).first()

        if wiki is None:
            raise CommandError(f"No wiki at {options['wiki']!r}.")

        path = options["output"] or archive_name(wiki)

        with open(path, "wb") as output:
            manifest = write_archive(wiki, output)

        self.stdout.write(
            self.style.SUCCESS(
                f"{path}: {len(manifest['pages'])} pages, "
                f"{len(manifest['images'])} images, "
                f"{len(manifest['files'])} files."
            )
        )

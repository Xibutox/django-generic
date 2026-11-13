"""``manage.py wiki_cleanup``: what the wiki no longer needs.

* The pages and wikis in the trash for more than ``--days`` days
  (``GENERIC["TRASH_DAYS"]``) are deleted for good.
* With ``--uploads``, the images and files no page shows - nor any
  version of one, nor a page in the trash - uploaded more than
  ``--upload-days`` days ago, are deleted with what they stored.

Run it once a day; ``--dry-run`` counts without deleting.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from generic.conf import generic_settings
from generic.wiki.models import (
    Wiki,
    WikiFile,
    WikiImage,
    WikiPage,
    WikiRevision,
    _address_pattern,
)

#: Days an upload no page shows is kept: a writer may still be in the
#: editor it was uploaded from.
UPLOAD_DAYS = 7


def shown() -> dict[str, set[int]]:
    """The ids of the uploads some text holds - a page, live or in the
    trash, or a version of one."""
    kinds = ("image", "file")
    pattern = re.compile(
        r"""(?:src|href)=["'](?:%s)["']"""
        % "|".join(_address_pattern(kind) for kind in kinds)
    )
    found: dict[str, set[int]] = {kind: set() for kind in kinds}
    texts = (
        WikiPage.all_objects.exclude(content="").values_list(
            "content", flat=True
        ),
        WikiRevision.objects.exclude(content="").values_list(
            "content", flat=True
        ),
    )

    for rows in texts:
        for content in rows.iterator():
            for match in pattern.finditer(content):
                kind = "image" if match.group("image") else "file"
                found[kind].add(int(match.group(kind)))

    return found


class Command(BaseCommand):
    help = (
        "Empty the wiki's trash after GENERIC['TRASH_DAYS'] days and, "
        "with --uploads, delete the images and files no page shows."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Days in the trash (default: GENERIC['TRASH_DAYS']).",
        )
        parser.add_argument(
            "--uploads",
            action="store_true",
            help="Also delete the images and files no page shows.",
        )
        parser.add_argument(
            "--upload-days",
            type=int,
            default=UPLOAD_DAYS,
            help=f"Days an unused upload is kept (default: {UPLOAD_DAYS}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count what would be deleted, and delete nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry = options["dry_run"]
        days = options["days"]

        if days is None:
            days = generic_settings.TRASH_DAYS

        pages = wikis = 0

        if days is not None:
            before = timezone.now() - datetime.timedelta(days=days)
            old_wikis = Wiki.all_objects.filter(deleted_at__lt=before)
            old_pages = WikiPage.all_objects.filter(
                deleted_at__lt=before
            ).exclude(wiki__in=old_wikis)
            wikis = old_wikis.count()
            pages = old_pages.count()

            if not dry:
                old_pages.delete()
                old_wikis.delete()

        self.stdout.write(
            f"Trash: {pages} pages, {wikis} wikis "
            f"{'to delete' if dry else 'deleted'}."
        )

        if not options["uploads"]:
            return

        used = shown()
        before = timezone.now() - datetime.timedelta(
            days=options["upload_days"]
        )
        count = 0

        for kind, model in (("image", WikiImage), ("file", WikiFile)):
            unused = model.objects.filter(uploaded_at__lt=before).exclude(
                pk__in=used[kind]
            )

            for upload in unused.iterator():
                count += 1

                if dry:
                    continue

                # The row first: a file left behind is only space, a
                # row without its file a broken page.
                stored = upload.file
                storage, name = stored.storage, stored.name
                upload.delete()

                if name:
                    try:
                        storage.delete(name)
                    except Exception:  # noqa: BLE001 - any storage
                        self.stderr.write(f"Could not delete {name}.")

        self.stdout.write(
            f"Uploads: {count} unused {'to delete' if dry else 'deleted'}."
        )

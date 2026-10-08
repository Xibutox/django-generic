"""``manage.py wiki_user_guide``: the user guide put in a wiki - again
after it was deleted, in another wiki, or brought up to date after an
upgrade of the framework::

    python manage.py wiki_user_guide --update
    python manage.py wiki_user_guide --wiki handbook --language fr
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Put the user guide in a wiki, one page per language of the "
        "site it is written in."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--wiki",
            default=None,
            help="The wiki's address; by default the first wiki.",
        )
        parser.add_argument(
            "--language",
            action="append",
            dest="languages",
            default=None,
            help="A language (en, fr); repeat for several. By default "
            "those of LANGUAGES the guide is written in.",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Replace the text of a guide already there; the "
            "replaced version stays in the page's history.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from generic.wiki.guide import GUIDES, install_user_guide
        from generic.wiki.models import Wiki

        wiki = None

        if options["wiki"]:
            wiki = Wiki.objects.filter(slug=options["wiki"]).first()

            if wiki is None:
                raise CommandError(f"No wiki at {options['wiki']!r}.")

        unknown = sorted(set(options["languages"] or ()) - set(GUIDES))

        if unknown:
            raise CommandError(
                f"The guide is not written in {', '.join(unknown)}: "
                f"{', '.join(GUIDES)} only."
            )

        done = install_user_guide(
            wiki=wiki,
            languages=options["languages"],
            update=options["update"],
        )

        for state, pages in done.items():
            for page in pages:
                self.stdout.write(
                    f"{state}: {page.wiki.name} > {page.title} "
                    f"({page.get_absolute_url()})"
                )

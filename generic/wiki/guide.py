"""The user guide: a wiki page every installation starts with.

What every screen of an application built on the framework lets its
readers do - find their way, filter a list, open, add, change and
delete a record - written once for all of them, in the languages the
framework ships (``guide/<language>.html``). The migration that adds it
(``0007_user_guide``) and ``manage.py wiki_user_guide`` both go
through :func:`install_user_guide`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings

from generic.wiki.sanitize import clean_html

GUIDE_DIR = Path(__file__).resolve().parent / "guide"

#: Each language the guide is written in: its page's title and address.
GUIDES = {
    "en": ("User guide", "user-guide"),
    "fr": ("Guide utilisateur", "guide-utilisateur"),
}

#: The guide's addresses, whatever the language.
GUIDE_SLUGS = frozenset(slug for _title, slug in GUIDES.values())

#: After the pages a project writes itself, in the menu.
GUIDE_POSITION = 1000


def guide_languages(languages: Any = None) -> list[str]:
    """The guide's languages among ``languages`` - by default the
    site's ``LANGUAGES`` - in their order; English when none is."""
    if languages is None:
        languages = [code for code, _name in settings.LANGUAGES]

    found = []

    for code in languages:
        base = str(code).lower().replace("_", "-").split("-")[0]

        if base in GUIDES and base not in found:
            found.append(base)

    return found or ["en"]


def guide_content(language: str) -> str:
    """The guide's text in ``language``, as the wiki stores it."""
    return clean_html((GUIDE_DIR / f"{language}.html").read_text("utf-8"))


def install_user_guide(
    wiki: Any = None,
    languages: Any = None,
    update: bool = False,
    wiki_model: Any = None,
    page_model: Any = None,
) -> dict[str, list[Any]]:
    """Put the guide in ``wiki`` - by default the first one, made when
    there is none - one page per language.

    A page already at the guide's address is left alone, unless
    ``update``: then its title and text become the guide's, the version
    it held kept in its history. ``wiki_model`` and ``page_model`` are
    a migration's historical models; left out, the app's own.

    Returns the pages ``{"created": [...], "updated": [...],
    "skipped": [...]}``.
    """
    # The app's own models keep a version of the text an update
    # replaces; a migration's historical ones have no ``keep``.
    keeps_revisions = wiki_model is None or page_model is None

    if keeps_revisions:
        from generic.wiki.models import Wiki, WikiPage

        wiki_model, page_model = Wiki, WikiPage

    if wiki is None:
        wiki = wiki_model.objects.order_by("position", "name", "pk").first()

    if wiki is None:
        wiki, _created = wiki_model.objects.get_or_create(
            slug="main", defaults={"name": "Wiki"}
        )

    done: dict[str, list[Any]] = {"created": [], "updated": [], "skipped": []}

    for language in guide_languages(languages):
        title, slug = GUIDES[language]
        content = guide_content(language)
        page = page_model.objects.filter(wiki=wiki, slug=slug).first()

        if page is None:
            page = page_model.objects.create(
                wiki=wiki,
                title=title,
                slug=slug,
                content=content,
                position=GUIDE_POSITION,
            )
            done["created"].append(page)
        elif update and (page.title, page.content) != (title, content):
            if keeps_revisions:
                from generic.wiki.models import WikiRevision

                WikiRevision.keep(page)

            page.title, page.content = title, content
            page.save()
            done["updated"].append(page)
        else:
            done["skipped"].append(page)

    return done

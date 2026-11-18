"""A wiki's public link: its pages, read-only, for anyone holding it.

Off unless the project says ``GENERIC["WIKI_PUBLIC_LINKS"] = True``.
Then whoever manages a wiki may give it a link (``POST
wikis/<id>/share/``), make a new one - the old one stops working - or
take it away (``DELETE``). The link is ``wiki/shared/<secret>/``: the
wiki's first page; ``wiki/shared/<secret>/<page>/`` each page.

What it shows is what a reader sees, nothing more: the live pages, no
history, no trash, no editor, no search across wikis. The links between
the pages lead to their shared addresses; the images and files they
show are served from under the link too, and only those - an upload no
live page of the wiki shows is not reached through it. The pages are
never indexed (``X-Robots-Tag``) and never tell another site their
address (``Referrer-Policy``).
"""

from __future__ import annotations

import re
import secrets
from typing import Any

from django.urls import reverse

from generic.conf import generic_settings
from generic.wiki.models import Wiki, WikiPage


def enabled() -> bool:
    return bool(generic_settings.WIKI_PUBLIC_LINKS)


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def shared_wiki(secret: str) -> Wiki | None:
    """The wiki shared under ``secret``: none when sharing is off, the
    link was replaced or the wiki is in the trash."""
    if not enabled() or not secret or len(secret) > 64:
        return None

    return Wiki.objects.filter(share_token=secret).first()


def link_of(wiki: Wiki, slug: str = "") -> str:
    """The shared address of ``wiki``, or of one of its pages."""
    if slug:
        return reverse(
            "generic_wiki:shared-page",
            kwargs={"secret": wiki.share_token, "slug": slug},
        )

    return reverse("generic_wiki:shared", kwargs={"secret": wiki.share_token})


def _prefix(name: str, **kwargs: Any) -> str:
    """A route's address up to its last argument, which is ``0``."""
    return reverse(name, kwargs=kwargs).rsplit("/0/", 1)[0] + "/"


def rewrite(html: str, wiki: Wiki) -> str:
    """``html``, its links to the wiki's pages and to its images and
    files led to their shared addresses. Links to other wikis stay as
    they are: their readers sign in."""
    secret = wiki.share_token
    page = re.escape(_prefix("generic_wiki:page", wiki=wiki.slug, slug=0))
    shared_page = _prefix("generic_wiki:shared-page", secret=secret, slug=0)
    image = re.escape(_prefix("generic_wiki:image", pk=0))
    file = re.escape(_prefix("generic_wiki:file", pk=0))
    shared_image = _prefix("generic_wiki:shared-image", secret=secret, pk=0)
    shared_file = _prefix("generic_wiki:shared-file", secret=secret, pk=0)

    html = re.sub(
        rf'(href=")(?:https?://[^/"]+)?{page}', rf"\g<1>{shared_page}", html
    )
    html = re.sub(
        rf'((?:src|href)=")(?:https?://[^/"]+)?{image}(\d+/)',
        rf"\g<1>{shared_image}\g<2>",
        html,
    )

    return re.sub(
        rf'(href=")(?:https?://[^/"]+)?{file}(\d+/)',
        rf"\g<1>{shared_file}\g<2>",
        html,
    )


def shows(wiki: Wiki, upload: Any) -> bool:
    """Whether a live page of ``wiki`` shows ``upload``."""
    return WikiPage.objects.filter(
        wiki=wiki, content__contains=upload.get_absolute_url()
    ).exists()

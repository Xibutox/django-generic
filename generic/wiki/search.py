"""Searching the wikis' pages by their words, not by their HTML.

A page's ``text`` holds its words (``WikiPage.save``): ``<strong>`` does
not match "strong", a class name matches nothing. Every word of the
search must be in the title or the text - accents set aside where
``generic.search`` is installed - and each page found comes with an
excerpt of its text around the first word found::

    found = search_pages_of(user, "escalate customer", wiki=handbook)
    # [{"page": <WikiPage>, "excerpt": [("... the ", False),
    #   ("escalate", True), (" to ...", False)]}, ...]

The excerpt is runs of text, each marked or not: the template writes
them escaped, never as HTML.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from django.db.models import Case, IntegerField, Q, Value, When

from generic.search import text_lookup
from generic.wiki.models import Wiki, WikiPage

#: Characters of text kept around the word found.
EXCERPT = 90

#: Pages a search answers, at most.
LIMIT = 50


def fold(text: str) -> str:
    """``text`` lower-cased and without accents, character for
    character - an index in it is an index in ``text``."""
    folded = []

    for character in text:
        bare = unicodedata.normalize("NFKD", character)
        bare = "".join(c for c in bare if not unicodedata.combining(c))
        # One character for one: a ligature keeps its place.
        folded.append((bare[:1] or character).lower())

    return "".join(folded)


def words_of(term: str) -> list[str]:
    return [word for word in term.split() if word][:10]


def excerpt(text: str, words: list[str]) -> list[tuple[str, bool]]:
    """A piece of ``text`` around the first of ``words`` it holds, as
    runs of text, the words found marked."""
    flat = " ".join(text.split())
    folded = fold(flat)
    targets = [fold(word) for word in words]
    hits = [
        (folded.find(target), target)
        for target in targets
        if target and folded.find(target) != -1
    ]

    if hits:
        first = min(index for index, _target in hits)
        start = max(0, first - EXCERPT // 2)
    else:
        start = 0

    end = min(len(flat), start + EXCERPT * 2)

    # Whole words at both ends.
    if start:
        space = flat.find(" ", start)
        start = space + 1 if 0 <= space < start + 20 else start

    if end < len(flat):
        space = flat.rfind(" ", start, end)
        end = space if space > start else end

    marks = [False] * (end - start)

    for target in {target for _index, target in hits}:
        index = folded.find(target, start)

        while 0 <= index < end:
            for position in range(index, min(index + len(target), end)):
                marks[position - start] = True

            index = folded.find(target, index + len(target))

    runs: list[tuple[str, bool]] = []

    if start:
        runs.append(("… ", False))

    for offset, character in enumerate(flat[start:end]):
        marked = marks[offset]

        if runs and runs[-1][1] == marked and runs[-1][0] != "… ":
            runs[-1] = (runs[-1][0] + character, marked)
        else:
            runs.append((character, marked))

    if end < len(flat):
        runs.append((" …", False))

    return runs


def search_pages_of(
    user: Any, term: str, wiki: Wiki | None = None, limit: int = LIMIT
) -> list[dict[str, Any]]:
    """The pages ``user`` reads holding every word of ``term`` - in
    ``wiki``, or in every wiki - those whose title holds them first."""
    words = words_of(term)

    if not words:
        return []

    pages = WikiPage.objects.filter(wiki__in=Wiki.objects.readable_by(user))

    if wiki is not None:
        pages = pages.filter(wiki=wiki)

    in_title = Q()

    for word in words:
        pages = pages.filter(
            Q(**{text_lookup("title"): word})
            | Q(**{text_lookup("text"): word})
        )
        in_title &= Q(**{text_lookup("title"): word})

    pages = (
        pages.select_related("wiki", "updated_by")
        .annotate(
            in_title=Case(
                When(in_title, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("in_title", "wiki__position", "wiki__name", "title")
    )[:limit]

    return [
        {"page": page, "excerpt": excerpt(page.text, words)} for page in pages
    ]

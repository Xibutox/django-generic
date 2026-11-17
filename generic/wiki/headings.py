"""A page's headings: an anchor each, and the table of contents.

The anchors are given when a page is shown, never stored: the cleaning
(``sanitize.py``) keeps no ``id`` - a pasted one could take an id the
application uses - and each anchor is made here, from the heading's
text, with a prefix of its own (``h-``), unique in the page::

    html, contents = with_anchors(safe_html(page.content))
    # <h2 id="h-escalating">Escalating</h2> ...
    # [{"id": "h-escalating", "text": "Escalating", "level": 2}, ...]

A link to ``#h-escalating`` - from the same page, or another one with
the page's address before it - goes to that heading.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

from django.utils.html import strip_tags
from django.utils.safestring import SafeString, mark_safe
from django.utils.text import slugify

#: The prefix every anchor starts with.
PREFIX = "h-"

#: A heading as the cleaning leaves it: the tag, at most its class.
_HEADING = re.compile(
    r'<(?P<tag>h[1-4])(?P<attrs>(?: class="[^"<>]*")?)>'
    r"(?P<body>.*?)</(?P=tag)>",
    re.DOTALL,
)

#: Headings a page needs before it shows a table of contents.
CONTENTS_MIN = 3


def anchor(text: str, taken: set[str]) -> str:
    """An anchor for ``text`` no other heading of the page has."""
    base = PREFIX + (slugify(text, allow_unicode=True)[:60] or "section")
    found = base
    index = 2

    while found in taken:
        found = f"{base}-{index}"
        index += 1

    taken.add(found)

    return found


def with_anchors(html: str) -> tuple[SafeString, list[dict[str, Any]]]:
    """``html`` - cleaned already - with an ``id`` on each heading, and
    its headings in order: ``{"id", "text", "level"}``."""
    taken: set[str] = set()
    contents: list[dict[str, Any]] = []

    def give(match: re.Match) -> str:
        text = " ".join(unescape(strip_tags(match["body"])).split())

        if not text:
            return match[0]

        found = anchor(text, taken)
        contents.append(
            {"id": found, "text": text, "level": int(match["tag"][1])}
        )

        return (
            f'<{match["tag"]} id="{found}"{match["attrs"]}>'
            f'{match["body"]}</{match["tag"]}>'
        )

    # The slug holds letters, digits, "-" and "_" only: nothing in an
    # id needs escaping.
    marked = _HEADING.sub(give, str(html))

    return mark_safe(marked), contents  # nosec B308 B703 - cleaned before


def table_of_contents(contents: list[dict[str, Any]]) -> list[dict]:
    """The headings worth a table of contents - none for a short page -
    each with its ``depth`` under the page's highest level."""
    if len(contents) < CONTENTS_MIN:
        return []

    top = min(entry["level"] for entry in contents)

    return [{**entry, "depth": entry["level"] - top} for entry in contents]

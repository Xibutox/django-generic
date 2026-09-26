"""Accent-insensitive search: ``societe`` finds *Société*.

An optional app. Installed (``"generic.search"`` in ``INSTALLED_APPS``),
every text match the framework makes - the table search, the column
filters, the filter editor's value search, the command palette, the
autocompletes, the classic list views, the wiki - ignores accents as
well as case. Not installed, every match is what it always was.

The folding happens in the database, so a search still runs where the
rows are: PostgreSQL through the ``unaccent`` extension (created by this
app's migration, behind an ``IMMUTABLE`` wrapper an index can use),
SQLite through a Python function registered on each connection, so
development and the tests behave as production does. Other databases
are left alone: their collations usually ignore accents already.

Rows that are not in a database - a ``DataResource``'s - are folded in
Python by :func:`fold`, which follows the same rules.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from django.apps import apps as registry

#: The name of the SQL function, on PostgreSQL and on SQLite alike.
FUNCTION = "generic_unaccent"

#: The transform's lookup name: ``title__unaccented__icontains``.
TRANSFORM = "unaccented"

#: Letters Unicode does not decompose into a base letter and an accent,
#: spelled out as PostgreSQL's ``unaccent`` rules spell them.
LETTERS = str.maketrans(
    {
        "œ": "oe",
        "Œ": "OE",
        "æ": "ae",
        "Æ": "AE",
        "ß": "ss",
        "ẞ": "SS",
        "ø": "o",
        "Ø": "O",
        "đ": "d",
        "Đ": "D",
        "ł": "l",
        "Ł": "L",
        "ı": "i",
        "ð": "d",
        "Ð": "D",
        "þ": "th",
        "Þ": "TH",
    }
)


def is_enabled() -> bool:
    """Whether the project installed the app, and so asked for it."""
    return registry.is_installed("generic.search")


def fold(value: Any) -> Any:
    """``value`` without its accents: ``Société`` -> ``Societe``.

    ``None`` stays ``None``, which is what an SQL function does with a
    ``NULL``; anything else is read as its text first.
    """
    if value is None:
        return None

    text = str(value).translate(LETTERS)

    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def normalize(value: Any) -> str:
    """What a text comparison in Python compares: case, and accents
    when the app is installed, set aside."""
    text = "" if value is None else str(value)

    return (fold(text) if is_enabled() else text).casefold()


def text_lookup(path: str, lookup: str = "icontains") -> str:
    """The keyword a text match on ``path`` filters with.

    ``text_lookup("title")`` is ``title__unaccented__icontains`` when
    the app is installed, ``title__icontains`` when it is not - one
    place deciding, so every search agrees with every other.
    """
    if is_enabled():
        return f"{path}__{TRANSFORM}__{lookup}"

    return f"{path}__{lookup}"

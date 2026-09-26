"""Best match first, for the command palette and the autocompletes.

A table keeps the order its reader chose. A short list of suggestions
has no such order to keep, and there the closest match belongs on top:
``word_similarity`` from ``pg_trgm`` scores how well the typed text
matches a word of each search field, accents set aside, and the best
score of a row sorts it.
"""

from __future__ import annotations

from typing import Sequence

from django.contrib.admin.utils import lookup_spawns_duplicates
from django.db import connections
from django.db.models import F, FloatField, Func, QuerySet, Value
from django.db.models.functions import Coalesce, Greatest

from generic.search import is_enabled

#: The annotation carrying the score.
RANK = "generic_search_rank"


def can_rank(queryset: QuerySet) -> bool:
    """Only PostgreSQL has ``pg_trgm``, and only the app installs it."""
    return is_enabled() and connections[queryset.db].vendor == "postgresql"


def rank(queryset: QuerySet, fields: Sequence[str], text: str) -> QuerySet:
    """``queryset`` ordered by how closely ``fields`` match ``text``.

    Fields crossing a many-valued relation are left out of the score:
    annotating through them would list a row once per related value.
    The previous ordering breaks ties.
    """
    text = (text or "").strip()

    if not text or not can_rank(queryset):
        return queryset

    from generic.search.lookups import Unaccented

    options = queryset.model._meta
    scores = [
        Coalesce(
            Func(
                Unaccented(Value(text)),
                Unaccented(F(field)),
                function="word_similarity",
                output_field=FloatField(),
            ),
            Value(0.0),
        )
        for field in fields
        if not lookup_spawns_duplicates(options, field)
    ]

    if not scores:
        return queryset

    score = scores[0] if len(scores) == 1 else Greatest(*scores)
    ordering = list(queryset.query.order_by or options.ordering or ("pk",))

    return queryset.annotate(**{RANK: score}).order_by(f"-{RANK}", *ordering)

"""The ``unaccented`` transform, compiled for each database."""

from __future__ import annotations

from typing import Any

from django.db.models import TextField, Transform

from generic.search import FUNCTION, TRANSFORM


class Unaccented(Transform):
    """A value without its accents, on both sides of the lookup.

    ``bilateral`` folds the searched text as well as the column, so
    ``Société`` typed in the box finds ``Societe`` stored, and the other
    way round.

    The result is text whatever went in: a search may name a number or
    a relation, and ``icontains`` on those already compares their text.
    """

    lookup_name = TRANSFORM
    bilateral = True
    output_field = TextField()

    def as_sql(self, compiler: Any, connection: Any, **extra: Any) -> Any:
        # Databases with no such function: their collation decides, as
        # it did before the app was installed.
        return compiler.compile(self.lhs)

    def as_postgresql(
        self, compiler: Any, connection: Any, **extra: Any
    ) -> Any:
        sql, params = compiler.compile(self.lhs)

        # The wrapper takes text; the cast is what lets a number, a
        # date or a varchar through - and an index repeats it exactly.
        return f"{FUNCTION}(({sql})::text)", params

    def as_sqlite(self, compiler: Any, connection: Any, **extra: Any) -> Any:
        sql, params = compiler.compile(self.lhs)

        return f"{FUNCTION}({sql})", params

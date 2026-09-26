"""Migration operations for PostgreSQL's side of the search.

Both do nothing on another database, like Django's own
``CreateExtension``: a migration that holds them runs everywhere, and
builds what only PostgreSQL can use where PostgreSQL is.
"""

from __future__ import annotations

from typing import Any, Sequence

from django.db.migrations.operations.base import Operation

from generic.search import FUNCTION


def is_postgresql(schema_editor: Any) -> bool:
    return schema_editor.connection.vendor == "postgresql"


class InstallUnaccent(Operation):
    """``unaccent`` and ``pg_trgm``, and the wrapper a search calls.

    ``unaccent()`` itself is only ``STABLE`` - its dictionary could
    change - so no index may use it. The wrapper promises the same
    answer for the same text, which is true as long as nobody edits the
    rules file, and names the extension's schema outright so it still
    resolves under an empty ``search_path`` (a restore, for one).

    Both extensions are *trusted* since PostgreSQL 13: the database's
    owner creates them without being a superuser.
    """

    reversible = True
    reduces_to_sql = True

    def state_forwards(self, app_label: str, state: Any) -> None:
        pass

    def database_forwards(
        self,
        app_label: str,
        schema_editor: Any,
        from_state: Any,
        to_state: Any,
    ) -> None:
        if not is_postgresql(schema_editor):
            return

        schema_editor.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
        schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT extnamespace::regnamespace::text FROM pg_extension "
                "WHERE extname = 'unaccent'"
            )
            schema = cursor.fetchone()[0]

        quoted = schema_editor.quote_name(schema)
        schema_editor.execute(
            f"CREATE OR REPLACE FUNCTION {FUNCTION}(text) RETURNS text "
            f"LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS "
            f"$$ SELECT {quoted}.unaccent('{quoted}.unaccent'::regdictionary"
            f", $1) $$"
        )

    def database_backwards(
        self,
        app_label: str,
        schema_editor: Any,
        from_state: Any,
        to_state: Any,
    ) -> None:
        if not is_postgresql(schema_editor):
            return

        # The extensions stay: something else may use them, and they
        # cost nothing unused.
        schema_editor.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text)")

    def describe(self) -> str:
        return "Installs unaccent, pg_trgm and the search function"


class CreateSearchIndex(Operation):
    """A trigram index making a ``%term%`` search on these fields fast.

    ::

        from generic.search.operations import CreateSearchIndex

        operations = [
            CreateSearchIndex("ticket", ("reference", "title"),
                              name="ticket_search"),
        ]

    One GIN ``gin_trgm_ops`` index over each field, on exactly the
    expression a search compiles to - ``UPPER(generic_unaccent(col))``
    - so the planner can use it for ``icontains``, ``istartswith`` and
    the rest. On any other database it does nothing, and the migration
    still runs there.
    """

    reversible = True
    reduces_to_sql = True

    def __init__(
        self,
        model_name: str,
        fields: Sequence[str],
        name: str,
    ) -> None:
        self.model_name = model_name
        self.fields = tuple(fields)
        self.name = name

    def deconstruct(self) -> tuple[str, list, dict]:
        return (
            self.__class__.__name__,
            [self.model_name, self.fields],
            {"name": self.name},
        )

    def state_forwards(self, app_label: str, state: Any) -> None:
        pass

    def index_names(self) -> list[str]:
        if len(self.fields) == 1:
            return [self.name]

        return [f"{self.name}_{number}" for number in range(len(self.fields))]

    def database_forwards(
        self,
        app_label: str,
        schema_editor: Any,
        from_state: Any,
        to_state: Any,
    ) -> None:
        if not is_postgresql(schema_editor):
            return

        model = to_state.apps.get_model(app_label, self.model_name)
        table = schema_editor.quote_name(model._meta.db_table)

        for index, field_name in zip(self.index_names(), self.fields):
            column = schema_editor.quote_name(
                model._meta.get_field(field_name).column
            )
            schema_editor.execute(
                f"CREATE INDEX IF NOT EXISTS "
                f"{schema_editor.quote_name(index)} ON {table} USING gin "
                f"((UPPER(({FUNCTION}(({column})::text))::text)) "
                f"gin_trgm_ops)"
            )

    def database_backwards(
        self,
        app_label: str,
        schema_editor: Any,
        from_state: Any,
        to_state: Any,
    ) -> None:
        if not is_postgresql(schema_editor):
            return

        for index in self.index_names():
            schema_editor.execute(
                f"DROP INDEX IF EXISTS {schema_editor.quote_name(index)}"
            )

    def describe(self) -> str:
        return f"Creates search index {self.name} on {self.model_name}"

    @property
    def migration_name_fragment(self) -> str:
        return f"search_index_{self.name}"

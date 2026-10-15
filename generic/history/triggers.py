"""PostgreSQL triggers: the writes made outside the application, kept.

The recorder (:mod:`generic.history.recording`, :mod:`.bulk`) sees what
goes through Django's ORM. A row changed from ``psql``, by another
application sharing the database, by a script, or by raw SQL in the
project's own code leaves no trace there - and the question an audit
asks is precisely "who changed this, and how" (ISO/IEC 27001 A.8.15).

So, on PostgreSQL, every recorded model's table carries a trigger,
``generic_history``, that writes the same kind of entry - the record's
own fields, by field name, compared with the last version - for every
row inserted, updated or deleted *outside* the ORM. Who did it is the
database role (``session_user``), the source says
``Database (outside the application)``.

The ORM's own writes are already recorded, with the person behind them:
each one is sent with the comment ``/* generic:orm */``, and the trigger
leaves those to the application. A statement that does not carry it is
recorded by the trigger - which is what makes raw SQL visible. A role
that may drop a trigger can of course go around it: that is what the
database's own audit (``pgaudit``) and its privileges are for.

The triggers are installed after every ``migrate`` (``post_migrate``)
and by ``manage.py history_triggers``; ``GENERIC["HISTORY_TRIGGERS"]``
- ``None``, the default, means "on PostgreSQL" - turns them off, and
the next ``migrate`` removes them. Not covered: many-to-many tables
(the version carries the last known list forward), models inheriting
another's table, composite keys.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from contextvars import ContextVar
from typing import Any, Iterator

from django.db import models

logger = logging.getLogger(__name__)

#: What every ORM write carries, and the trigger looks for.
TAG = "/* generic:orm */"

#: The names everything here is created under, and dropped by.
PREFIX = "generic_history"
TRIGGER = PREFIX
SOURCE = "Database (outside the application)"

#: Inside a compiler's execute_sql: the statement is the ORM's.
_orm: ContextVar[bool] = ContextVar("generic_history_orm", default=False)

ISO_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {PREFIX}_iso(value timestamptz) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    -- datetime.isoformat() in UTC, as the application writes it.
    SELECT to_char(value AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
        || CASE WHEN extract(microseconds FROM value)::bigint % 1000000 = 0
                THEN '' ELSE to_char(value AT TIME ZONE 'UTC', '.US') END
        || '+00:00'
$$;
CREATE OR REPLACE FUNCTION {PREFIX}_iso_naive(value timestamp) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT to_char(value, 'YYYY-MM-DD"T"HH24:MI:SS')
        || CASE WHEN extract(microseconds FROM value)::bigint % 1000000 = 0
                THEN '' ELSE to_char(value, '.US') END
$$;
CREATE OR REPLACE FUNCTION {PREFIX}_time(value time) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT to_char(value, 'HH24:MI:SS')
        || CASE WHEN extract(microseconds FROM value)::bigint % 1000000 = 0
                THEN '' ELSE to_char(value, '.US') END
$$;
"""  # nosec B608 - names from model metadata, quoted


def is_wanted(connection: Any) -> bool:
    """Whether this database gets the triggers."""
    from generic.conf import generic_settings

    wanted = generic_settings.HISTORY_TRIGGERS

    if connection.vendor != "postgresql":
        return False

    return bool(generic_settings.HISTORY) and wanted is not False


# -- tagging the ORM's writes --------------------------------------------


@contextlib.contextmanager
def orm_write() -> Iterator[None]:
    token = _orm.set(True)

    try:
        yield
    finally:
        _orm.reset(token)


def tag(execute: Any, sql: str, params: Any, many: bool, context: Any):
    """The connection's execute wrapper: an ORM write says so."""
    if _orm.get() and isinstance(sql, str):
        sql = f"{TAG} {sql}"

    return execute(sql, params, many, context)


def watch_connection(connection: Any) -> None:
    if connection.vendor == "postgresql" and tag not in getattr(
        connection, "execute_wrappers", ()
    ):
        connection.execute_wrappers.append(tag)


def connection_created(sender: Any, connection: Any, **kwargs: Any) -> None:
    watch_connection(connection)


_installed = False


def install_tagging() -> None:
    """Tag the ORM's writes, on every PostgreSQL connection, once."""
    global _installed

    if _installed:
        return

    _installed = True

    from django.db import connections
    from django.db.backends.signals import connection_created as created
    from django.db.models.sql import compiler

    for name in (
        "SQLInsertCompiler",
        "SQLUpdateCompiler",
        "SQLDeleteCompiler",
    ):
        klass = getattr(compiler, name)
        original = klass.execute_sql

        def execute_sql(self: Any, *args: Any, __original=original, **kw):
            with orm_write():
                return __original(self, *args, **kw)

        execute_sql.__wrapped__ = original  # type: ignore[attr-defined]
        klass.execute_sql = execute_sql

    created.connect(connection_created, dispatch_uid="generic.history.tag")

    for alias in connections:
        # Already open - the test runner's, a shell's.
        connection = connections[alias]

        if connection.connection is not None:
            watch_connection(connection)


# -- the SQL --------------------------------------------------------------


def value_sql(field: Any, column: str) -> str:
    """The expression giving ``field``'s value as the recorder writes it
    (``generic.history.recording.json_safe``)."""
    from django.conf import settings

    internal = field.get_internal_type()

    if internal == "DateTimeField":
        function = "iso" if settings.USE_TZ else "iso_naive"

        return f"{PREFIX}_{function}(rec.{column})"

    if internal == "DateField":
        return f"to_char(rec.{column}, 'YYYY-MM-DD')"

    if internal == "TimeField":
        return f"{PREFIX}_time(rec.{column})"

    if internal == "JSONField":
        return f"rec.{column}::jsonb"

    if isinstance(field, models.BooleanField) or internal in (
        "AutoField",
        "BigAutoField",
        "SmallAutoField",
        "IntegerField",
        "BigIntegerField",
        "SmallIntegerField",
        "PositiveIntegerField",
        "PositiveBigIntegerField",
        "PositiveSmallIntegerField",
        "FloatField",
    ):
        return f"rec.{column}"

    if field.is_relation:
        target = field.target_field

        return value_sql(target, column)

    # Text, decimals (as the database holds them: "10.00"), UUIDs,
    # file names: their text.
    return f"rec.{column}::text"


def quote(connection: Any, name: str) -> str:
    return connection.ops.quote_name(name)


def literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def trackable(resource: Any) -> bool:
    meta = resource.model._meta

    return (
        not meta.proxy
        and not meta.parents
        and meta.managed
        and getattr(meta.pk, "column", None) is not None
    )


def function_name(model: Any) -> str:
    return f"{PREFIX}_{model._meta.db_table}"[:63]


def trigger_sql(connection: Any, resource: Any) -> str:
    """The function and trigger recording ``resource``'s table."""
    from generic.history.recording import tracked_fields

    model = resource.model
    meta = model._meta
    table = quote(connection, meta.db_table)
    pk = quote(connection, meta.pk.column)
    function = quote(connection, function_name(model))
    pairs: list[str] = []
    carried: list[str] = []

    for field in tracked_fields(resource):
        if field.many_to_many:
            carried.append(field.name)
            continue

        column = quote(connection, field.column)
        pairs.append(f"{literal(field.name)}, {value_sql(field, column)}")

    # jsonb_build_object takes 100 arguments: 50 fields a call.
    objects = [
        "jsonb_build_object(" + ", ".join(pairs[i : i + 50]) + ")"
        for i in range(0, len(pairs), 50)
    ] or ["'{}'::jsonb"]
    carry = "".join(f"""
    IF previous.values ? {literal(name)} THEN
        vals := vals || jsonb_build_object({literal(name)},
            previous.values -> {literal(name)});
    END IF;""" for name in carried)
    entries = quote(connection, "generic_historyentry")

    # Names from the models' own metadata, quoted by the backend;
    # values through literal(). Nothing here comes from a request.
    return f"""
CREATE OR REPLACE FUNCTION {function}() RETURNS trigger
LANGUAGE plpgsql AS $body$
DECLARE
    rec record;
    vals jsonb;
    act text;
    kind integer;
    identity text;
    previous record;
BEGIN
    -- The application records its own writes, with who made them.
    IF position({literal(TAG)} IN coalesce(current_query(), '')) > 0 THEN
        RETURN NULL;
    END IF;

    IF TG_OP = 'DELETE' THEN
        rec := OLD; act := 'deleted';
    ELSIF TG_OP = 'INSERT' THEN
        rec := NEW; act := 'created';
    ELSE
        rec := NEW; act := 'updated';
    END IF;

    SELECT id INTO kind FROM django_content_type
        WHERE app_label = {literal(meta.app_label)}
        AND model = {literal(meta.model_name)};
    identity := left(rec.{pk}::text, 128);
    vals := {" || ".join(objects)};

    SELECT version, "values", label INTO previous FROM {entries}
        WHERE content_type_id = kind AND object_id = identity
        ORDER BY version DESC, id DESC LIMIT 1;
{carry}
    -- Saved without a change is not a version.
    IF act = 'updated' AND previous.version IS NOT NULL
            AND previous.values = vals THEN
        RETURN NULL;
    END IF;

    INSERT INTO {entries} (content_type_id, object_id, label, version,
        action, user_id, user_label, source, at, batch, "values")
    VALUES (kind, identity,
        left(coalesce(previous.label, {literal(meta.verbose_name_raw)}
            || ' ' || identity), 200),
        coalesce(previous.version, 0) + 1, act, NULL,
        left(session_user::text, 200), {literal(SOURCE)},
        clock_timestamp(), '', vals);

    RETURN NULL;
EXCEPTION WHEN OTHERS THEN
    -- Recording must never break the write, as in the application:
    -- the failure goes to the server's log.
    RAISE WARNING 'generic history: % on %: %', TG_OP, TG_TABLE_NAME,
        SQLERRM;
    RETURN NULL;
END
$body$;
DROP TRIGGER IF EXISTS {TRIGGER} ON {table};
CREATE TRIGGER {TRIGGER} AFTER INSERT OR UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION {function}();
"""  # nosec B608 - names from model metadata, quoted


def recorded_resources() -> list[Any]:
    """One resource per recorded table - the first site's."""
    from generic.history.bulk import RECORDED, recording

    found = []

    for model in list(RECORDED):
        resources = [r for r in recording(model) if trackable(r)]

        if resources:
            found.append(resources[0])

    return found


def existing(connection: Any) -> list[tuple[str, str]]:
    """(table, function) of every trigger installed here."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT event_object_table, action_statement
            FROM information_schema.triggers
            WHERE trigger_name = %s AND event_object_schema = current_schema()
            GROUP BY event_object_table, action_statement
            """,
            [TRIGGER],
        )

        return [(table, statement) for table, statement in cursor.fetchall()]


def drop_sql(connection: Any, table: str) -> str:
    return (
        f"DROP TRIGGER IF EXISTS {TRIGGER} ON {quote(connection, table)};\n"
        f"DROP FUNCTION IF EXISTS "
        f"{quote(connection, (PREFIX + '_' + table)[:63])}();\n"
    )


def install(connection: Any, *, verbosity: int = 1) -> int:
    """Install, update or remove the triggers. Returns how many are in
    place afterwards."""
    from django.db import transaction

    wanted = is_wanted(connection)
    resources = recorded_resources() if wanted else []
    tables = {resource.model._meta.db_table for resource in resources}
    statements = [ISO_FUNCTION] if resources else []
    statements += [trigger_sql(connection, r) for r in resources]

    for table, _statement in existing(connection):
        if table not in tables:
            statements.append(drop_sql(connection, table))

    if not statements:
        return 0

    with transaction.atomic(using=connection.alias):
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    if verbosity:
        sys.stdout.write(
            f"History triggers: {len(resources)} table(s) recorded "
            "outside the application.\n"
        )

    return len(resources)


def post_migrate(sender: Any, using: str = "default", **kwargs: Any) -> None:
    """After ``migrate``: the triggers follow the models."""
    from django.db import connections

    if getattr(sender, "name", "") != "generic":
        return

    connection = connections[using]

    if connection.vendor != "postgresql":
        return

    try:
        install(connection, verbosity=0)
    except Exception:
        logger.exception("Could not install the history triggers.")


__all__ = ["SOURCE", "TAG", "install", "install_tagging", "trigger_sql"]

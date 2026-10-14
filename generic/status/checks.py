"""Whether each thing the application leans on answers.

A check is a function taking nothing. What it returns says how it went:

- ``None``, ``True`` or ``"ok"``: fine;
- ``False``: broken;
- ``"warning"``, ``"error"`` or ``"off"`` (not in use here);
- ``(level, detail)``, or ``{"level": ..., "detail": ...}``;
- an exception: broken, its message as the detail.

The framework's own run first - databases, migrations, caches, the
channel layer, Celery, the media folder, the tasks - then the
project's, declared with :func:`register_check` or listed in
``GENERIC["STATUS_CHECKS"]``.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from django.apps import apps
from django.conf import settings
from django.core.cache import caches
from django.db import connections
from django.utils import timezone
from django.utils.module_loading import import_string
from django.utils.translation import gettext, ngettext

from generic.conf import generic_settings

logger = logging.getLogger(__name__)

#: Worst last: the state of a whole server is its worst check's.
LEVELS = ("off", "ok", "warning", "error")


def worst(levels: Any) -> str:
    found = [level for level in levels if level in LEVELS]

    if not found:
        return "ok"

    worst_level = max(found, key=LEVELS.index)

    return "ok" if worst_level == "off" else worst_level


@dataclass(frozen=True)
class Check:
    """One declared check."""

    name: str
    label: Any
    function: Callable[[], Any]
    group: Any = ""

    def run(self) -> dict[str, Any]:
        started = time.perf_counter()

        try:
            level, detail = normalize(self.function())
        except Exception as error:
            # Shown on the page - the reason the check exists - and
            # logged, without paging anybody: a warning, not an error,
            # or a database that is down would mail on every refresh.
            logger.warning("Status check %s failed", self.name, exc_info=True)
            level = "error"
            detail = str(error) or error.__class__.__name__

        return {
            "name": self.name,
            "label": str(self.label),
            "group": str(self.group or gettext("Project")),
            "level": level,
            "detail": str(detail or ""),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }


def normalize(result: Any) -> tuple[str, str]:
    """``(level, detail)`` from whatever a check returned."""
    if result is None or result is True:
        return "ok", ""

    if result is False:
        return "error", ""

    if isinstance(result, str):
        return (result, "") if result in LEVELS else ("ok", result)

    if isinstance(result, dict):
        level = result.get("level", result.get("status", "ok"))
        detail = result.get("detail", "")
    elif isinstance(result, (list, tuple)) and len(result) == 2:
        level, detail = result
    else:
        raise TypeError(
            f"A status check returned {result!r}: return None, a level, "
            f"(level, detail) or a dict."
        )

    if level is True:
        level = "ok"
    elif level is False:
        level = "error"

    if level not in LEVELS:
        raise ValueError(
            f"{level!r} is not a status level; use one of "
            f"{', '.join(LEVELS)}."
        )

    return level, str(detail or "")


# -- the project's checks -------------------------------------------------

_registry: dict[str, Check] = {}


def register_check(
    function: Callable[[], Any] | None = None,
    *,
    name: str = "",
    label: Any = "",
    group: Any = "",
) -> Any:
    """Declare a check of the project's own::

        from generic.status import register_check

        @register_check(label=_("Payment provider"))
        def payments():
            response = requests.get(PROVIDER, timeout=3)
            if response.status_code != 200:
                return "error", f"HTTP {response.status_code}"
            return "ok", _("Answered")

    In a module imported at start-up - the app's ``resources.py`` is
    one. The name defaults to the function's; declaring it again
    replaces it, so a reloaded module does not show it twice.
    """

    def declare(target: Callable[[], Any]) -> Callable[[], Any]:
        key = name or f"{target.__module__}.{target.__name__}"
        _registry[key] = Check(
            name=key,
            label=label or target.__name__.replace("_", " ").capitalize(),
            function=target,
            group=group,
        )

        return target

    return declare(function) if function is not None else declare


def unregister_check(name: str) -> None:
    _registry.pop(name, None)


def project_checks() -> list[Check]:
    found = list(_registry.values())

    for path in generic_settings.STATUS_CHECKS or []:
        function = import_string(path)
        label = (
            getattr(function, "label", "")
            or function.__name__.replace("_", " ").capitalize()
        )
        found.append(Check(name=path, label=label, function=function))

    return found


# -- the framework's own ---------------------------------------------------


#: The query asking a database that speaks no plain SQL whether it
#: answers, by its backend's vendor. Salesforce (django-salesforce)
#: speaks SOQL, which has no ``SELECT 1``: every organisation has one
#: Organization row, readable with API access.
PROBES = {
    "salesforce": "SELECT Id FROM Organization LIMIT 1",
}


def probe_for(alias: str) -> str:
    """What to ask ``alias``: the project's query, else its vendor's."""
    declared = dict(generic_settings.STATUS_DATABASE_QUERIES or {})

    if declared.get(alias):
        return str(declared[alias])

    connection = connections[alias]

    if connection.vendor in PROBES:
        return PROBES[connection.vendor]

    # Oracle wants a table even for a constant: "SELECT 1 FROM DUAL".
    return "SELECT 1" + connection.features.bare_select_suffix


def database_version(connection: Any) -> str:
    """The engine and its version, or the engine alone when the backend
    does not say (a third-party backend often does not)."""
    try:
        version = ".".join(
            str(part) for part in connection.get_database_version()
        )
    except Exception:
        return str(connection.display_name)

    return f"{connection.display_name} {version}"


def database_aliases() -> list[str]:
    """Every database, but those the project left out with ``None``."""
    declared = dict(generic_settings.STATUS_DATABASE_QUERIES or {})

    return [
        alias
        for alias in settings.DATABASES
        if not (alias in declared and declared[alias] is None)
    ]


def database_check(alias: str) -> Check:
    def run() -> tuple[str, str]:
        connection = connections[alias]

        with connection.cursor() as cursor:
            cursor.execute(probe_for(alias))
            cursor.fetchone()

        return "ok", database_version(connection)

    return Check(
        name=f"database.{alias}",
        label=gettext("Database %(alias)s") % {"alias": alias},
        function=run,
        group=gettext("Databases"),
    )


def migrations_check() -> tuple[str, str]:
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connections["default"])
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())

    if plan:
        return "warning", ngettext(
            "%(count)s migration is not applied.",
            "%(count)s migrations are not applied.",
            len(plan),
        ) % {"count": len(plan)}

    return "ok", gettext("Up to date")


def cache_check(alias: str) -> Check:
    def run() -> tuple[str, str]:
        backend = settings.CACHES[alias].get("BACKEND", "")
        name = backend.rsplit(".", 1)[-1]

        if backend.endswith("DummyCache"):
            return "off", gettext("No cache: nothing is kept")

        cache = caches[alias]
        key = f"generic:status:{uuid.uuid4().hex}"
        cache.set(key, "1", 30)

        try:
            if cache.get(key) != "1":
                return "error", gettext("A value written was not read back")
        finally:
            cache.delete(key)

        if backend.endswith("LocMemCache"):
            return "ok", gettext("In memory, this process only")

        return "ok", name

    return Check(
        name=f"cache.{alias}",
        label=gettext("Cache %(alias)s") % {"alias": alias},
        function=run,
        group=gettext("Services"),
    )


def channel_layer_check() -> tuple[str, str]:
    import asyncio

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()

    if layer is None:
        return "off", gettext("No channel layer: pages are not live")

    name = layer.__class__.__name__

    if name == "InMemoryChannelLayer":
        return "ok", gettext("In memory, this process only")

    async def round_trip() -> Any:
        channel = await layer.new_channel()
        await layer.send(channel, {"type": "generic.status"})

        return await asyncio.wait_for(layer.receive(channel), timeout=3)

    message = async_to_sync(round_trip)()

    if (message or {}).get("type") != "generic.status":
        return "error", gettext("A message sent was not received")

    return "ok", name


def celery_app() -> Any:
    try:
        from celery import current_app
    except ImportError:
        return None

    return current_app


def celery_check() -> tuple[str, str]:
    app = celery_app()
    conf = app.conf

    if conf.get("task_always_eager"):
        return "ok", gettext("Eager: tasks run in the process asking")

    if not conf.get("broker_url"):
        return "off", gettext("No broker: tasks run in the process asking")

    with app.connection_for_write(connect_timeout=3) as connection:
        connection.ensure_connection(max_retries=1)

    workers = app.control.ping(timeout=1.0) or []

    if not workers:
        return "warning", gettext(
            "The broker answers, but no worker does: queued tasks wait."
        )

    return "ok", ngettext(
        "%(count)s worker answers",
        "%(count)s workers answer",
        len(workers),
    ) % {"count": len(workers)}


def media_check() -> tuple[str, str]:
    root = str(settings.MEDIA_ROOT)

    if not os.path.isdir(root):
        return "error", gettext("%(path)s does not exist") % {"path": root}

    if not os.access(root, os.W_OK):
        return "error", gettext("%(path)s cannot be written") % {"path": root}

    return "ok", gettext("Writable")


def tasks_check() -> tuple[str, str]:
    from generic.tasks.models import TaskRun

    since = timezone.now() - timedelta(hours=24)
    failed = TaskRun.objects.failed().filter(queued_at__gte=since).count()

    if failed:
        return "warning", ngettext(
            "%(count)s run failed in the last 24 hours",
            "%(count)s runs failed in the last 24 hours",
            failed,
        ) % {"count": failed}

    return "ok", gettext("No run failed in the last 24 hours")


def framework_checks() -> list[Check]:
    found = [database_check(alias) for alias in database_aliases()]
    found.append(
        Check(
            name="migrations",
            label=gettext("Migrations"),
            function=migrations_check,
            group=gettext("Databases"),
        )
    )
    found += [cache_check(alias) for alias in settings.CACHES]

    services = gettext("Services")
    application = gettext("Application")

    if apps.is_installed("channels") or getattr(
        settings, "CHANNEL_LAYERS", None
    ):
        found.append(
            Check(
                name="channels",
                label=gettext("Channel layer"),
                function=channel_layer_check,
                group=services,
            )
        )

    if celery_app() is not None:
        found.append(
            Check(
                name="celery",
                label=gettext("Celery"),
                function=celery_check,
                group=services,
            )
        )

    if getattr(settings, "MEDIA_ROOT", ""):
        found.append(
            Check(
                name="media",
                label=gettext("Media files"),
                function=media_check,
                group=application,
            )
        )

    found.append(
        Check(
            name="tasks",
            label=gettext("Tasks"),
            function=tasks_check,
            group=application,
        )
    )

    return found


def run_checks() -> list[dict[str, Any]]:
    return [check.run() for check in framework_checks() + project_checks()]

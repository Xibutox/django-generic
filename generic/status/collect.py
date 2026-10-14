"""This server's status, as one JSON document.

The same document feeds this server's page and every other server that
shows it beside its own: what one reads, the others read. ``format``
names its shape, so a reader can tell a status from any other JSON an
address might answer.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import django
import rest_framework
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

import generic
from generic.conf import generic_settings
from generic.status.checks import run_checks, worst
from generic.status.system import system

FORMAT = "generic-status/1"


def absolute(request: Any, name: str) -> str:
    try:
        path = reverse(name)
    except NoReverseMatch:
        return ""

    return request.build_absolute_uri(path) if request is not None else path


def server(request: Any) -> dict[str, Any]:
    from generic.sites import site

    return {
        "title": str(site.get_title()),
        "version": str(generic_settings.VERSION or ""),
        "framework": generic.__version__,
        "django": django.get_version(),
        "rest_framework": rest_framework.VERSION,
        "debug": bool(settings.DEBUG),
        "time_zone": str(settings.TIME_ZONE),
        "language": str(settings.LANGUAGE_CODE),
        "page_url": absolute(request, "site:status"),
        "api_url": absolute(request, "generic:status"),
        "site_url": absolute(request, "site:index"),
    }


def application() -> dict[str, Any]:
    """Who is using it, and what is planned for it."""
    from generic.maintenance.models import RestartAnnouncement

    now = timezone.now()
    users = get_user_model().objects.filter(is_active=True)
    sessions = None

    if "django.contrib.sessions" in settings.INSTALLED_APPS and (
        settings.SESSION_ENGINE.endswith(("db", "cached_db"))
    ):
        from django.contrib.sessions.models import Session

        sessions = Session.objects.filter(expire_date__gt=now).count()

    restart = RestartAnnouncement.objects.current()

    return {
        "users": users.count(),
        "users_today": users.filter(
            last_login__gte=now - timedelta(hours=24)
        ).count(),
        "sessions": sessions,
        "restart": restart.as_client() if restart else None,
    }


def gauges_level(machine: dict[str, Any]) -> str:
    levels = [
        machine["cpu"]["level"],
        machine["memory"]["level"],
        machine["memory"]["swap"]["level"],
    ]
    levels += [disk["level"] for disk in machine["disks"]]

    return worst(levels)


def snapshot(request: Any = None) -> dict[str, Any]:
    """Everything the status page shows about this server."""
    started = time.perf_counter()
    checks = run_checks()
    machine = system()
    level = worst(
        [check["level"] for check in checks] + [gauges_level(machine)]
    )

    return {
        "format": FORMAT,
        "level": level,
        "generated_at": timezone.now().isoformat(),
        "server": server(request),
        "system": machine,
        "checks": checks,
        "application": application(),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }

"""Security events: who signed in, failed to, was locked out, changed a
password, made an API token, was given a right, exported a table.

The history answers "what changed", the access log "who read what";
neither says who signed in from where, or that someone tried thirty
passwords - the first questions after an incident (ISO/IEC 27001
A.8.15, A.8.16; GDPR Art. 33). Each event is written twice:

* to the ``generic.security`` logger - one line, with the account and
  the address, for the log file and whatever collects it (a refusal
  at ``WARNING``, the rest at ``INFO``);
* to :class:`SecurityEvent`, read on *History > Security events*
  behind ``generic.view_securityevent``.

Recorded by the framework itself, nothing to declare. A project
records its own with :func:`record`::

    from generic.audit import record

    record("exported", request=request, detail="Yearly report")

``GENERIC["SECURITY_LOG"] = False`` turns it off;
``SECURITY_LOG_RETENTION_DAYS`` (``None``: keep everything) is applied
by ``apply_retention`` with the other stores. See docs/security-log.md.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

logger = logging.getLogger("generic.security")

#: Logged at WARNING: worth a look by whoever reads the log.
REFUSALS = frozenset({"sign_in_failed", "locked_out", "access_refused"})


def is_on() -> bool:
    from generic.conf import generic_settings

    return bool(generic_settings.SECURITY_LOG)


def name_of(user: Any) -> str:
    if user is None or not getattr(user, "pk", None):
        return ""

    return (user.get_full_name() or user.get_username())[:200]


def record(
    kind: str,
    *,
    request: Any = None,
    user: Any = None,
    username: str = "",
    actor: Any = None,
    detail: str = "",
) -> Any:
    """Record one event. Returns the entry, or ``None`` when the log is
    off or the entry could not be written - which is logged, and never
    raised: a sign-in does not fail because its record did.

    ``user`` is the account it is about, by default the request's;
    ``username`` the name typed, for an account that may not exist;
    ``actor`` whoever acted on somebody else's account.
    """
    from django.db import transaction

    from generic.access import address_of
    from generic.audit.models import SecurityEvent

    if not is_on():
        return None

    if user is None and request is not None:
        candidate = getattr(request, "user", None)

        if getattr(candidate, "is_authenticated", False):
            user = candidate

    if user is not None and not getattr(user, "pk", None):
        user = None

    username = (username or (user.get_username() if user else ""))[:150]
    address = address_of(request) if request is not None else None
    agent = ""

    if request is not None:
        agent = (getattr(request, "META", None) or {}).get(
            "HTTP_USER_AGENT", ""
        )[:255]

    actor_label = name_of(actor) if actor is not None and actor != user else ""
    detail = str(detail or "")[:255]

    logger.log(
        logging.WARNING if kind in REFUSALS else logging.INFO,
        "%s account=%r user_id=%s by=%r address=%s detail=%r",
        kind,
        username,
        getattr(user, "pk", None),
        actor_label,
        address or "-",
        detail,
    )

    try:
        with transaction.atomic():
            return SecurityEvent.objects.create(
                kind=kind,
                user=user,
                username=username,
                actor_label=actor_label,
                detail=detail,
                address=address,
                user_agent=agent,
            )
    except Exception:
        logger.exception("Could not record the security event %s", kind)

        return None


def prune(days: int | None = None) -> int:
    """Delete events older than ``days`` - by default
    ``GENERIC["SECURITY_LOG_RETENTION_DAYS"]``; ``None`` keeps them
    all. Returns how many went."""
    from django.utils import timezone

    from generic.audit.models import SecurityEvent
    from generic.conf import generic_settings

    if days is None:
        days = generic_settings.SECURITY_LOG_RETENTION_DAYS

    if not days:
        return 0

    cutoff = timezone.now() - datetime.timedelta(days=int(days))
    deleted, _detail = SecurityEvent.objects.filter(at__lt=cutoff).delete()

    return deleted


__all__ = ["is_on", "logger", "prune", "record"]

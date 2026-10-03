"""Failed passwords, counted: the sign-in page stops guessing.

After ``GENERIC["LOGIN_MAX_ATTEMPTS"]`` failed passwords for one
account, the sign-in page refuses that account for
``GENERIC["LOGIN_LOCKOUT_MINUTES"]`` - without even checking the
password, so a guess made meanwhile tells nothing. One address is
allowed four times as many failures, for every account together: an
office behind one address is many people, a script trying names is
one. A success clears the account's count.

The counts live in Django's cache, so they hold across the processes
sharing it - Redis in production; the default local-memory cache counts
per process. Signing in through an SSO provider is never counted:
the provider has its own rules.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from django.core.cache import cache

logger = logging.getLogger("generic.accounts")

#: How many more failures one address may make than one account.
ADDRESS_FACTOR = 4


def limits() -> tuple[int | None, int]:
    """(attempts, seconds) - attempts ``None`` when nothing is counted."""
    from generic.conf import generic_settings

    attempts = generic_settings.LOGIN_MAX_ATTEMPTS
    minutes = generic_settings.LOGIN_LOCKOUT_MINUTES or 15

    return (int(attempts) if attempts else None), int(minutes) * 60


def account_key(username: str) -> str:
    # Hashed: a key holds what anybody typed, a cache key must stay
    # short and plain.
    digest = hashlib.sha256(
        (username or "").strip().lower().encode()
    ).hexdigest()

    return f"generic:login:account:{digest[:32]}"


def address_key(request: Any) -> str | None:
    from generic.access import address_of

    address = address_of(request)

    return f"generic:login:address:{address}" if address else None


def counted(request: Any, username: str) -> list[tuple[str, int]]:
    """Each key this attempt counts against, with its limit."""
    attempts, _seconds = limits()

    if attempts is None:
        return []

    keys = [(account_key(username), attempts)]
    address = address_key(request)

    if address:
        keys.append((address, attempts * ADDRESS_FACTOR))

    return keys


def is_locked(request: Any, username: str) -> bool:
    """Whether this account, or this address, has failed too often."""
    return any(
        (cache.get(key) or 0) >= limit
        for key, limit in counted(request, username)
    )


def failed(request: Any, username: str) -> None:
    """Count one failed password. The window opens at the first."""
    _attempts, seconds = limits()

    for key, limit in counted(request, username):
        cache.add(key, 0, timeout=seconds)

        try:
            count = cache.incr(key)
        except ValueError:
            # Expired between the two calls: this is the first again.
            cache.set(key, 1, timeout=seconds)
            count = 1

        if count == limit:
            logger.warning(
                "Sign-in refused for %s minutes after %s failed "
                "passwords (%s).",
                seconds // 60,
                count,
                "address" if "address" in key else "account",
            )


def succeeded(request: Any, username: str) -> None:
    """A right password: the account's count starts again."""
    cache.delete(account_key(username))


__all__ = ["failed", "is_locked", "succeeded"]

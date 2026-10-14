"""Asking another server for its status.

The request goes from this server, never from the browser: the other
server's token stays here, and nothing needs the other site to allow
this one's pages (CORS). One request per server, so a server that does
not answer delays only its own card.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from django.utils import timezone, translation
from django.utils.translation import gettext

import generic
from generic.conf import generic_settings
from generic.status.checks import LEVELS
from generic.status.collect import FORMAT
from generic.status.models import StatusServer

logger = logging.getLogger(__name__)

#: The header carrying the shared secret. A header of its own rather
#: than Authorization, where an API token class would read it, refuse
#: it and answer 401 before the status view had a say.
TOKEN_HEADER = "X-Generic-Status-Token"

#: More than any status: an address answering a film is not one.
MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirections: the token is not sent anywhere else."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


opener = urllib.request.build_opener(NoRedirect)


def is_web_address(value: Any) -> bool:
    parts = urlsplit(str(value or ""))

    return parts.scheme in ("http", "https") and bool(parts.netloc)


def read(server: StatusServer) -> dict[str, Any]:
    """The other server's status, raw; raises what went wrong."""
    request = urllib.request.Request(
        server.status_url,
        headers={
            "Accept": "application/json",
            # The other server's checks, in the reader's language when
            # it speaks it.
            "Accept-Language": translation.get_language() or "en",
            "User-Agent": f"django-generic/{generic.__version__} status",
            **({TOKEN_HEADER: server.token} if server.token else {}),
        },
    )
    timeout = float(generic_settings.STATUS_REMOTE_TIMEOUT or 5)

    # The address was checked to be http(s) when it was saved.
    with opener.open(request, timeout=timeout) as response:  # nosec B310
        body = response.read(MAX_BYTES + 1)

    if len(body) > MAX_BYTES:
        raise ValueError(gettext("The answer is too large to be a status."))

    try:
        payload = json.loads(body.decode("utf-8"))
    except ValueError:
        raise ValueError(
            gettext(
                "The address does not answer a status: check that it is "
                "the other server's status endpoint."
            )
        ) from None

    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise ValueError(
            gettext(
                "The address answers, but not with a django-generic status."
            )
        )

    return payload


def describe(error: Exception) -> str:
    """What went wrong, in a sentence for the card."""
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return gettext(
                "Refused (HTTP %(code)s): check the token, and the other "
                "server's STATUS_TOKEN."
            ) % {"code": error.code}

        if 300 <= error.code < 400:
            return gettext(
                "Redirected to %(location)s: put that address instead."
            ) % {"location": error.headers.get("Location", "?")}

        if error.code == 404:
            return gettext(
                "Not found (HTTP 404): the address is not a status "
                "endpoint, or the other server has no status page."
            )

        return gettext("The server answered HTTP %(code)s.") % {
            "code": error.code
        }

    if isinstance(error, urllib.error.URLError):
        return gettext("Unreachable: %(reason)s") % {"reason": error.reason}

    if isinstance(error, TimeoutError):
        return gettext("No answer within %(seconds)s seconds.") % {
            "seconds": generic_settings.STATUS_REMOTE_TIMEOUT
        }

    return str(error) or error.__class__.__name__


def level_of(status: dict[str, Any] | None) -> str:
    level = (status or {}).get("level")

    return level if status is not None and level in LEVELS else "error"


def fetch(server: StatusServer) -> dict[str, Any]:
    """The card of one monitored server: its status, or why not."""
    started = time.perf_counter()
    status = None
    error = ""

    try:
        status = read(server)
    except Exception as failure:
        error = describe(failure)
        logger.info("Status of %s unavailable: %s", server.url, error)

    if status is not None:
        # Links only ever point at a web address, whatever it sent.
        for key in ("page_url", "site_url", "api_url"):
            if not is_web_address(status.get("server", {}).get(key)):
                status.setdefault("server", {})[key] = ""

    return {
        "id": server.pk,
        "name": server.name,
        "description": server.description,
        "url": server.site_url,
        "reachable": status is not None,
        "level": level_of(status),
        "error": error,
        "status": status,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "fetched_at": timezone.now().isoformat(),
    }

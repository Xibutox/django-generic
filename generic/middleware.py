"""Middleware the framework offers. All of it optional.

``UserLanguageMiddleware`` serves each signed-in user the language they
chose, wherever they sign in from. ``CurrentUserMiddleware`` tells the
history who is changing things::

    MIDDLEWARE = [
        ...
        "django.middleware.locale.LocaleMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "generic.middleware.UserLanguageMiddleware",
        "generic.middleware.CurrentUserMiddleware",
        ...
    ]

Both must come after Django's own: the language one because Django
decides a language from the URL, the cookie or the browser first, and
both because they need to know who is asking.

Two more guard the session and the page, each turned on by a setting
(docs/security.md)::

    MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "generic.middleware.CSPMiddleware",
        ...
        "django.contrib.messages.middleware.MessageMiddleware",
        "generic.middleware.SessionIdleMiddleware",
        ...
    ]

``SessionIdleMiddleware`` signs out a session nobody has used for
``SESSION_IDLE_MINUTES``; ``CSPMiddleware`` sends the
``CONTENT_SECURITY_POLICY`` with every answer, with a nonce for the
page's own inline scripts.
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Callable

from django.http import HttpRequest, HttpResponse
from django.utils import translation
from django.utils.translation import gettext as _

from generic.conf import generic_settings
from generic.history.actor import reset_actor, set_actor
from generic.i18n import preferred_language


class UserLanguageMiddleware:
    """Let a saved language preference win over the browser's.

    Without it the language follows the browser, which is a property of
    the machine rather than of the person: the same account reads
    English on a colleague's laptop. With it, the preference travels
    with the account and the browser decides only for visitors who have
    not chosen.
    """

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        language = preferred_language(getattr(request, "user", None))

        if language:
            translation.activate(language)
            request.LANGUAGE_CODE = translation.get_language()

        response = self.get_response(request)

        if language and not response.has_header("Content-Language"):
            response.headers["Content-Language"] = translation.get_language()

        return response


class CurrentUserMiddleware:
    """Name the person behind every record written during a request.

    History is written from the model signals, which see the record and
    not the request. This puts the user in the context the recorder
    reads, for the length of the request and no longer - so a worker
    thread reused by the next request starts with nobody again.

    Without it the framework still records what changed and when; only
    the *who* is missing, which is most of the point. A project that
    writes records outside a request - a task, a command, an import -
    says who with ``generic.history.acting_as``.
    """

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        token = set_actor(getattr(request, "user", None))

        try:
            return self.get_response(request)
        finally:
            reset_actor(token)


#: Where the session keeps the time of its reader's last action.
LAST_SEEN = "generic.last_seen"

#: Sent by the pages' scripts: seconds since the reader last clicked,
#: typed or scrolled (generic/js/core.js). A refresh the page makes by
#: itself - a live table redrawn by an event - is no sign of anyone.
IDLE_HEADER = "X-Generic-Idle"

#: Answered on the request that signed a session out, so the page that
#: sent it reloads onto the sign-in page rather than showing errors.
SIGNED_OUT_HEADER = "X-Generic-Signed-Out"


class SessionIdleMiddleware:
    """Sign out a session left unused for ``SESSION_IDLE_MINUTES``.

    ``SESSION_COOKIE_AGE`` bounds a session's whole life; this bounds
    the time a screen may stay signed in with nobody in front of it
    (ISO/IEC 27002 8.5, OWASP ASVS 3.3). An action is a page opened, a
    form sent - any request - except the ones a page sends by itself:
    those carry ``X-Generic-Idle``, how long ago the reader last
    touched the page, so a live table refreshing all night keeps no
    one signed in. The sign-out is Django's ``logout()``: the security
    log records it, and the sign-in page says why.

    After ``MessageMiddleware``, for that message. The time is written
    to the session at most once a minute, not on every request.
    """

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        minutes = generic_settings.SESSION_IDLE_MINUTES
        user = getattr(request, "user", None)
        session = getattr(request, "session", None)

        if not minutes or session is None or not user:
            return self.get_response(request)

        if not user.is_authenticated:
            return self.get_response(request)

        now = int(time.time())
        before = int(session.get(LAST_SEEN) or now)

        # Whatever this request is, it comes after the silence.
        if now - before > minutes * 60:
            return self.sign_out(request, minutes)

        seen = max(before, now - self.idle_seconds(request))

        if seen - int(session.get(LAST_SEEN) or 0) >= 60:
            session[LAST_SEEN] = seen

        return self.get_response(request)

    @staticmethod
    def idle_seconds(request: HttpRequest) -> int:
        """How long the page has gone untouched; 0 for anything else."""
        value = request.headers.get(IDLE_HEADER, "")

        try:
            return max(0, int(value))
        except ValueError:
            return 0

    def sign_out(self, request: HttpRequest, minutes: int) -> HttpResponse:
        from django.contrib import messages
        from django.contrib.auth import logout

        logout(request)
        messages.info(
            request,
            _(
                "You were signed out after %(minutes)s minutes without "
                "activity."
            )
            % {"minutes": minutes},
            fail_silently=True,
        )
        response = self.get_response(request)
        response.headers[SIGNED_OUT_HEADER] = "idle"

        return response


#: The framework's own pages under a policy that lets nothing in from
#: elsewhere. 'unsafe-eval' is Alpine's: its standard build reads the
#: x- attributes with Function(). 'unsafe-inline' for styles: the pages
#: and the libraries set style attributes. WebSockets to this host are
#: added per request.
RECOMMENDED_CSP: dict[str, list[str]] = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "'unsafe-eval'", "'nonce'"],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'", "data:"],
    "connect-src": ["'self'"],
    "frame-src": ["'self'"],
    "worker-src": ["'self'", "blob:"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'self'"],
}


def csp_nonce(request: Any) -> str:
    """The request's nonce, made on first use (``{% csp_nonce %}``)."""
    nonce = getattr(request, "_generic_csp_nonce", None)

    if nonce is None:
        nonce = secrets.token_urlsafe(16)
        request._generic_csp_nonce = nonce

    return nonce


class CSPMiddleware:
    """Send ``CONTENT_SECURITY_POLICY`` with every answer.

    A script injected into a page - through a field shown unescaped, a
    library's bug - runs only if the policy allows where it comes from:
    the recommended one allows this site's own files and the inline
    scripts that carry the request's nonce, which the framework's
    templates do (``nonce="{% csp_nonce %}"``, a tag of
    ``generic_ui``). An answer that already sets a policy - a file
    served in a sandbox - keeps its own. Django 6 has its own
    (``SECURE_CSP``); this one works on 5.2 too, and knows the
    framework's pages.
    """

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        policy = policy_for(request)

        if not policy:
            return response

        header = (
            "Content-Security-Policy-Report-Only"
            if generic_settings.CONTENT_SECURITY_POLICY_REPORT_ONLY
            else "Content-Security-Policy"
        )

        if "Content-Security-Policy" not in response.headers:
            response.headers.setdefault(header, policy)

        return response


def policy_for(request: Any) -> str:
    """The header's value for this request, or ``""`` when there is none."""
    setting = generic_settings.CONTENT_SECURITY_POLICY

    if not setting:
        return ""

    directives = RECOMMENDED_CSP if setting == "recommended" else setting
    parts = []

    for name, sources in directives.items():
        values = [
            f"'nonce-{csp_nonce(request)}'" if value == "'nonce'" else value
            for value in sources
        ]

        if name == "connect-src" and "'self'" in values:
            # Older Safari reads 'self' as http(s) only: the events'
            # WebSocket to this host, named.
            host = request.get_host()
            values += [f"ws://{host}", f"wss://{host}"]

        parts.append(" ".join([name, *values]))

    return "; ".join(parts)

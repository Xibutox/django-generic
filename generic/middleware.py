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
"""

from __future__ import annotations

from typing import Callable

from django.http import HttpRequest, HttpResponse
from django.utils import translation

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

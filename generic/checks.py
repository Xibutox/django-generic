"""System checks: what plugging the framework into a project needs.

``python manage.py check`` - and every ``runserver`` - names what is
missing or out of place, with the line to write. Each message has an id
a project may silence (``SILENCED_SYSTEM_CHECKS``) when it knows why.

    generic.E001  the ``request`` context processor is missing
    generic.E002  a framework middleware runs before the authentication
    generic.E003  the REST API does not accept session authentication
    generic.E004  the site's URLs are not mounted
    generic.E005  the wiki is installed without nh3
    generic.W001  a framework middleware is missing
    generic.W002  LocaleMiddleware is missing while several languages are
    generic.W003  the framework's own endpoints are not mounted
    generic.W004  LOGIN_URL leads nowhere
    generic.W005  a WebSocket is offered but nothing serves ASGI
    generic.I001  the JavaScript catalog is not mounted
"""

from __future__ import annotations

import importlib.util
from typing import Any

from django.conf import settings
from django.core import checks
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

REQUEST_PROCESSOR = "django.template.context_processors.request"
AUTHENTICATION = "django.contrib.auth.middleware.AuthenticationMiddleware"
LOCALE = "django.middleware.locale.LocaleMiddleware"
SESSION_AUTHENTICATION = "rest_framework.authentication.SessionAuthentication"

#: The framework's middleware, and what goes missing without each.
MIDDLEWARE = {
    "generic.middleware.UserLanguageMiddleware": (
        "a user's saved language is ignored"
    ),
    "generic.middleware.CurrentUserMiddleware": (
        "the history records changes without saying who made them"
    ),
}

DOCS = "See docs/installation.md."


@checks.register(checks.Tags.templates)
def check_templates(app_configs: Any = None, **kwargs: Any) -> list:
    """Every page draws its frame from the request."""
    engines = [
        engine
        for engine in getattr(settings, "TEMPLATES", [])
        if engine.get("BACKEND", "").endswith("DjangoTemplates")
    ]

    if any(
        REQUEST_PROCESSOR
        in engine.get("OPTIONS", {}).get("context_processors", [])
        for engine in engines
    ):
        return []

    return [
        checks.Error(
            "The 'request' context processor is missing: the pages draw "
            "their frame - navigation, user, language - from it.",
            hint=f"Add {REQUEST_PROCESSOR!r} to TEMPLATES[0]['OPTIONS']"
            f"['context_processors']. {DOCS}",
            id="generic.E001",
        )
    ]


@checks.register(checks.Tags.security)
def check_middleware(app_configs: Any = None, **kwargs: Any) -> list:
    """The framework's middleware, present and after the user is known."""
    middleware = list(getattr(settings, "MIDDLEWARE", []) or [])
    messages = []

    for name, consequence in MIDDLEWARE.items():
        if name not in middleware:
            messages.append(
                checks.Warning(
                    f"{name} is not in MIDDLEWARE: {consequence}.",
                    hint=f"Add it after {AUTHENTICATION}. {DOCS}",
                    id="generic.W001",
                )
            )
        elif AUTHENTICATION in middleware and middleware.index(
            name
        ) < middleware.index(AUTHENTICATION):
            messages.append(
                checks.Error(
                    f"{name} runs before {AUTHENTICATION}: it has no user "
                    f"to read yet.",
                    hint=f"Move it after {AUTHENTICATION}. {DOCS}",
                    id="generic.E002",
                )
            )

    languages = getattr(settings, "LANGUAGES", [])

    if (
        getattr(settings, "USE_I18N", True)
        and len(languages) > 1
        and LOCALE not in middleware
    ):
        messages.append(
            checks.Warning(
                f"{LOCALE} is not in MIDDLEWARE while LANGUAGES offers "
                f"several: every page is drawn in LANGUAGE_CODE.",
                hint="Add it between the session and CommonMiddleware. "
                + DOCS,
                id="generic.W002",
            )
        )

    return messages


@checks.register()
def check_rest_framework(app_configs: Any = None, **kwargs: Any) -> list:
    """The pages call the API with the session they are signed in by."""
    configured = getattr(settings, "REST_FRAMEWORK", {}) or {}
    classes = configured.get("DEFAULT_AUTHENTICATION_CLASSES")

    # DRF's own default includes session authentication.
    if classes is None or SESSION_AUTHENTICATION in classes:
        return []

    return [
        checks.Error(
            "REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] leaves out "
            "session authentication: the pages would be refused every row "
            "and every form they ask the API for.",
            hint=f"Add {SESSION_AUTHENTICATION!r}. {DOCS}",
            id="generic.E003",
        )
    ]


@checks.register(checks.Tags.urls)
def check_urls(app_configs: Any = None, **kwargs: Any) -> list:
    """The site, its endpoints and the sign-in page are reachable."""
    from generic.sites import site

    messages = []

    try:
        reverse(f"{site.name}:index")
    except NoReverseMatch:
        return [
            checks.Error(
                "The site's URLs are not mounted: no generated page can be "
                "reached.",
                hint="Add path('', site.urls) - or path('app/', site.urls) "
                "- to the URLconf, from generic.sites import site. " + DOCS,
                id="generic.E004",
            )
        ]

    try:
        reverse("generic:preferences")
    except NoReverseMatch:
        messages.append(
            checks.Warning(
                "The framework's endpoints are not mounted: notifications, "
                "preferences, saved views and watches will not answer.",
                hint="Add path('api/generic/', include('generic.urls', "
                "namespace='generic')). " + DOCS,
                id="generic.W003",
            )
        )

    login = str(getattr(settings, "LOGIN_URL", "") or "")

    if login and ":" not in login and login.startswith("/"):
        try:
            resolve(login)
        except Resolver404:
            messages.append(
                checks.Warning(
                    f"LOGIN_URL is {login!r}, which no view answers: a "
                    f"page asking to sign in leads to a 404.",
                    hint="Set LOGIN_URL = 'site:login', the site's own "
                    "sign-in page, or point it at the project's. " + DOCS,
                    id="generic.W004",
                )
            )

    try:
        reverse("javascript-catalog")
    except NoReverseMatch:
        messages.append(
            checks.Info(
                "The JavaScript catalog is not mounted: tables, filters "
                "and forms speak English whatever the page's language.",
                hint="Add path('jsi18n/', JavaScriptCatalog.as_view("
                "packages=['generic']), name='javascript-catalog'). " + DOCS,
                id="generic.I001",
            )
        )

    return messages


@checks.register()
def check_optional_parts(app_configs: Any = None, **kwargs: Any) -> list:
    """What an optional part needs, when it is there."""
    from django.apps import apps

    from generic.conf import generic_settings

    messages = []

    if apps.is_installed("generic.wiki") and (
        importlib.util.find_spec("nh3") is None
    ):
        messages.append(
            checks.Error(
                "generic.wiki is installed but nh3 is not: the wiki cannot "
                "clean what its editor writes, and saving a page fails.",
                hint="pip install 'django-generic[wiki]'. " + DOCS,
                id="generic.E005",
            )
        )

    if (
        importlib.util.find_spec("channels") is not None
        and generic_settings.EVENTS_WEBSOCKET_URL
        and not getattr(settings, "ASGI_APPLICATION", None)
    ):
        messages.append(
            checks.Warning(
                "Channels is installed and the pages open a WebSocket, but "
                "no ASGI_APPLICATION is set: served over WSGI, every socket "
                "fails and nothing refreshes live.",
                hint="Serve the project over ASGI (docs/events.md), or set "
                "GENERIC['EVENTS_WEBSOCKET_URL'] = None. " + DOCS,
                id="generic.W005",
            )
        )

    return messages

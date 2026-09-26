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
    generic.W006  Django 6.1 or later, and MAILERS is not set
    generic.W007  a resource ranks its search without generic.search
    generic.E006  generic.tokens without knox (generic/tokens/checks.py)
    generic.E007  generic.tokens, and KNOX_TOKEN_MODEL is not its model
    generic.W008  generic.tokens, its authentication class not in DRF
    generic.E008  the OpenAPI pages without drf-spectacular
    generic.I001  the JavaScript catalog is not mounted
"""

from __future__ import annotations

import importlib.util
from typing import Any

import django
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

#: Django 6.1 configures mail with MAILERS; 7.0 sends none without it.
HAS_MAILERS = django.VERSION >= (6, 1)


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


@checks.register()
def check_mail(app_configs: Any = None, **kwargs: Any) -> list:
    """The mails the framework sends have a mailer to leave through.

    Django says so itself only in a deprecation warning, which Python
    hides; and a mail that cannot leave is logged, never raised, so the
    day it breaks nobody is told - the people who asked for mail just
    stop receiving it.
    """
    if not HAS_MAILERS or settings.is_overridden("MAILERS"):
        return []

    return [
        checks.Warning(
            "MAILERS is not set: the mails the framework sends - "
            "notifications, watches, task reports, messages - go through "
            "the EMAIL_* settings Django 6.1 deprecates, and from Django "
            "7.0 nowhere.",
            hint="Define MAILERS = {'default': {'BACKEND': ...}} in place "
            "of EMAIL_BACKEND and the EMAIL_* settings (Django's "
            "'Migrating email to mailers'). " + DOCS,
            id="generic.W006",
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

    messages.extend(check_search_rank())
    messages.extend(check_openapi())

    return messages


def check_openapi() -> list:
    """The OpenAPI pages mounted: what they need to answer."""
    from django.apps import apps

    try:
        reverse("generic_openapi:schema")
    except NoReverseMatch:
        return []

    missing = [
        name
        for name in ("drf_spectacular", "drf_spectacular_sidecar")
        if not apps.is_installed(name)
    ]
    schema_class = getattr(settings, "REST_FRAMEWORK", {}).get(
        "DEFAULT_SCHEMA_CLASS", ""
    )

    if schema_class != "drf_spectacular.openapi.AutoSchema":
        missing.append(
            "REST_FRAMEWORK['DEFAULT_SCHEMA_CLASS'] = "
            "'drf_spectacular.openapi.AutoSchema'"
        )

    if not missing:
        return []

    return [
        checks.Error(
            "generic.openapi's pages are mounted, but the description "
            "cannot be written without: " + ", ".join(missing) + ".",
            hint="pip install 'django-generic[api]' and see docs/api.md.",
            id="generic.E008",
        )
    ]


def check_search_rank() -> list:
    """``search_rank`` needs the app that installs ``pg_trgm``."""
    from django.apps import apps

    if apps.is_installed("generic.search"):
        return []

    from generic.sites import site

    return [
        checks.Warning(
            f"{type(resource).__name__} sets search_rank = True, but "
            f"generic.search is not installed: its results keep their "
            f"usual order.",
            hint="Add 'generic.search' to INSTALLED_APPS and migrate "
            "(docs/search.md), or drop search_rank.",
            obj=type(resource),
            id="generic.W007",
        )
        for resource in site.get_resources()
        if getattr(resource, "search_rank", False)
    ]

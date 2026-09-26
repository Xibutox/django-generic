"""What the example project is, whichever machine it runs on.

Everything here is the same in development and in production: the
apps, the middleware, the templates, the languages, the framework's own
configuration. What differs - the database, the secrets, DEBUG, the
security headers, the Debug Toolbar - is in ``dev.py`` and ``prod.py``,
which start with ``from .base import *``.

The helpers below read the environment. They are here rather than in a
package because a new project copies this directory and nothing else.
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import django
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

#: The repository: settings/ is two levels under it.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# -- Reading the environment -------------------------------------------


def env(name, default=""):
    """A variable of the environment, or ``default`` when it is unset
    or empty - an empty line in an env file means "not given"."""
    return os.environ.get(name) or default


def env_required(name):
    """A variable production cannot start without.

    Refusing to start is the point: a server that falls back to a
    development default for its secret key runs, and is not safe.
    """
    value = os.environ.get(name)

    if not value:
        raise ImproperlyConfigured(
            f"{name} is not set. Production reads it from the "
            f"environment - see docker/prod.env.example."
        )

    return value


def env_bool(name, default=False):
    value = os.environ.get(name)

    if not value:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default=0):
    value = os.environ.get(name)

    return int(value) if value else default


def env_list(name, default=()):
    """A comma-separated list: ``a.example.com,b.example.com``."""
    value = os.environ.get(name)

    if not value:
        return list(default)

    return [item.strip() for item in value.split(",") if item.strip()]


def database_from_url(url):
    """``DATABASES["default"]`` from a URL.

    ``postgres://user:password@host:5432/name`` for Postgres,
    ``sqlite:///relative.sqlite3`` or ``sqlite:////absolute/path`` for
    SQLite.
    """
    parsed = urlparse(url)

    if parsed.scheme in {"postgres", "postgresql", "pgsql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
        }

    if parsed.scheme == "sqlite":
        # sqlite:///name is relative to the repository, sqlite:////name
        # absolute: the path keeps one slash of the three or four.
        path = unquote(parsed.path)

        if path.startswith("//"):
            name = Path(path[1:])
        else:
            name = BASE_DIR / path.lstrip("/")

        return {"ENGINE": "django.db.backends.sqlite3", "NAME": name}

    raise ImproperlyConfigured(
        f"DATABASE_URL: '{parsed.scheme}' is not a database this project "
        f"knows. Use postgres://... or sqlite:///..."
    )


#: How long the channel layer waits on a Redis reply. channels-redis
#: asks Redis for a socket's next event and waits up to 5 seconds for
#: it; redis-py 8 gives up on any reply after 5 seconds by default. The
#: two race, and the socket loses: a page left quiet has its WebSocket
#: closed with a TimeoutError every few seconds, and misses what is
#: sent until it reconnects. Longer than that wait, not unbounded: a
#: Redis that stops answering is still noticed.
CHANNEL_LAYER_SOCKET_TIMEOUT = 15


def redis_backends(url):
    """The channel layer and the cache, on Redis.

    The in-memory channel layer is per process: with more than one
    worker, only the one holding the socket would see an event. Redis
    is what makes events work on more than one process.
    """
    return (
        {
            "default": {
                "BACKEND": "channels_redis.core.RedisChannelLayer",
                "CONFIG": {
                    "hosts": [
                        {
                            "address": url,
                            "socket_timeout": CHANNEL_LAYER_SOCKET_TIMEOUT,
                        }
                    ]
                },
            }
        },
        {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": url,
            }
        },
    )


def mail_settings(backend, **options):
    """The settings sending mail through ``backend``, on either Django.

    Django 6.1 configures mail with ``MAILERS`` and deprecates
    ``EMAIL_BACKEND`` and the other ``EMAIL_*`` settings - and refuses
    to start with both. 5.2, the oldest this project runs on, reads
    only the latter. ``options`` take MAILERS' names (``host``,
    ``port``, ``username``, ``password``, ``use_tls``...) and become
    the old settings where those are what Django reads::

        globals().update(mail_settings(SMTP, host="smtp.example.com"))

    Once 5.2 is left behind, write ``MAILERS`` instead.
    """
    if django.VERSION >= (6, 1):
        mailer = {"BACKEND": backend}

        if options:
            mailer["OPTIONS"] = options

        return {"MAILERS": {"default": mailer}}

    legacy = {
        "host": "EMAIL_HOST",
        "port": "EMAIL_PORT",
        "username": "EMAIL_HOST_USER",
        "password": "EMAIL_HOST_PASSWORD",
        "use_tls": "EMAIL_USE_TLS",
        "use_ssl": "EMAIL_USE_SSL",
        "timeout": "EMAIL_TIMEOUT",
        "ssl_certfile": "EMAIL_SSL_CERTFILE",
        "ssl_keyfile": "EMAIL_SSL_KEYFILE",
        "file_path": "EMAIL_FILE_PATH",
    }
    unknown = sorted(set(options) - set(legacy))

    if unknown:
        raise ImproperlyConfigured(
            f"Mail option {', '.join(unknown)}: Django "
            f"{django.get_version()} has no EMAIL_* setting for it."
        )

    return {
        "EMAIL_BACKEND": backend,
        **{legacy[name]: value for name, value in options.items()},
    }


# -- Applications ------------------------------------------------------

INSTALLED_APPS = [
    # First, and before staticfiles: it replaces runserver with one
    # that speaks ASGI, so `manage.py runserver` serves the WebSocket
    # events and the static files at the same time. Without it,
    # runserver is WSGI-only and every socket is silently dropped.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # --- required by the framework ---
    "channels",
    "rest_framework",
    "generic",
    # --- optional: the wiki ---
    "generic.wiki",
    # --- this example ---
    "example",
]

# --- optional: schedules, managed from the Tasks group ---
# Its models are the ones the Django admin plugin shows; the framework
# declares them as resources instead. Added only when it is installed,
# so `pip install -e ".[export,events,tasks,wiki,dev]"` still runs the
# example - the task pages work without a scheduler, minus the
# schedules.
try:
    import django_celery_beat  # noqa: F401

    INSTALLED_APPS.insert(
        INSTALLED_APPS.index("example"), "django_celery_beat"
    )
except ImportError:
    pass

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Between the session and Common, as Django requires: it settles on
    # a language from the cookie or the browser.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # After the authentication: a signed-in user's saved language wins
    # over the browser's, so the choice follows the account.
    "generic.middleware.UserLanguageMiddleware",
    # Also after it: what every record's history records as the who.
    "generic.middleware.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "example_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "example_project.wsgi.application"
ASGI_APPLICATION = "example_project.asgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -- Internationalisation ----------------------------------------------
#
# Narrow LANGUAGES to what the project actually translated: the frame
# offers a language menu built from this list, and Django's default -
# every language it ships - would be a hundred entries no one wrote.

LANGUAGE_CODE = "en-us"
LANGUAGES = [
    ("en", _("English")),
    ("fr", _("French")),
]
#: Where this project's own catalogs live; the framework ships its own
#: under ``generic/locale/``, found because it is an installed app.
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

# -- Static ------------------------------------------------------------
#
# Where `collectstatic` gathers the files for the web server. In
# development nothing is collected: runserver serves them from the apps.

STATIC_URL = "/static/"
STATIC_ROOT = Path(env("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))

# -- Authentication ----------------------------------------------------
#
# The site brings its own sign-in page; a route name works here.

LOGIN_URL = "site:login"
LOGIN_REDIRECT_URL = "/"

# Django's own, and worth having: they are what the People screens
# check a password against when an administrator sets one for somebody
# else. A project that declares none accepts anything.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
        "UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation."
        "MinimumLengthValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation."
        "CommonPasswordValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation."
        "NumericPasswordValidator"
    },
]

# -- REST framework ----------------------------------------------------
#
# The framework's viewsets declare their own renderers, pagination and
# filter backends, so nothing here can change table behaviour by
# accident. Only authentication and permissions are project-wide.

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# -- The framework -----------------------------------------------------
#
# Every setting has a default; these are only the ones this example
# changes. See docs/settings.md.

GENERIC = {
    "SITE_TITLE": "Support desk",
    "SITE_ICON": "support_agent",
    # The address the site is reached at, for the links in the mails it
    # sends. Production sets it; in development the mails go to the
    # console, where a relative link is enough.
    "SITE_URL": env("DJANGO_SITE_URL") or None,
    "TABLE_PAGE_SIZE": 15,
    "AUTOCOMPLETE_PAGE_SIZE": 20,
    # Shown in the navigation's footer and on the help page. The help
    # page finds LICENSE and CHANGELOG.md by itself.
    "VERSION": "1.0.0",
    "HELP_TEXT": (
        "A support desk built on django-generic: tickets, customers, "
        "teams and the time spent on them. Every screen here is "
        "declared in example/resources.py."
    ),
    "HELP_LINKS": [
        {
            "label": "Feature guide",
            "url": "/demo/",
            "icon": "menu_book",
            "description": "Each feature, and what to try.",
        },
        {
            "label": "Wiki",
            "url": "/wiki/",
            "icon": "auto_stories",
            "description": "What the desk writes down for itself.",
        },
    ],
}

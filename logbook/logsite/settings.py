"""The logbook: notes, the tasks written in them, and the time they took.

A planner on django-generic: notes written line by line - plain lines,
headings, bullets, to-dos, and task lines that become tasks (FNC, a
ticket to fix; DM, an evolution to build) - the tasks on a kanban
board, the time spent on each logged by a timer or placed on an hourly
calendar, then checked there. For local use only: the secret key is
written here and DEBUG is on, unless the environment says otherwise.
Built like the minimal example and the document manager - one settings
file, no real time, plain WSGI - so it runs anywhere ``runserver``
does.
"""

import os
from pathlib import Path

import django
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "logbook-example-local-only")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1"
).split(",")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",  # the framework's
    "generic",  # the framework's
    "planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # The Content-Security-Policy: nothing from elsewhere runs.
    "generic.middleware.CSPMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # After the session, before the common middleware: the language of
    # the page, from the cookie or the browser.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # The framework's two, after the authentication: they read the user.
    "generic.middleware.UserLanguageMiddleware",
    "generic.middleware.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "logsite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                # Required: every page draws its frame from the request.
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "logsite.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH") or BASE_DIR / "db.sqlite3",
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# English and French, the framework's two: the account menu switches.
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English")), ("fr", _("French"))]
USE_I18N = True
USE_TZ = True
TIME_ZONE = "Europe/Paris"
LOCALE_PATHS = [BASE_DIR / "planner" / "locale"]

STATIC_URL = "/static/"
STATIC_ROOT = os.environ.get("DJANGO_STATIC_ROOT") or (
    BASE_DIR / "staticfiles"
)

LOGIN_URL = "site:login"
LOGIN_REDIRECT_URL = "/"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

CONSOLE_MAIL = "django.core.mail.backends.console.EmailBackend"

if django.VERSION >= (6, 1):
    MAILERS = {"default": {"BACKEND": CONSOLE_MAIL}}
else:
    EMAIL_BACKEND = CONSOLE_MAIL

GENERIC = {
    "SITE_TITLE": "Logbook",
    "SITE_ICON": "edit_note",
    "CONTENT_SECURITY_POLICY": "recommended",
    "THEME": {"--ui-hue": "175"},
    "EVENTS_WEBSOCKET_URL": None,
}

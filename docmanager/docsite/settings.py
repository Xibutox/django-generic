"""The document manager: django-generic as a document management system.

Teams each with their own documents (``generic.teams``), documents
filed in folders, every file kept as a version with its author, date
and change note, and the wiki. For local use only: the secret key is
written here and DEBUG is on. Built like the minimal example - one
settings file, no real time, plain WSGI - so it runs anywhere
``runserver`` does; the full example's production settings and Docker
stack (``example_project/``, ``docker/``) apply unchanged when it
grows up.
"""

import os
from pathlib import Path

import django
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "docmanager-example-local-only"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",  # the framework's
    "generic",  # the framework's
    "generic.teams",  # records split between teams (docs/teams.md)
    "generic.wiki",  # the wiki: needs the extra, pip install ".[wiki]"
    "documents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

ROOT_URLCONF = "docsite.urls"

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

WSGI_APPLICATION = "docsite.wsgi.application"

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

STATIC_URL = "/static/"

# Where the documents' files are written, every version of them. No
# MEDIA_URL: each file is served through the API, to who may see it.
MEDIA_ROOT = os.environ.get("DJANGO_MEDIA_ROOT") or BASE_DIR / "media"

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
    "SITE_TITLE": "Documents",
    "SITE_ICON": "folder_open",
    "THEME": {"--ui-hue": "250"},
    "EVENTS_WEBSOCKET_URL": None,
    # Office files are larger than the framework's 10 MB default.
    "FILE_MAX_SIZE": 50 * 1024 * 1024,
    # A team's wiki is its members' only; a wiki of no team, everyone's.
    "WIKI_ACCESS": "documents.wikis.wikis_of_my_teams",
}

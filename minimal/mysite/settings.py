"""The least a Django project needs to run django-generic.

A ``django-admin startproject`` settings file, trimmed, with the
framework's lines marked, the wiki, and - when its environment variables
are set - signing in with Microsoft through django-allauth. For local
use only: the secret key is written here and DEBUG is on. Everything
the full example adds - real time, API tokens, Celery, production
settings - is in ``example_project/``.
"""

import os
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "minimal-example-local-only"
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
    "generic.wiki",  # the wiki: needs the extra, pip install ".[wiki]"
    "library",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # The framework's two, after the authentication: they read the user.
    "generic.middleware.UserLanguageMiddleware",
    "generic.middleware.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mysite.urls"

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

WSGI_APPLICATION = "mysite.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        # Beside manage.py, or where the Docker image says: a volume.
        "NAME": os.environ.get("DJANGO_DB_PATH") or BASE_DIR / "db.sqlite3",
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# One language, so no language menu and no LocaleMiddleware.
LANGUAGE_CODE = "en-us"
LANGUAGES = [("en", "English")]
USE_I18N = True
USE_TZ = True
TIME_ZONE = "UTC"

STATIC_URL = "/static/"

# Where uploaded files are written: the wiki's images. Beside manage.py,
# or in the Docker image's volume. No MEDIA_URL: each image is served
# through the wiki, to whoever is signed in.
MEDIA_ROOT = os.environ.get("DJANGO_MEDIA_ROOT") or BASE_DIR / "media"

# The site's own sign-in page.
LOGIN_URL = "site:login"
LOGIN_REDIRECT_URL = "/"

# The pages call the API with the session they are signed in by.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# Mail - notifications, password resets - printed to the console. Django
# 6.1 configures it with MAILERS, and refuses it beside EMAIL_BACKEND.
CONSOLE_MAIL = "django.core.mail.backends.console.EmailBackend"

if django.VERSION >= (6, 1):
    MAILERS = {"default": {"BACKEND": CONSOLE_MAIL}}
else:
    EMAIL_BACKEND = CONSOLE_MAIL

# Everything has a default (docs/settings.md). No live updates: the
# pages open no WebSocket, so plain WSGI and runserver serve them all.
GENERIC = {
    "SITE_TITLE": "Library",
    "EVENTS_WEBSOCKET_URL": None,
}

# Signing in with Microsoft (Entra ID), through django-allauth - only
# where an app registration is given, so without one the example runs
# without allauth installed, and the sign-in page is the password form.
# Needs pip install "django-allauth[socialaccount]"; the registration is
# in README.md.
MICROSOFT_CLIENT_ID = os.environ.get("MICROSOFT_CLIENT_ID", "")

if MICROSOFT_CLIENT_ID:
    INSTALLED_APPS += [
        "allauth",
        "allauth.account",
        "allauth.socialaccount",
        "allauth.socialaccount.providers.microsoft",
    ]
    MIDDLEWARE += ["allauth.account.middleware.AccountMiddleware"]
    AUTHENTICATION_BACKENDS = [
        # The password form, as before.
        "django.contrib.auth.backends.ModelBackend",
        # Accounts signed in by Microsoft.
        "allauth.account.auth_backends.AuthenticationBackend",
    ]
    SOCIALACCOUNT_PROVIDERS = {
        "microsoft": {
            "APPS": [
                {
                    "client_id": MICROSOFT_CLIENT_ID,
                    "secret": os.environ.get("MICROSOFT_CLIENT_SECRET", ""),
                    # The directory's id for one organisation's
                    # accounts; "organizations" or "common" for more.
                    "settings": {
                        "tenant": os.environ.get(
                            "MICROSOFT_TENANT_ID", "organizations"
                        ),
                    },
                }
            ],
        }
    }
    # The sign-in page's button is a link: follow it straight to
    # Microsoft rather than to allauth's own "Continue" page.
    SOCIALACCOUNT_LOGIN_ON_GET = True
    # Microsoft has checked the address; an account is made at the first
    # sign-in, with no permissions until it is given a group.
    SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
    SOCIALACCOUNT_AUTO_SIGNUP = True

    # The framework's part: the button, first on the sign-in page. The
    # route is allauth's (mysite/urls.py mounts it under accounts/).
    GENERIC["SSO_PROVIDERS"] = [
        {
            "label": "Microsoft",
            "route": "microsoft_login",
            "icon": "corporate_fare",
            "description": "Use your work or school account.",
        }
    ]

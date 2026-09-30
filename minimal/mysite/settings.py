"""The least a Django project needs to run django-generic.

A ``django-admin startproject`` settings file, trimmed, with the
framework's lines marked. For local use only: the secret key is
written here and DEBUG is on. Everything the full example adds - real
time, the wiki, API tokens, Celery, Docker, production settings - is in
``example_project/``.
"""

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
        "NAME": BASE_DIR / "db.sqlite3",
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

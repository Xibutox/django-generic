"""Settings for the test project.

Two modes, one file. By default everything is in-process - SQLite and an
in-memory channel layer - so the suite runs anywhere with no services to
start. Set ``DATABASE_URL`` and ``REDIS_URL`` (the Docker compose stack
does) and the same suite runs against Postgres and Redis instead.
"""

import atexit
import os
import shutil
import tempfile
from urllib.parse import urlparse

import django

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "test-only-not-a-secret",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "").lower() in {"1", "true"}
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "generic",
    "generic.wiki",
    "generic.docx",
    # Accent-insensitive search: installed, as a project would, so the
    # suite runs every search through it - on SQLite and on PostgreSQL.
    "generic.search",
    # The API for scripts: tokens, and its OpenAPI description.
    "knox",
    "generic.tokens",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "tests.testapp",
    # Covered by the suite too: the example is a deliverable, and a
    # broken example is a broken promise.
    "example",
]

# The scheduler is optional, and the framework has to work either way.
# Where it is installed the suite covers its screens as well; where it
# is not, those tests skip and the rest is unaffected.
try:  # pragma: no cover - a property of the environment, not the code
    import django_celery_beat  # noqa: F401

    INSTALLED_APPS.append("django_celery_beat")
except ImportError:
    pass

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "generic.middleware.UserLanguageMiddleware",
    "generic.middleware.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "tests.urls"

# The classic views' tests follow Django's default LOGIN_URL on purpose,
# and the suite serves no WebSocket: both are what the framework's own
# checks rightly say about a project - this one is a test bench.
SILENCED_SYSTEM_CHECKS = ["generic.W004", "generic.W005"]

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

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    _database = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _database.path.lstrip("/"),
            "USER": _database.username or "",
            "PASSWORD": _database.password or "",
            "HOST": _database.hostname or "",
            "PORT": str(_database.port or ""),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
# What the framework ships translations for, which is what the language
# menu and the preference offer.
LANGUAGES = [
    ("en", "English"),
    ("fr", "French"),
]
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"

# Uploaded files land in a folder of the run's own, removed at the end:
# never in the checkout. A test writing files still points MEDIA_ROOT at
# its own tmp_path, so what it finds there is only what it wrote.
MEDIA_ROOT = tempfile.mkdtemp(prefix="generic-tests-media-")
atexit.register(shutil.rmtree, MEDIA_ROOT, True)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "generic.tokens.authentication.TokenAuthentication",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

REDIS_URL = os.environ.get("REDIS_URL")

if REDIS_URL:
    # The in-memory layer is per process: with more than one worker,
    # only the worker holding the socket would see the event.
    # A read allowed longer than the 5 seconds channels-redis waits on
    # Redis for the next message: redis-py 8 gives up after 5 by
    # default (see example_project/settings/base.py).
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [{"address": REDIS_URL, "socket_timeout": 15}]
            },
        }
    }
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

# Whatever the environment says - the Docker stack sets
# CELERY_BROKER_URL for its own worker - a task the suite sends through
# Celery runs here: a worker would not see the test database.
CELERY_BROKER_URL = "memory://"
CELERY_TASK_ALWAYS_EAGER = True

# The suite's mail lands in django.core.mail.outbox whatever is written
# here: the test runner swaps every mailer for the in-memory one. From
# Django 6.1 there has to be a mailer to swap - without MAILERS, every
# mail sent warns that Django 7.0 will have nowhere to send it. Before
# 6.1 the runner swaps EMAIL_BACKEND, which needs nothing.
if django.VERSION >= (6, 1):
    MAILERS = {
        "default": {
            "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
        }
    }

# Framework configuration under test.
GENERIC = {
    "TABLE_PAGE_SIZE": 10,
    "TABLE_MAX_PAGE_SIZE": 100,
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# The People screens check a password against the project's own
# validators; the suite covers that, so the suite declares some.
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

LOGGING_CONFIG = None

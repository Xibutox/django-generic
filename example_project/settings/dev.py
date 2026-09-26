"""Development: DEBUG on, and nothing to start but Django.

``manage.py`` and ``celery.py`` use this module unless told otherwise.
It runs on SQLite and an in-memory channel layer, so ``runserver``
needs no services. Set ``DATABASE_URL`` and ``REDIS_URL`` and the same
settings run on Postgres and Redis instead - which is what
``docker/docker-compose.dev.yml`` does.
"""

import importlib.util
import os
import sys
from pathlib import Path

from .base import *  # noqa: F401,F403
from .base import (
    INSTALLED_APPS,
    MIDDLEWARE,
    database_from_url,
    env,
    mail_settings,
    redis_backends,
)

DEBUG = True
# Development only, and said so: production refuses to start without
# its own (see prod.py).
SECRET_KEY = env("DJANGO_SECRET_KEY", "example-project-only-not-a-secret")
ALLOWED_HOSTS = ["*"]

# -- Database ----------------------------------------------------------

DATABASES = {
    "default": database_from_url(
        env("DATABASE_URL", "sqlite:///example.sqlite3")
    )
}

# -- Events and cache --------------------------------------------------
#
# In memory unless Redis is given. One process then, which is what
# runserver is.

REDIS_URL = env("REDIS_URL")

if REDIS_URL:
    CHANNEL_LAYERS, CACHES = redis_backends(REDIS_URL)
else:
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }

# -- Celery ------------------------------------------------------------
#
# Without a broker, a task runs in the request that sends it: nothing
# else to start, and an error shows where it happened.

CELERY_BROKER_URL = env("CELERY_BROKER_URL", "memory://")
CELERY_TASK_ALWAYS_EAGER = not env("CELERY_BROKER_URL")

# -- Mail --------------------------------------------------------------
#
# Printed by runserver rather than sent: the notifications that go by
# mail can be read without a mail server. MAILERS from Django 6.1,
# EMAIL_BACKEND before - see mail_settings in base.py.

globals().update(
    mail_settings("django.core.mail.backends.console.EmailBackend")
)

# -- Django Debug Toolbar ----------------------------------------------
#
# The panel on the side of every page: the SQL a page ran and how long
# it took, the templates it drew and their context, the cache, the
# signals, the headers. Its History panel also lists the API calls the
# tables and forms make, which is where most of this framework's
# queries run. Only when it is installed (the "dev" extra), never under
# a test runner, and DEBUG_TOOLBAR=0 turns it off.

DEBUG_TOOLBAR = (
    importlib.util.find_spec("debug_toolbar") is not None
    and "PYTEST_VERSION" not in os.environ
    and sys.argv[1:2] != ["test"]
    and env("DEBUG_TOOLBAR", "1") != "0"
)

if DEBUG_TOOLBAR:
    # New lists, not base's changed in place: base is shared, and
    # production must never inherit what development added to it.
    INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
    # As early as it can be: it has to see the response last, after
    # every other middleware has had its say. Nothing here compresses
    # the response, which would have to come first.
    MIDDLEWARE = [
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        *MIDDLEWARE,
    ]
    # Whose requests get the toolbar: this machine's. In a container
    # the browser is the host, seen as the network's gateway - which
    # the toolbar's own Docker callback recognises. Outside one, that
    # callback would let in whatever came through the router, so it is
    # only used where Docker says it runs.
    INTERNAL_IPS = ["127.0.0.1", "::1"]
    DEBUG_TOOLBAR_CONFIG = {
        "SHOW_TOOLBAR_CALLBACK": (
            "debug_toolbar.middleware.show_toolbar_with_docker"
            if Path("/.dockerenv").exists()
            else "debug_toolbar.middleware.show_toolbar"
        ),
        # A tab on the edge of the page until it is asked for, rather
        # than a panel over the navigation on every page.
        "SHOW_COLLAPSED": True,
    }

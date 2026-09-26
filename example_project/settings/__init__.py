"""The example project's settings, one module per way it runs.

    base.py   what the project is, wherever it runs
    dev.py    DEBUG, SQLite and in-memory by default, the Debug Toolbar
    prod.py   everything from the environment, HTTPS, Postgres, Redis

``manage.py`` and ``celery.py`` default to ``dev``, what a developer
types; ``asgi.py`` and ``wsgi.py`` default to ``prod``, what a server
imports. ``DJANGO_SETTINGS_MODULE`` chooses otherwise.
"""

import os

from django.core.exceptions import ImproperlyConfigured

# The package itself is not a settings module: Django would take it,
# find no setting in it and run on its defaults - no apps, no database.
# That is what an environment still naming the single settings.py of
# earlier versions would do, so it is refused by name.
if os.environ.get("DJANGO_SETTINGS_MODULE") == __name__:
    raise ImproperlyConfigured(
        f"DJANGO_SETTINGS_MODULE={__name__} names the package, not a "
        f"mode: use {__name__}.dev or {__name__}.prod."
    )

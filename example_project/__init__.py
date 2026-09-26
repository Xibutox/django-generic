"""The example project: settings, URLs, the servers' entry points and
the Celery application.

The Celery application is imported here, as Celery's own guide for
Django does, so that every process of the project has it: the web
server, a ``manage.py`` command, the worker. Without this line nothing
but the worker ever imports ``celery.py``; a task started from a page
then finds no broker configured and runs in the request that started
it, while the worker waits for work that never comes.
"""

import importlib.util

# Only with the "tasks" extra. Without Celery, a declared task runs in
# the process that starts it, which is what it would do anyway.
if importlib.util.find_spec("celery") is not None:
    from .celery import app as celery_app

    __all__ = ["celery_app"]

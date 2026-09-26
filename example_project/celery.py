"""Celery application.

Celery runs as a Python package inside the Django image rather than in
an image of its own: same code, same dependencies, one build.

The development settings by default, like manage.py: the production
stack names its settings module for every service.
"""

import os

from celery import Celery

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "example_project.settings.dev",
)

app = Celery("example")

# Every CELERY_* Django setting becomes a Celery setting.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

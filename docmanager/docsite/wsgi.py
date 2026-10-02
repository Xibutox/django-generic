"""WSGI entry point of the document manager."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docsite.settings")

application = get_wsgi_application()

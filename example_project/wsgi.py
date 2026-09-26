"""WSGI application.

Serves the HTTP half only. The events module needs ASGI; see asgi.py.

Production settings by default, as for asgi.py: a server started
without DJANGO_SETTINGS_MODULE must not run with DEBUG on.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "example_project.settings.prod",
)

application = get_wsgi_application()

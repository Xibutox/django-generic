"""ASGI application: HTTP plus the WebSocket events.

Copy this into your own project. Serve it with an ASGI server - Daphne
or Uvicorn. A WSGI server will serve the REST API perfectly well and
silently drop every socket.

Production settings by default: a server started without
DJANGO_SETTINGS_MODULE must never run with DEBUG on. `manage.py
runserver` uses the development settings, and so can a server started
by hand - DJANGO_SETTINGS_MODULE=example_project.settings.dev.
"""

import os

from django.conf import settings
from django.core.asgi import get_asgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "example_project.settings.prod",
)

# Built first: it populates the app registry, and the imports below
# reach models through it.
django_asgi_application = get_asgi_application()

http_application = django_asgi_application

if settings.DEBUG:
    # Static files are served by the application itself in development.
    #
    # `manage.py runserver` does this for you, but running an ASGI
    # server directly with the development settings does not, and the
    # result is a page that loads with no styling at all and 404s on
    # every asset.
    #
    # In production the web server in front serves STATIC_ROOT instead
    # (docker/Caddyfile), which is why this is behind DEBUG.
    from django.contrib.staticfiles.handlers import (
        ASGIStaticFilesHandler,
    )

    http_application = ASGIStaticFilesHandler(django_asgi_application)

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import (  # noqa: E402
    AllowedHostsOriginValidator,
)

from generic.events.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": http_application,
        # AllowedHostsOriginValidator is what stops another site from
        # opening a socket with your users' cookies attached.
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)

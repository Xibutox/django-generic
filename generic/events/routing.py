"""WebSocket routes.

Wire them into the project's ASGI application::

    from channels.auth import AuthMiddlewareStack
    from channels.routing import ProtocolTypeRouter, URLRouter
    from generic.events.routing import websocket_urlpatterns

    application = ProtocolTypeRouter({
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        ),
    })
"""

from __future__ import annotations

from django.urls import path

from generic.events.consumers import EventConsumer

websocket_urlpatterns = [
    path("ws/events/", EventConsumer.as_asgi(), name="generic-events"),
]

"""``schema/`` and ``docs/``: the OpenAPI description, and its pages.

Mount under ``api/``, before ``site.urls``::

    path("api/", include("generic.openapi.urls")),

Both need a signed-in reader - a session, or a token - and describe
only what that reader may use.
"""

from typing import Any

from django.templatetags.static import static
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import IsAuthenticated

from generic.conf import generic_settings


class DocsView(SpectacularSwaggerView):
    """Swagger UI, from the files drf-spectacular-sidecar ships.

    Never from a CDN, whatever ``SPECTACULAR_SETTINGS`` says: the
    framework serves every file itself.
    """

    permission_classes = [IsAuthenticated]

    @property
    def title(self) -> str:  # type: ignore[override]
        return f"{generic_settings.SITE_TITLE} API"

    @staticmethod
    def _swagger_ui_resource(filename: str) -> Any:
        return static(f"drf_spectacular_sidecar/swagger-ui-dist/{filename}")

    @staticmethod
    def _swagger_ui_favicon() -> Any:
        return static(
            "drf_spectacular_sidecar/swagger-ui-dist/favicon-32x32.png"
        )


app_name = "generic_openapi"

urlpatterns = [
    path(
        "schema/",
        SpectacularAPIView.as_view(
            serve_public=False, permission_classes=[IsAuthenticated]
        ),
        name="schema",
    ),
    path(
        "docs/",
        DocsView.as_view(url_name="generic_openapi:schema"),
        name="docs",
    ),
]

"""Example project routes."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from generic.sites import site

urlpatterns = [
    # Kept alongside, not replaced: the admin stays useful for staff and
    # DBA work while the generic screens serve the people using the app.
    path("admin/", admin.site.urls),
    # Translates the framework's JavaScript. Optional - without it the
    # controls fall back to their English source strings.
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic"]),
        name="javascript-catalog",
    ),
    # The framework's own endpoints: notifications, preferences,
    # watches and saved table views.
    path("api/generic/", include("generic.urls", namespace="generic")),
    # The wiki: pages, their editor and their API.
    path("wiki/", include("generic.wiki.urls")),
    # Word files merged with a template: the page; its endpoint is in
    # generic.urls, under api/generic/docx/merge/.
    path("docx/", include("generic.docx.urls")),
    # The API described for scripts: api/schema/ (OpenAPI) and
    # api/docs/ (Swagger UI), for signed-in readers, token or session.
    path("api/", include("generic.openapi.urls")),
    # The hand-written REST endpoints the classic pages use.
    path("api/", include("example.api_urls", namespace="example_api")),
    # The classic, server-rendered views, kept for comparison.
    path("demo/", include("example.urls", namespace="example")),
    # Everything generated from example/resources.py: the dashboard,
    # sign in and account pages, every resource's pages and API.
    path("", site.urls),
]

# The Debug Toolbar's own pages, when the settings turned it on. First,
# so no pattern of the site's can shadow them.
if getattr(settings, "DEBUG_TOOLBAR", False):
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns = debug_toolbar_urls() + urlpatterns

"""{{ title }}: the routes."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog
from generic.sites import site

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic"]),
        name="javascript-catalog",
    ),
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("wiki/", include("generic.wiki.urls")),
    # Everything generated from the resources.py files: the dashboard,
    # sign in and account pages, every resource's pages and API. Last.
    path("", site.urls),
]

if getattr(settings, "DEBUG_TOOLBAR", False):
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns = debug_toolbar_urls() + urlpatterns

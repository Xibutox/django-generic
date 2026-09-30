"""The minimal example's routes: the framework's endpoints, then the
site generated from library/resources.py, last."""

from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from generic.sites import site

urlpatterns = [
    # The browser side's strings: the tables, filters and forms.
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic"]),
        name="javascript-catalog",
    ),
    # Notifications, preferences, saved table views.
    path("api/generic/", include("generic.urls", namespace="generic")),
    # The dashboard, sign-in and account pages, and every resource's
    # pages and API.
    path("", site.urls),
]

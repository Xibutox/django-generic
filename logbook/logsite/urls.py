"""The logbook's routes: the framework's endpoints, then the site
generated from planner/resources.py, last."""

from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from generic.sites import site

urlpatterns = [
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic", "planner"]),
        name="javascript-catalog",
    ),
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("", site.urls),
]

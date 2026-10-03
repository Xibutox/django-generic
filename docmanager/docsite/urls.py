"""The document manager's routes: the framework's endpoints, the wiki,
then the site generated from documents/resources.py, last."""

from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from generic.sites import site

urlpatterns = [
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic"]),
        name="javascript-catalog",
    ),
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("wiki/", include("generic.wiki.urls")),
    path("", site.urls),
]

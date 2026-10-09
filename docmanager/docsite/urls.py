"""The document manager's routes: the framework's endpoints, the wiki,
then the site generated from documents/resources.py, last."""

from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from documents.upload_merge import ROUTE, UploadMergePage
from generic.sites import site

urlpatterns = [
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic"]),
        name="javascript-catalog",
    ),
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("wiki/", include("generic.wiki.urls")),
    # Answers 404 unless DOCUMENT_UPLOAD_MERGE is on (settings.py).
    path(
        "merge-uploads/",
        UploadMergePage.as_view(site=site),
        name=ROUTE,
    ),
    path("", site.urls),
]

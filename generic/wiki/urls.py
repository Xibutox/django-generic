"""The wikis, their pages and their API. Mount under ``wiki/``::

path("wiki/", include("generic.wiki.urls")),

``wiki/`` lists the wikis, ``wiki/<wiki>/`` opens one at its first
page, ``wiki/<wiki>/<page>/`` is a page and ``wiki/<wiki>/export.pdf``
the whole wiki as a PDF.

The editor uploads its images to ``api/generic/wiki/images/``, in
``generic.urls``; they are shown from ``images/<id>/`` here, so their
address follows wherever the wiki is mounted.
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from generic.wiki import api, views

app_name = "generic_wiki"

router = SimpleRouter()
router.register("wikis", api.WikiViewSet, basename="wiki")
router.register("pages", api.WikiPageViewSet, basename="page")

urlpatterns = [
    path("", views.WikiListView.as_view(), name="index"),
    # Before the wikis: "api", "images" and "files" are reserved.
    path("api/", include(router.urls)),
    path("images/<int:pk>/", views.WikiImageView.as_view(), name="image"),
    path("files/<int:pk>/", views.WikiFileView.as_view(), name="file"),
    # A page's address never holds a dot: this is never a page.
    path("<str:wiki>/export.pdf", views.WikiPdfView.as_view(), name="pdf"),
    path("<str:wiki>/", views.WikiIndexView.as_view(), name="wiki"),
    path("<str:wiki>/<str:slug>/", views.WikiPageView.as_view(), name="page"),
]

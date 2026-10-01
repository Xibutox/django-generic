"""The wiki's pages and its API. Mount under ``wiki/``::

path("wiki/", include("generic.wiki.urls")),

The editor uploads its images to ``api/generic/wiki/images/``, in
``generic.urls``; they are shown from ``images/<id>/`` here, so their
address follows wherever the wiki is mounted.
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from generic.wiki import api, views

app_name = "generic_wiki"

router = SimpleRouter()
router.register("pages", api.WikiPageViewSet, basename="page")

urlpatterns = [
    path("", views.WikiIndexView.as_view(), name="index"),
    # Before the pages: "api" is a reserved address.
    path("api/", include(router.urls)),
    path("images/<int:pk>/", views.WikiImageView.as_view(), name="image"),
    path("files/<int:pk>/", views.WikiFileView.as_view(), name="file"),
    path("<str:slug>/", views.WikiPageView.as_view(), name="page"),
]

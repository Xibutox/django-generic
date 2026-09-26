"""The wiki's pages and its API. Mount under ``wiki/``::

path("wiki/", include("generic.wiki.urls")),
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
    path("<str:slug>/", views.WikiPageView.as_view(), name="page"),
]

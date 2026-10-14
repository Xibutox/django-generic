"""``tests.urls`` with the site's pages built again: for a screen
registered after start-up - the Access requests, which a project giving
a right on request has from the start."""

from generic.sites import site
from tests.urls import urlpatterns as base

from django.urls import path  # isort: skip

urlpatterns = [
    *(
        pattern
        for pattern in base
        if getattr(pattern, "namespace", None) != site.name
    ),
    path("", site.urls),
]

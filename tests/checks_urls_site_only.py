"""A URLconf with the site and nothing else: the framework's endpoints
and the JavaScript catalog are missing (generic.W003, generic.I001)."""

from django.urls import path

from generic.sites import site

urlpatterns = [path("", site.urls)]

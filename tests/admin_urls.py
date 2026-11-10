"""``tests.urls`` with Django's admin mounted beside the site, as a
project keeping it does."""

from django.contrib import admin
from django.urls import path

from tests.urls import urlpatterns as base

urlpatterns = [path("admin/", admin.site.urls), *base]

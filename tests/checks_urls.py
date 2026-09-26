"""A URLconf that forgot the site: what generic.E004 is about."""

from django.urls import path
from django.views.generic import TemplateView

urlpatterns = [path("", TemplateView.as_view(template_name="x.html"))]

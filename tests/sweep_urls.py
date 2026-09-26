"""A URLconf with a page whose address no sweep knows how to fill."""

from django.urls import include, path
from django.views.generic import TemplateView

from tests.urls import urlpatterns as project

urlpatterns = [
    path(
        "odd/<str:thing>/",
        TemplateView.as_view(template_name="generic/base.html"),
        name="odd-page",
    ),
    path("", include(project)),
]

"""The logbook's routes: the framework's endpoints, then the site
generated from planner/resources.py, last."""

from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from generic.sites import site
from planner import kpi

urlpatterns = [
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic", "planner"]),
        name="javascript-catalog",
    ),
    path("api/generic/", include("generic.urls", namespace="generic")),
    # The old planner's key figures, at their old addresses, before the
    # site's own pages.
    path("planner/api/kpi/", kpi.month_view, name="kpi-month"),
    path("planner/api/kpi/year/", kpi.year_view, name="kpi-year"),
    path("", site.urls),
]

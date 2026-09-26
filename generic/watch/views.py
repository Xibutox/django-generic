"""The page listing what a user is being told about.

One row per watch, each with the changes it listens for and the
channels it uses - which is where "the format, per model and per
record" is actually chosen. The button on a record only turns a watch
on and off; this is where it is tuned.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb
from generic.watch.models import (
    CHANNEL_LABELS,
    EVENT_LABELS,
    EVENTS,
    Watch,
)


class WatchesPage(SiteViewMixin, TemplateView):
    """Everything this user asked to hear about."""

    template_name = "generic/watch/watches.html"
    page_title = _("Watching")
    page_subtitle = _("What you are told about, and how.")

    def has_permission(self) -> bool:
        return bool(self.request.user.is_authenticated)

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=gettext("Watching"))]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from generic.delivery import ALL

        context = super().get_context_data(**kwargs)
        context["events"] = [
            {"name": name, "label": EVENT_LABELS[name]} for name in EVENTS
        ]
        context["channels"] = [
            {"name": name, "label": CHANNEL_LABELS[name]} for name in ALL
        ]
        context["watch_count"] = Watch.objects.filter(
            user=self.request.user
        ).count()

        return context

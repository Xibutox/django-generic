"""The page an operator announces a restart from."""

from __future__ import annotations

from typing import Any

from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext
from django.views.generic import TemplateView

from generic.maintenance.api import may_announce
from generic.maintenance.models import RestartAnnouncement
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb


def _reverse(name: str) -> str:
    try:
        return reverse(name)
    except NoReverseMatch:
        return ""


class RestartAnnouncementPage(SiteViewMixin, TemplateView):
    """Announce a restart, see what is planned, call it off.

    The form is the serializer's own schema, rendered by the same code
    as any resource form; this page only frames it.
    """

    template_name = "generic/maintenance/restart.html"

    def has_permission(self) -> bool:
        return may_announce(self.request.user)

    def get_page_title(self) -> str:
        return gettext("Plan a restart")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=self.get_page_title())]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        current = RestartAnnouncement.objects.current()

        context.update(
            {
                "form_config": {
                    "mode": "create",
                    "embedded": True,
                    "schemaUrl": _reverse("generic:restart-schema"),
                    # A create posts to the collection; the same route
                    # here, which is one announcement at a time.
                    "collectionUrl": _reverse("generic:restart"),
                },
                "restart_url": _reverse("generic:restart"),
                "current": current,
                "recent": RestartAnnouncement.objects.all()[:10],
            }
        )

        return context

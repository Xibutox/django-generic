"""The Server status page: this server, then every monitored one."""

from __future__ import annotations

from typing import Any

from django.http import Http404
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext
from django.views.generic import TemplateView

from generic.conf import generic_settings
from generic.sites.views import SiteViewMixin
from generic.status.api import accepted_tokens, may_view_status
from generic.status.models import StatusServer
from generic.status.remote import TOKEN_HEADER
from generic.views.toolbar import Breadcrumb, ToolbarItem


def _reverse(name: str, *args: Any) -> str:
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ""


class StatusPage(SiteViewMixin, TemplateView):
    """A frame: the cards fill themselves from the status endpoints.

    One request per server, from the browser to this server, so a
    server that takes its time to answer holds up its own card only.
    """

    template_name = "generic/status/status.html"

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if not generic_settings.SHOW_STATUS:
            raise Http404

        return super().dispatch(request, *args, **kwargs)

    def has_permission(self) -> bool:
        return may_view_status(self.request.user)

    def get_page_title(self) -> str:
        return gettext("Server status")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=self.get_page_title())]

    def servers_resource(self) -> Any:
        return self.site.get_resource(StatusServer)

    def get_toolbar_items(self) -> list[ToolbarItem]:
        resource = self.servers_resource()
        items = []

        if resource is not None and resource.has_add_permission(self.request):
            items.append(
                ToolbarItem(
                    url=resource.get_add_url(),
                    label=gettext("Add a server"),
                    icon="add",
                    variant="primary",
                )
            )

        if resource is not None and resource.has_view_permission(self.request):
            items.append(
                ToolbarItem(
                    url=resource.get_list_url(),
                    label=gettext("Monitored servers"),
                    icon="dns",
                )
            )

        return items

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        resource = self.servers_resource()
        may_change = bool(
            resource is not None
            and resource.has_change_permission(self.request)
        )
        servers = [
            {
                "id": server.pk,
                "name": server.name,
                "description": server.description,
                "url": _reverse("generic:status-server", server.pk),
                "changeUrl": (
                    resource.get_change_url(server.pk) if may_change else ""
                ),
            }
            for server in StatusServer.objects.filter(is_active=True)
        ]
        api_url = _reverse("generic:status")

        context["status_config"] = {
            "localUrl": api_url,
            "servers": servers,
            "refresh": int(generic_settings.STATUS_REFRESH_SECONDS or 0),
        }
        context["plug"] = {
            "address": self.request.build_absolute_uri(api_url),
            "header": TOKEN_HEADER,
            "has_token": bool(accepted_tokens()),
        }

        return context

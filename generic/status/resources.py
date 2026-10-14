"""The monitored servers, as an ordinary screen, and the status page's
place in the navigation."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from generic.conf import generic_settings
from generic.reports import Report
from generic.sites import ModelResource, action, display, site
from generic.status.models import StatusServer
from generic.status.remote import fetch

GROUP = _("Monitoring")


class StatusServerResource(ModelResource):
    """Other servers running django-generic, shown on the status page."""

    icon = "dns"
    group = GROUP
    order = 1
    description = _(
        "Other servers running django-generic: the Server status page "
        "shows each of them beside this one."
    )

    list_display = (
        "name",
        "url",
        "description",
        "has_token",
        "is_active",
        "position",
    )
    search_fields = ("name", "url", "description")
    ordering = ("position", "name")
    actions = ("test_connection", "delete_selected")
    fieldsets = (
        (None, {"fields": (("name", "position"), "url", "token")}),
        (None, {"fields": ("description", "is_active")}),
    )
    detail_fieldsets = (
        (None, {"fields": ("name", "url", "description")}),
        (None, {"fields": ("has_token", "is_active", "position")}),
    )
    form_overrides = {
        "token": {"widget": "password", "width": 12},
        "url": {"placeholder": "https://erp.example.com"},
    }
    # The token is sent to the other server, so it is kept as typed -
    # and for that reason never sent back to a browser, never kept in
    # the history, never exported.
    form_field_kwargs = {"token": {"write_only": True, "required": False}}
    history_exclude = ("token",)
    mailing = False

    @display(description=_("Token"), boolean=True)
    def has_token(self, server: StatusServer) -> bool:
        return bool(server.token)

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        """An empty token on a change keeps the one already there."""
        token = str(serializer.validated_data.get("token", "") or "")

        if change and not token.strip():
            serializer.validated_data.pop("token", None)

        return super().save_model(request, serializer, change)

    @action(
        description=_("Test the connection"),
        icon="network_check",
        permissions=("view",),
        help=_("Ask the server for its status now, and say how it went."),
    )
    def test_connection(self, request: Any, queryset: Any) -> Report:
        report = Report()

        for server in queryset:
            card = fetch(server)
            elapsed = gettext("%(ms)s ms") % {"ms": card["elapsed_ms"]}

            if card["reachable"]:
                title = str(card["status"].get("server", {}).get("title"))
                report.success(
                    f"{server.name}: {title}",
                    gettext("Answered in %(elapsed)s, state %(level)s.")
                    % {"elapsed": elapsed, "level": card["level"]},
                )
            else:
                report.error(server.name, card["error"])

        return report


def register_screens() -> None:
    """Put the status page and the monitored servers on the site.

    ``SHOW_STATUS = False`` leaves both out; a project registering
    ``StatusServer`` itself keeps its own screen.
    """
    if not generic_settings.SHOW_STATUS:
        return

    if not site.is_registered(StatusServer):
        site.register(StatusServer, StatusServerResource)

    site.add_link(
        _("Server status"),
        route="site:status",
        icon="monitor_heart",
        group=GROUP,
        order=-1,
        permission="generic.view_status",
    )

"""The help page, and the changes the application went through."""

from __future__ import annotations

from typing import Any

from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext
from django.views.generic import TemplateView

from generic.conf import generic_settings
from generic.help.api import may_change_settings
from generic.help.models import HelpSettings
from generic.help.sources import changelogs, licence
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb


def _reverse(name: str) -> str:
    try:
        return reverse(name)
    except NoReverseMatch:
        return ""


class HelpPage(SiteViewMixin, TemplateView):
    """What this application is, who to ask, under what licence."""

    template_name = "generic/help/help.html"

    def get_page_title(self) -> str:
        return gettext("Help")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=self.get_page_title())]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        sources = changelogs()
        newest = sources[0].releases if sources else []

        context.update(
            {
                "version": str(generic_settings.VERSION or ""),
                "help_text": str(generic_settings.HELP_TEXT or ""),
                "help_links": list(generic_settings.HELP_LINKS or []),
                "licence": licence(),
                "changelog_url": self.site.get_url("changelog"),
                # The last release, so the page says what changed most
                # recently without being a changelog itself.
                "latest_release": newest[0].as_dict() if newest else None,
                "bug_report_url": HelpSettings.bug_report_link(),
                "settings_config": self.get_settings_config(),
            }
        )

        return context

    def get_settings_config(self) -> dict[str, Any] | None:
        """The settings form, for whoever may change them; else None."""
        url = _reverse("generic:help-settings")

        if not url or not may_change_settings(self.request.user):
            return None

        return {
            "mode": "update",
            "embedded": True,
            "schemaUrl": _reverse("generic:help-settings-schema"),
            "objectUrl": url,
        }


class ChangelogPage(SiteViewMixin, TemplateView):
    """Every change the application recorded, as its files tell it."""

    template_name = "generic/help/changelog.html"

    def get_page_title(self) -> str:
        return gettext("What changed")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [
            Breadcrumb(label=gettext("Help"), url=self.site.get_url("help")),
            Breadcrumb(label=self.get_page_title()),
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["sources"] = [source.as_dict() for source in changelogs()]

        return context

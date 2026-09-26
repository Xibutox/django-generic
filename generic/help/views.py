"""The help page, and the changes the application went through."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext
from django.views.generic import TemplateView

from generic.conf import generic_settings
from generic.help.sources import changelogs, licence
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb


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
            }
        )

        return context


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

"""The merge page: files chosen, ordered, merged, downloaded."""

from __future__ import annotations

from typing import Any

from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext
from django.views.generic import TemplateView

from generic.conf import generic_settings
from generic.docx.merge import PLACEHOLDER
from generic.docx.permissions import may_merge
from generic.sites import site
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb


def merge_url() -> str:
    """The endpoint's address; empty when ``generic.urls`` is not
    mounted."""
    try:
        return reverse("generic:docx-merge")
    except NoReverseMatch:
        return ""


class DocxMergePage(SiteViewMixin, TemplateView):
    site = site
    template_name = "generic/docx/merge.html"

    def has_permission(self) -> bool:
        return may_merge(self.request.user)

    def get_page_title(self) -> str:
        return gettext("Merge Word files")

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return [Breadcrumb(label=self.get_page_title())]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["placeholder"] = PLACEHOLDER
        context["merge_config"] = {
            "url": merge_url(),
            "maxFiles": generic_settings.DOCX_MERGE_MAX_FILES,
            "maxSize": generic_settings.FILE_MAX_SIZE,
        }

        return context

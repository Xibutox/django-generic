"""Detail view."""

from __future__ import annotations

from typing import Any, Sequence

from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext
from django.views.generic.detail import DetailView

from generic.forms.fieldsets import render_readonly_value
from generic.views.mixins import AccessMixin, ModelPageMixin
from generic.views.tables import resolve_column_label
from generic.views.toolbar import Breadcrumb, ToolbarItem


class GenericDetailView(AccessMixin, ModelPageMixin, DetailView):
    """Read-only view of one object.

    Fields are declared the way a listing declares its columns::

        class BookDetailView(GenericDetailView):
            model = Book
            display_fields = ("title", "author", "price")
    """

    template_name = "generic/detail.html"
    page_action = "detail"
    permission_action = "view"
    context_object_name = "object"

    #: Fields shown, in order. Empty means every concrete model field.
    display_fields: Sequence[str] = ()

    list_url_name: str = ""
    update_url_name: str = ""
    delete_url_name: str = ""

    # -- content ------------------------------------------------------

    def get_display_fields(self) -> Sequence[str]:
        if self.display_fields:
            return self.display_fields

        model = self.get_model()

        if model is None:
            return ()

        return tuple(
            field.name for field in model._meta.fields if field.name != "id"
        )

    def build_detail_rows(self) -> list[dict[str, Any]]:
        instance = self.object
        model = self.get_model()
        rows = []

        for name in self.get_display_fields():
            accessor = getattr(self, name, None)

            if callable(accessor):
                value = accessor(instance)
            else:
                display = getattr(
                    instance,
                    f"get_{name}_display",
                    None,
                )
                value = (
                    display()
                    if callable(display)
                    else getattr(instance, name, None)
                )

            rows.append(
                {
                    "name": name,
                    "label": resolve_column_label(
                        name,
                        accessor,
                        model,
                    ),
                    "value": render_readonly_value(value),
                }
            )

        return rows

    # -- chrome -------------------------------------------------------

    def get_page_subtitle(self) -> str:
        return self.page_subtitle or str(self.object)

    def reverse_object_route(self, route: str) -> str:
        if not route:
            return ""

        try:
            return reverse(route, kwargs={"pk": self.object.pk})
        except NoReverseMatch:
            return ""

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        if self.breadcrumbs:
            return list(self.breadcrumbs)

        meta = self.model_meta
        trail = []

        if self.list_url_name:
            try:
                trail.append(
                    Breadcrumb(
                        label=str(meta.verbose_name_plural).capitalize(),
                        url=reverse(self.list_url_name),
                    )
                )
            except NoReverseMatch:
                pass

        trail.append(Breadcrumb(label=str(self.object)))

        return trail

    def get_toolbar_items(self) -> list[ToolbarItem]:
        if self.toolbar_items:
            return list(self.toolbar_items)

        meta = self.model_meta
        items = []

        update_url = self.reverse_object_route(self.update_url_name)

        if update_url:
            items.append(
                ToolbarItem(
                    url=update_url,
                    label=gettext("Change"),
                    icon="edit",
                    variant="primary",
                    permission=(f"{meta.app_label}.change_{meta.model_name}"),
                )
            )

        delete_url = self.reverse_object_route(self.delete_url_name)

        if delete_url:
            items.append(
                ToolbarItem(
                    url=delete_url,
                    label=gettext("Delete"),
                    icon="delete",
                    variant="danger",
                    permission=(f"{meta.app_label}.delete_{meta.model_name}"),
                )
            )

        return items

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["detail_rows"] = self.build_detail_rows()

        return context

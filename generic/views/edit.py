"""Create and update views."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.http import HttpResponse
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.views.generic.edit import CreateView, UpdateView

from generic.views.mixins import (
    AccessMixin,
    FieldsetMixin,
    ModelPageMixin,
    PopupMixin,
)
from generic.views.toolbar import Breadcrumb, ToolbarItem

#: Submit button names, matching the admin's so muscle memory carries
#: over and so a project's existing templates keep working.
SAVE = "_save"
SAVE_AND_CONTINUE = "_continue"
SAVE_AND_ADD_ANOTHER = "_addanother"


class GenericEditMixin(
    PopupMixin,
    FieldsetMixin,
    SuccessMessageMixin,
    AccessMixin,
    ModelPageMixin,
):
    """Shared behaviour of the create and update views."""

    template_name = "generic/form.html"

    #: Which submit buttons the page offers.
    show_save = True
    show_save_and_continue = True
    show_save_and_add_another = False

    list_url_name: str = ""
    detail_url_name: str = ""
    delete_url_name: str = ""

    def get_initial(self) -> dict[str, Any]:
        """Seed the form from the query string.

        Lets a link pre-fill a form — "add a chapter to *this* book" —
        without a dedicated view. Only real model fields are taken, so
        an arbitrary parameter cannot reach the form.
        """
        initial = dict(super().get_initial())
        model = self.get_model()

        if model is None:
            return initial

        for name, values in self.request.GET.lists():
            try:
                field = model._meta.get_field(name)
            except FieldDoesNotExist:
                continue

            if isinstance(field, models.ManyToManyField):
                initial[name] = values
            else:
                initial[name] = values[0]

        return initial

    # -- redirection --------------------------------------------------

    def reverse_object_route(self, route: str, instance: Any) -> str:
        if not route or instance is None or instance.pk is None:
            return ""

        try:
            return reverse(route, kwargs={"pk": instance.pk})
        except NoReverseMatch:
            return ""

    def get_list_url(self) -> str:
        if not self.list_url_name:
            return ""

        try:
            return reverse(self.list_url_name)
        except NoReverseMatch:
            return ""

    def get_cancel_url(self) -> str:
        return (
            self.reverse_object_route(
                self.detail_url_name,
                getattr(self, "object", None),
            )
            or self.get_list_url()
            or "/"
        )

    def get_success_url(self) -> str:
        if SAVE_AND_CONTINUE in self.request.POST:
            return self.request.get_full_path()

        if SAVE_AND_ADD_ANOTHER in self.request.POST:
            return self.request.path

        detail_url = self.reverse_object_route(
            self.detail_url_name,
            self.object,
        )

        if detail_url:
            return detail_url

        list_url = self.get_list_url()

        if list_url:
            return list_url

        return super().get_success_url()

    def form_valid(self, form: Any) -> HttpResponse:
        response = super().form_valid(form)

        # A popup must report back to the window that opened it rather
        # than navigating, which would strand the parent form.
        if self.is_popup():
            return self.render_popup_response(
                self.popup_action,
                self.object,
            )

        return response

    def form_invalid(self, form: Any) -> HttpResponse:
        messages.error(
            self.request,
            _("Please correct the errors below."),
        )

        return super().form_invalid(form)

    # -- chrome -------------------------------------------------------

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        if self.breadcrumbs:
            return list(self.breadcrumbs)

        meta = self.model_meta
        trail = []
        list_url = self.get_list_url()

        if list_url and meta is not None:
            trail.append(
                Breadcrumb(
                    label=str(meta.verbose_name_plural).capitalize(),
                    url=list_url,
                )
            )

        trail.append(Breadcrumb(label=self.get_page_title()))

        return trail

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        popup = self.is_popup()

        context.update(
            {
                "cancel_url": self.get_cancel_url(),
                "save_name": SAVE,
                "save_and_continue_name": SAVE_AND_CONTINUE,
                "save_and_add_another_name": SAVE_AND_ADD_ANOTHER,
                "show_save": self.show_save,
                # Inside a popup there is nowhere to continue *to*.
                "show_save_and_continue": (
                    self.show_save_and_continue and not popup
                ),
                "show_save_and_add_another": (
                    self.show_save_and_add_another and not popup
                ),
                "delete_url": self.reverse_object_route(
                    self.delete_url_name,
                    getattr(self, "object", None),
                ),
            }
        )

        return context


class GenericCreateView(GenericEditMixin, CreateView):
    """Create one object.

    ::

        class BookCreateView(GenericCreateView):
            model = Book
            fields = ("title", "author", "price")
            list_url_name = "book-list"
    """

    page_action = "create"
    permission_action = "add"
    popup_action = "create"
    show_save_and_add_another = True

    def get_success_message(self, cleaned_data: dict) -> str:
        if self.success_message:
            return super().get_success_message(cleaned_data)

        return gettext("%(name)s was added successfully.") % {
            "name": self.object
        }


class GenericUpdateView(GenericEditMixin, UpdateView):
    """Change one object."""

    page_action = "update"
    permission_action = "change"
    popup_action = "change"

    def get_page_subtitle(self) -> str:
        return self.page_subtitle or str(self.object)

    def get_success_message(self, cleaned_data: dict) -> str:
        if self.success_message:
            return super().get_success_message(cleaned_data)

        return gettext("%(name)s was updated successfully.") % {
            "name": self.object
        }

    def get_toolbar_items(self) -> list[ToolbarItem]:
        if self.toolbar_items:
            return list(self.toolbar_items)

        detail_url = self.reverse_object_route(
            self.detail_url_name,
            self.object,
        )

        if not detail_url:
            return []

        return [
            ToolbarItem(
                url=detail_url,
                label=gettext("View"),
                icon="view",
                variant="ghost",
            )
        ]

"""Mixins shared by the generic views.

Each one does a single thing, so a project can take the page chrome
without the permissions, or the permissions without the fieldsets.
"""

from __future__ import annotations

from typing import Any, Sequence

from django.contrib.auth.mixins import (
    LoginRequiredMixin,
    PermissionRequiredMixin,
)
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _
from django.views.generic.base import ContextMixin

from generic.forms.fieldsets import (
    FieldsetForm,
    FieldsetsSpec,
    build_default_fieldsets,
)
from generic.views.toolbar import Breadcrumb, ToolbarItem

#: Query parameter marking a window opened to edit a related object.
POPUP_PARAM = "_popup"

#: Query parameter naming the field the opener expects back.
TO_FIELD_PARAM = "_to_field"


class PageMixin(ContextMixin):
    """Title, subtitle, breadcrumbs and toolbar.

    Every generic view inherits this, so a template only ever reads one
    vocabulary regardless of which view rendered it.
    """

    #: Shown as the page heading. Falls back to a model-derived title.
    page_title: str = ""
    #: Secondary heading, usually the object being worked on.
    page_subtitle: str = ""
    #: Rendered above the title.
    breadcrumbs: Sequence[Breadcrumb] = ()
    #: Buttons in the page toolbar.
    toolbar_items: Sequence[ToolbarItem] = ()
    #: Whether the collapsible navigation sidebar is rendered.
    show_sidebar: bool = True

    def get_page_title(self) -> str:
        return self.page_title

    def get_page_subtitle(self) -> str:
        return self.page_subtitle

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return list(self.breadcrumbs)

    def get_toolbar_items(self) -> list[ToolbarItem]:
        return list(self.toolbar_items)

    def get_visible_toolbar_items(self) -> list[ToolbarItem]:
        user = getattr(self.request, "user", None)

        return [
            item for item in self.get_toolbar_items() if item.is_visible(user)
        ]

    def is_popup(self) -> bool:
        return POPUP_PARAM in self.request.GET or (
            POPUP_PARAM in self.request.POST
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        popup = self.is_popup()

        context.update(
            {
                "page_title": self.get_page_title(),
                "page_subtitle": self.get_page_subtitle(),
                "breadcrumbs": self.get_breadcrumbs(),
                "toolbar_items": self.get_visible_toolbar_items(),
                # A popup is a bare window inside another page: no
                # sidebar, no breadcrumbs, no chrome to get lost in.
                "show_sidebar": self.show_sidebar and not popup,
                "is_popup": popup,
                "popup_param": POPUP_PARAM,
            }
        )

        return context


class ModelPageMixin(PageMixin):
    """Page chrome derived from the view's model.

    Saves every view from restating "Books" three times.
    """

    #: Verb describing what the page does, used in the default title.
    page_action: str = ""

    def get_model(self) -> Any:
        model = getattr(self, "model", None)

        if model is not None:
            return model

        queryset = getattr(self, "queryset", None)

        if queryset is not None:
            return queryset.model

        return None

    @property
    def model_meta(self) -> Any:
        model = self.get_model()

        return model._meta if model is not None else None

    def get_default_page_title(self) -> str:
        meta = self.model_meta

        if meta is None:
            return ""

        # A listing is named after the collection, a detail page after
        # the object; neither needs a translatable wrapper around a bare
        # placeholder.
        if self.page_action == "list":
            return str(meta.verbose_name_plural).capitalize()

        if self.page_action == "detail":
            return str(meta.verbose_name).capitalize()

        titles = {
            "create": _("Add %(name)s"),
            "update": _("Change %(name)s"),
            "delete": _("Delete %(name)s"),
        }
        template = titles.get(self.page_action)

        if template is None:
            return str(meta.verbose_name_plural).capitalize()

        return str(template % {"name": meta.verbose_name}).capitalize()

    def get_page_title(self) -> str:
        return self.page_title or self.get_default_page_title()


class AccessMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Authentication plus a model-derived permission.

    A view that names a model gets ``app_label.view_model`` and friends
    for free, matching Django's own permission names. Set
    ``permission_required`` to override, or ``require_permission =
    False`` when authentication alone is enough.
    """

    #: ``view``, ``add``, ``change`` or ``delete``.
    permission_action: str = "view"
    require_permission: bool = True

    def get_permission_required(self) -> Sequence[str]:
        if self.permission_required is not None:
            return super().get_permission_required()

        if not self.require_permission:
            return ()

        meta = getattr(self, "model_meta", None)

        if meta is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__} must define "
                f"'permission_required', or a model to derive it from, "
                f"or set require_permission = False."
            )

        return (
            f"{meta.app_label}." f"{self.permission_action}_{meta.model_name}",
        )

    def has_permission(self) -> bool:
        if not self.require_permission:
            return True

        return super().has_permission()


class PopupMixin:
    """Support for editing a related object in a popup window.

    A select widget can open a small window to create the missing
    option; on save, the window posts the new value back to its opener
    and closes. This is Django admin's mechanism, kept because it is the
    one thing that makes a deep form usable without losing what has
    already been typed.
    """

    popup_response_template = "generic/popup_response.html"

    #: Reported to the opener so it knows whether to add an option or
    #: relabel the one it already has.
    popup_action: str = "change"

    def render_popup_response(
        self,
        action: str,
        instance: Any,
    ) -> HttpResponse:
        to_field = self.request.POST.get(TO_FIELD_PARAM) or (
            self.request.GET.get(TO_FIELD_PARAM)
        )
        attribute = to_field or instance._meta.pk.attname

        payload = {
            "action": action,
            "value": str(instance.serializable_value(attribute)),
            "obj": str(instance),
        }

        if action == "change":
            payload["newValue"] = str(instance.pk)

        # Handed over as a dict: the template serialises it with
        # json_script, so nothing is interpolated into executable code.
        return TemplateResponse(
            self.request,
            self.popup_response_template,
            {"popup_response_data": payload},
        )


class FieldsetMixin:
    """Lay a form out in named fieldsets.

    Declared the way Django admin declares them; a tuple inside
    ``fields`` puts those fields on one row::

        fieldsets = (
            (None, {"fields": ("title", ("author", "publisher"))}),
            ("Commercial", {"fields": ("price",),
                            "classes": ("collapse",)}),
        )
    """

    fieldsets: FieldsetsSpec | None = None
    readonly_fields: Sequence[str] = ()

    def get_readonly_fields(self) -> Sequence[str]:
        return self.readonly_fields

    def get_fieldsets(self, form: Any) -> FieldsetsSpec:
        if self.fieldsets is not None:
            return self.fieldsets

        return build_default_fieldsets(
            form,
            self.get_readonly_fields(),
        )

    def get_fieldset_form(self, form: Any) -> FieldsetForm:
        # The view is the display source, so a read-only field can be
        # computed with a ``method(self, instance)`` on it.
        return FieldsetForm(
            form,
            self.get_fieldsets(form),
            self.get_readonly_fields(),
            source=self,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        form = context.get("form")

        if form is not None:
            context["fieldset_form"] = self.get_fieldset_form(form)

        return context

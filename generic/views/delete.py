"""Delete view, with a preview of what goes with it."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.db import router
from django.http import HttpResponse
from django.urls import NoReverseMatch, reverse
from django.utils.encoding import force_str
from django.utils.translation import gettext
from django.views.generic.edit import DeleteView

from generic.views.mixins import AccessMixin, ModelPageMixin, PopupMixin
from generic.views.toolbar import Breadcrumb


def collect_deletion_summary(instance: Any) -> dict[str, Any]:
    """What deleting ``instance`` would take with it.

    Uses Django's own cascade collector, so the answer matches what the
    database would actually do.
    """
    from django.contrib.admin.utils import NestedObjects
    from django.db.models.deletion import ProtectedError, RestrictedError

    using = router.db_for_write(instance._meta.model, instance=instance)
    collector = NestedObjects(using=using)

    try:
        collector.collect([instance])
    except (ProtectedError, RestrictedError) as error:
        protected = list(
            getattr(error, "protected_objects", None)
            or getattr(error, "restricted_objects", None)
            or []
        )

        return {
            "can_delete": False,
            "nested": [],
            "counts": [],
            "protected": [describe(item) for item in protected],
        }

    protected = [describe(item) for item in collector.protected]

    return {
        "can_delete": not protected,
        "nested": build_nested(collector.nested()),
        "counts": [
            {
                "label": force_str(model._meta.verbose_name_plural),
                "count": len(instances),
            }
            for model, instances in collector.model_objs.items()
            if not is_link(model)
        ],
        "protected": protected,
    }


def is_link(model: Any) -> bool:
    """A many-to-many table Django made: links going, not records.

    "Ticket-tag relationship: Ticket_tags object (4)" tells a reader
    nothing the record's own line does not; the tags themselves stay.
    """
    return bool(model._meta.auto_created)


def describe(instance: Any) -> dict[str, str]:
    meta = instance._meta

    return {
        "model": force_str(meta.verbose_name).capitalize(),
        "label": force_str(instance),
    }


def build_nested(node: Any) -> list[Any]:
    """Turn the collector's nested lists into template-friendly data."""
    result = []

    for item in node:
        if isinstance(item, (list, tuple)):
            # A nested list belongs to the entry just before it.
            if result:
                result[-1]["children"] = build_nested(item)
            continue

        if is_link(type(item)):
            continue

        result.append({**describe(item), "children": []})

    return result


class GenericDeleteView(
    PopupMixin,
    AccessMixin,
    ModelPageMixin,
    DeleteView,
):
    """Confirm, then delete.

    The confirmation page lists everything the cascade would remove, and
    refuses outright when a protected relation stands in the way — so
    the user learns why here rather than from a 500 after submitting.
    """

    template_name = "generic/delete_confirmation.html"
    page_action = "delete"
    permission_action = "delete"
    popup_action = "delete"

    list_url_name: str = ""
    detail_url_name: str = ""

    def get_page_subtitle(self) -> str:
        return self.page_subtitle or str(self.object)

    def get_list_url(self) -> str:
        if not self.list_url_name:
            return ""

        try:
            return reverse(self.list_url_name)
        except NoReverseMatch:
            return ""

    def get_cancel_url(self) -> str:
        if self.detail_url_name and self.object is not None:
            try:
                return reverse(
                    self.detail_url_name,
                    kwargs={"pk": self.object.pk},
                )
            except NoReverseMatch:
                pass

        return self.get_list_url() or "/"

    def get_success_url(self) -> str:
        list_url = self.get_list_url()

        if list_url:
            return list_url

        return super().get_success_url()

    def form_valid(self, form: Any) -> HttpResponse:
        self.object = self.get_object()
        summary = collect_deletion_summary(self.object)

        # Checked again on POST: the page may have been open for a
        # while, and a relation could have appeared since it rendered.
        if not summary["can_delete"]:
            messages.error(
                self.request,
                gettext(
                    "%(name)s cannot be deleted because other records "
                    "depend on it."
                )
                % {"name": self.object},
            )

            return self.render_to_response(
                self.get_context_data(object=self.object)
            )

        label = str(self.object)
        response = super().form_valid(form)

        messages.success(
            self.request,
            gettext("%(name)s was deleted successfully.") % {"name": label},
        )

        if self.is_popup():
            return self.render_popup_response("delete", self.object)

        return response

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
        context["deletion"] = collect_deletion_summary(self.object)
        context["cancel_url"] = self.get_cancel_url()

        return context

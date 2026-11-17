"""Form pages: any serializer drawn as a form, in the site's frame.

A resource's add and change pages write one record. A form page is for
everything else - a form that writes nothing (send a notice, run a
computation), a form over a model that is not a resource's own add page,
a form writing several records at once (:class:`generic.api.ModelsForm`)
- with the same look, widgets, sections, validation and messages::

    class NoticeForm(FormSerializer):
        title = serializers.CharField(max_length=120)
        body = serializers.CharField(style={"base_template": "textarea.html"})


    class NoticePage(FormPageView):
        serializer_class = NoticeForm
        page_title = _("Send a notice")
        permission_required = "example.change_ticket"

        def form_valid(self, serializer):
            send(**serializer.validated_data)
            return _("The notice was sent.")

    # urls.py
    path("notice/", NoticePage.as_view(site=site), name="notice")

The page is a frame: the form is drawn in the browser from the
serializer's schema, which travels inside the page, and is posted back
as JSON to the page's own address. The serializer validates it - a 400
puts each error beside its field - and ``form_valid`` does the work.

A page of a resource is a :class:`ResourceFormPageView`, declared with
``ResourcePage(name, view=...)``: the resource's address, permission,
breadcrumbs and - on a record's page - the record, which a model form
of that model edits.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import HttpResponseBase, JsonResponse
from django.utils.encoding import force_str
from django.utils.translation import gettext
from django.views.generic import TemplateView
from rest_framework import serializers
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.fields import get_error_detail
from rest_framework.request import Request
from rest_framework.settings import api_settings

from generic.api.relations import DISPLAY_KEY
from generic.sites.pages import ResourcePageView
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb


def model_of(serializer_class: Any) -> Any:
    """The model a model serializer writes, or ``None``."""
    if not isinstance(serializer_class, type) or not issubclass(
        serializer_class, serializers.ModelSerializer
    ):
        return None

    return getattr(getattr(serializer_class, "Meta", None), "model", None)


def permission_name(model: Any, action: str) -> str:
    options = model._meta

    return f"{options.app_label}.{action}_{options.model_name}"


def as_errors(detail: Any) -> dict[str, Any]:
    """A validation error as the form reads it: by field, or general."""
    if isinstance(detail, dict):
        return detail

    if not isinstance(detail, list):
        detail = [detail]

    return {api_settings.NON_FIELD_ERRORS_KEY: detail}


class FormViewMixin:
    """What draws a serializer as a form, and answers it.

    Mixed into :class:`FormPageView` (a page of the site) and
    :class:`ResourceFormPageView` (a page of a resource).
    """

    request: Any
    template_name: Any = "generic/form_page.html"

    #: A ``FormSerializer``, a ``FormModelSerializer`` or a
    #: ``ModelsForm``: the fields, their layout and their validation.
    serializer_class: Any = None
    #: Needed besides what the serializer's models need: a permission
    #: string, or several (all of them).
    permission_required: str | Iterable[str] = ()
    #: The values the form opens with, when it edits nothing.
    initial: dict[str, Any] = {}
    #: The submit button.
    submit_label: Any = None
    #: Shown once the form is accepted, unless ``form_valid`` returns a
    #: message of its own.
    success_message: Any = None
    #: Where to go once the form is accepted; ``None`` stays on the page
    #: with the form ready again.
    success_url: Any = None
    #: The Cancel link; none when ``None``.
    cancel_url: Any = None
    #: A sentence above the form.
    description: Any = ""
    #: The page header's icon.
    icon = "edit_note"

    # -- the serializer ------------------------------------------------

    def get_serializer_class(self) -> Any:
        if self.serializer_class is None:
            raise ImproperlyConfigured(
                f"{type(self).__name__} draws a form from a serializer: "
                f"set serializer_class."
            )

        return self.serializer_class

    def get_serializer_context(self) -> dict[str, Any]:
        return {"request": self.request, "view": self}

    def get_serializer(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("context", self.get_serializer_context())

        return self.get_serializer_class()(*args, **kwargs)

    def get_instance(self) -> Any:
        """What the form edits: a record for a model form, a mapping of
        part names to records for a ``ModelsForm``; ``None`` to create.
        """
        return None

    def get_form_instance(self) -> Any:
        if not hasattr(self, "_form_instance"):
            self._form_instance = self.get_instance()

        return self._form_instance

    # -- permissions ---------------------------------------------------

    def get_required_permissions(self) -> list[str]:
        """``permission_required``, and what the models need: adding a
        record a model form creates, changing one it edits."""
        required = self.permission_required
        permissions = (
            [required] if isinstance(required, str) else list(required)
        )
        serializer_class = self.get_serializer_class()
        instance = self.get_form_instance()

        if hasattr(serializer_class, "get_required_permissions"):
            permissions.extend(
                serializer_class.get_required_permissions(instance)
            )
        elif model_of(serializer_class) is not None:
            action = "add" if instance is None else "change"
            permissions.append(
                permission_name(model_of(serializer_class), action)
            )

        return permissions

    def has_form_permission(self) -> bool:
        return self.request.user.has_perms(self.get_required_permissions())

    # -- what the page sends the browser -------------------------------

    def get_submit_label(self) -> str:
        return force_str(self.submit_label or gettext("Submit"))

    def get_cancel_url(self) -> str:
        return force_str(self.cancel_url or "")

    def get_description(self) -> str:
        return force_str(self.description or "")

    def get_initial(self) -> dict[str, Any]:
        """The values the form opens with.

        The record's, read through the serializer, when the form edits
        one; ``initial`` otherwise.
        """
        instance = self.get_form_instance()

        if instance is None:
            return dict(self.initial)

        return dict(self.get_serializer(instance).data)

    def get_schema(self) -> dict[str, Any]:
        schema = self.get_serializer_class().get_form_schema(
            request=self.request
        )
        schema.update(
            {
                "mode": "create",
                "inlines": [],
                "title": force_str(self.get_page_title()),  # type: ignore
                "submitLabel": self.get_submit_label(),
            }
        )

        return schema

    def split_initial(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """The initial values, and the labels of their relations."""
        initial = self.get_initial()
        display = initial.pop(DISPLAY_KEY, None) or {}

        return (
            {
                key: value
                for key, value in initial.items()
                if not key.startswith("_")
            },
            display,
        )

    def get_form_config(self) -> dict[str, Any]:
        initial, display = self.split_initial()

        return {
            # Every value sent, as a new record's are: a form page has
            # no record of its own to patch.
            "mode": "create",
            "formPage": True,
            "schema": self.get_schema(),
            "collectionUrl": self.request.path,
            "cancelUrl": self.get_cancel_url(),
            "initial": initial,
            "initialDisplay": display,
            "label": force_str(self.get_page_title()),  # type: ignore
        }

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)  # type: ignore[misc]
        context.update(
            form_config=self.get_form_config(),
            form_description=self.get_description(),
            form_icon=self.icon,
        )

        return context

    # -- the answer ------------------------------------------------------

    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            data = Request(
                request, parsers=[parser() for parser in self.get_parsers()]
            ).data
        except (ParseError, UnsupportedMediaType) as error:
            return self.respond({"detail": force_str(error.detail)}, 400)

        serializer = self.get_serializer(self.get_form_instance(), data=data)

        if not serializer.is_valid():
            return self.form_invalid(serializer.errors)

        try:
            # All or nothing: a refusal raised half way through the work
            # leaves no record behind.
            with transaction.atomic():
                result = self.form_valid(serializer)
        except serializers.ValidationError as error:
            return self.form_invalid(as_errors(error.detail))
        except DjangoValidationError as error:
            return self.form_invalid(as_errors(get_error_detail(error)))

        if isinstance(result, HttpResponseBase):
            return result

        return self.respond(self.get_success_payload(result))

    def get_parsers(self) -> tuple[Any, ...]:
        # Here, not at import: the viewsets import the sites.
        from generic.api.viewsets import FORM_PARSERS

        return FORM_PARSERS

    def form_valid(self, serializer: Any) -> Any:
        """The work, once the form is valid; in a transaction.

        Saves by default - a model form's record, a ``ModelsForm``'s
        records. A form that writes nothing overrides it and reads
        ``serializer.validated_data``. Returns a message (a string), a
        response (sent as it is), or anything ``get_success_message``
        and ``get_success_url`` make sense of: what was saved, by
        default. A ``ValidationError`` raised here is shown on the form.
        """
        if type(serializer).create is serializers.Serializer.create:
            raise ImproperlyConfigured(
                f"{type(self).__name__}: {type(serializer).__name__} saves "
                f"nothing; override form_valid(serializer) to do the work."
            )

        return serializer.save()

    def form_invalid(self, errors: Any) -> JsonResponse:
        return self.respond(errors, 400)

    def get_success_message(self, result: Any) -> str:
        if isinstance(result, str):
            return result

        if self.success_message:
            return force_str(self.success_message)

        return gettext("Done.")

    def get_success_url(self, result: Any) -> str:
        return force_str(self.success_url or "")

    def get_success_payload(self, result: Any) -> dict[str, Any]:
        url = self.get_success_url(result)
        payload: dict[str, Any] = {
            "_message": self.get_success_message(result),
            "_redirect": url,
        }

        if not url:
            # The form stays: it opens again on what is now true - empty
            # for a form that creates, the new values for one that edits.
            initial, display = self.split_initial()
            payload["_initial"] = initial
            payload["_initialDisplay"] = display

        return payload

    def respond(self, data: Any, status: int = 200) -> JsonResponse:
        return JsonResponse(
            data, status=status, encoder=DjangoJSONEncoder, safe=False
        )


class FormPageView(FormViewMixin, SiteViewMixin, TemplateView):
    """A form page of the site, mounted in a URLconf::

        path("notice/", NoticePage.as_view(site=site), name="notice")

    Signed-in readers only, holding the permissions
    ``get_required_permissions`` lists.
    """

    def has_permission(self) -> bool:
        return super().has_permission() and self.has_form_permission()

    def get_breadcrumbs(self) -> list[Breadcrumb]:
        return super().get_breadcrumbs() or [
            Breadcrumb(label=force_str(self.get_page_title()))
        ]


class ResourceFormPageView(FormViewMixin, ResourcePageView):
    """A form page of a resource::

        pages = (
            ResourcePage("onboard", view=OnboardingPage,
                         title=_("New customer"), icon="person_add"),
        )

    The resource's view permission and the page's own come first. On a
    record's page (``detail=True``) a model form of the resource's model
    edits the record, under the resource's change permission.
    """

    def has_permission(self) -> bool:
        return super().has_permission() and self.has_form_permission()

    def edits_the_record(self) -> bool:
        model = model_of(self.get_serializer_class())

        return (
            self.object is not None
            and model is not None
            and isinstance(self.object, model)
        )

    def get_instance(self) -> Any:
        return self.object if self.edits_the_record() else None

    def get_required_permissions(self) -> list[str]:
        permissions = super().get_required_permissions()
        model = getattr(self.resource, "model", None)

        # The resource's own rules - a team's records, a closed record -
        # rather than the bare model permission, for its own model.
        if model is not None:
            own = {
                permission_name(model, "add"),
                permission_name(model, "change"),
            }
            permissions = [name for name in permissions if name not in own]

        return permissions

    def has_form_permission(self) -> bool:
        if not super().has_form_permission():
            return False

        resource = self.resource
        model = getattr(resource, "model", None)
        serializer_class = self.get_serializer_class()
        writes = [model_of(serializer_class)] + [
            part.get_model() for part in getattr(serializer_class, "parts", ())
        ]

        if model is None or model not in writes:
            return True

        instance = self.get_form_instance()
        values = (
            instance.values() if isinstance(instance, Mapping) else [instance]
        )
        records = [value for value in values if isinstance(value, model)]

        if records:
            return all(
                resource.has_change_permission(self.request, record)
                for record in records
            )

        return resource.has_add_permission(self.request)


__all__ = ["FormPageView", "FormViewMixin", "ResourceFormPageView"]

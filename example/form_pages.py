"""Form pages of the example: forms that are not a resource's add page.

One of each kind (``generic.sites.form_pages``, docs/form-pages.md):

- **no model** - send a notice to colleagues (``NoticePage``), a page
  of the site mounted in example/urls.py: the form writes nothing, its
  ``form_valid`` sends the notifications;
- **several models** - a new customer with its first ticket, in one
  form saved as a whole (``NewCustomerPage``), a page of the customer
  resource;
- **one model** - reassign a ticket (``TicketReassignPage``): four of
  the ticket's fields, on a page of each ticket, under the ticket's
  change permission.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from rest_framework import serializers

from example.models import Customer, Ticket
from generic.api import (
    FormModelSerializer,
    FormPart,
    FormSerializer,
    ModelsForm,
)
from generic.delivery import notify
from generic.events.models import NotificationLevel
from generic.sites import FormPageView, ResourceFormPageView

# ---------------------------------------------------------------------
# No model: a notice to colleagues
# ---------------------------------------------------------------------


class NoticeForm(FormSerializer):
    """What a notice says, and to whom. Nothing of it is stored but the
    notifications it sends."""

    recipients = serializers.PrimaryKeyRelatedField(
        label=_("Recipients"),
        many=True,
        queryset=get_user_model().objects.filter(is_active=True),
    )
    title = serializers.CharField(label=_("Title"), max_length=120)
    body = serializers.CharField(
        label=_("Message"),
        style={"base_template": "textarea.html"},
    )
    level = serializers.ChoiceField(
        label=_("Level"),
        choices=[
            (level.value, level.label)
            for level in (
                NotificationLevel.INFO,
                NotificationLevel.WARNING,
                NotificationLevel.CRITICAL,
            )
        ],
        default=NotificationLevel.INFO,
    )
    url = serializers.CharField(
        label=_("Link"),
        required=False,
        allow_blank=True,
        max_length=200,
        help_text=_("A page of this site the notice points to."),
    )

    form_sections = (
        {"name": "general", "title": _("Notice"), "position": 0},
        {"name": "options", "title": _("Options"), "position": 1},
    )
    form_overrides = {
        "title": {"placeholder": _("Maintenance tonight")},
        "level": {"section": "options", "width": 6},
        "url": {"section": "options", "width": 6, "placeholder": "/example/"},
    }

    def validate_url(self, value: str) -> str:
        # A link of this site: a notice is not a way to send colleagues
        # elsewhere.
        if value and not value.startswith("/"):
            raise serializers.ValidationError(
                gettext("A link of this site starts with /.")
            )

        return value


class NoticePage(FormPageView):
    serializer_class = NoticeForm
    page_title = _("Send a notice")
    description = _(
        "Each recipient finds it in their notifications, at once if they "
        "are connected."
    )
    icon = "campaign"
    submit_label = _("Send")
    permission_required = "example.change_ticket"

    def form_valid(self, serializer: Any) -> str:
        values = serializer.validated_data
        notify(
            values["recipients"],
            title=values["title"],
            body=values["body"],
            level=values["level"],
            url=values.get("url", ""),
        )

        count = len(values["recipients"])

        return ngettext(
            "The notice was sent to %(count)d person.",
            "The notice was sent to %(count)d people.",
            count,
        ) % {"count": count}


# ---------------------------------------------------------------------
# Several models: a new customer with its first ticket
# ---------------------------------------------------------------------


class NewCustomerForm(ModelsForm):
    """A customer and its first ticket: both written, or neither."""

    parts = (
        FormPart(
            "customer",
            Customer,
            fields=("name", "code", "segment", "city", "account_manager"),
            title=_("Customer"),
        ),
        FormPart(
            "ticket",
            Ticket,
            fields=("title", "team", "priority", "description"),
            title=_("First ticket"),
            links={"customer": "customer"},
        ),
    )

    form_overrides = {
        "customer__name": {"width": 8},
        "customer__code": {"width": 4},
        "customer__segment": {"width": 6},
        "customer__city": {"width": 6},
        "ticket__team": {"width": 6},
        "ticket__priority": {"width": 6},
        "ticket__description": {"multiline": True},
    }

    def get_save_kwargs(self, part: FormPart, saved: dict) -> dict:
        if part.name == "ticket":
            # Numbered as the ticket's own form numbers it.
            from example.resources import next_reference

            return {"reference": next_reference()}

        return {}


class NewCustomerPage(ResourceFormPageView):
    serializer_class = NewCustomerForm
    submit_label = _("Create both")
    description = _(
        "The customer and its first ticket are created together: if "
        "either is refused, neither is written."
    )

    def get_success_message(self, result: Any) -> str:
        return gettext("%(customer)s was added, with ticket %(ticket)s.") % {
            "customer": result["customer"],
            "ticket": result["ticket"].reference,
        }

    def get_success_url(self, result: Any) -> str:
        return self.resource.get_detail_url(result["customer"].pk)


# ---------------------------------------------------------------------
# One model: reassign a ticket
# ---------------------------------------------------------------------


class TicketReassignForm(FormModelSerializer):
    class Meta:
        model = Ticket
        fields = ("team", "assignee", "priority", "due_on")

    form_overrides = {
        "team": {"width": 6},
        "assignee": {"width": 6},
        "priority": {"width": 6},
        "due_on": {"width": 6},
    }


class TicketReassignPage(ResourceFormPageView):
    serializer_class = TicketReassignForm
    submit_label = _("Reassign")
    success_message = _("The ticket was reassigned.")

    def get_success_url(self, result: Ticket) -> str:
        return self.resource.get_detail_url(result.pk)

    def get_cancel_url(self) -> str:
        return self.resource.get_detail_url(self.object.pk)

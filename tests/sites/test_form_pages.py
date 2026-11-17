"""Form pages (``generic.sites.form_pages``) and ``ModelsForm``.

The example has one of each kind: a form writing nothing (a notice to
colleagues), a form writing two models at once (a customer with its
first ticket) and a form over some of one model's fields (reassign a
ticket). Below them, what the declarations allow and refuse.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from rest_framework import serializers

from example.models import Customer, Team, Ticket
from generic.api import (
    FormModelSerializer,
    FormPart,
    FormSerializer,
    ModelsForm,
)
from generic.events.models import Notification
from generic.sites import FormPageView
from tests.factories import UserFactory
from tests.sites.test_resource_api import user_with

pytestmark = pytest.mark.django_db

NOTICE = "/example/notice/"
NEW_CUSTOMER = "/example/customer/new-with-ticket/"


def reassign_url(ticket: Ticket) -> str:
    return f"/example/ticket/{ticket.pk}/reassign/"


def post(client, url: str, data: dict):
    return client.post(url, json.dumps(data), content_type="application/json")


def config_of(response) -> dict:
    return response.context["form_config"]


# ---------------------------------------------------------------------
# No model: the notice
# ---------------------------------------------------------------------


class TestAFormWithoutModel:
    def test_the_page_carries_its_schema_and_posts_to_itself(
        self, admin_client
    ):
        response = admin_client.get(NOTICE)
        config = config_of(response)
        fields = {field["name"]: field for field in config["schema"]["fields"]}

        assert response.status_code == 200
        assert "generic/form_page.html" in [
            template.name for template in response.templates
        ]
        assert response.context["page_title"] == "Send a notice"
        assert config["formPage"] is True
        assert config["mode"] == "create"
        assert config["collectionUrl"] == NOTICE
        assert config["schema"]["submitLabel"] == "Send"
        assert list(fields) == ["recipients", "title", "body", "level", "url"]
        assert fields["recipients"]["type"] == "multiselect"
        assert fields["body"]["widget"] == "textarea"
        assert fields["level"]["section"] == "options"
        assert [s["name"] for s in config["schema"]["sections"]] == [
            "general",
            "options",
        ]

    def test_a_valid_form_does_the_work_and_says_so(
        self, admin_client, admin_user
    ):
        reader = UserFactory(username="reader")

        response = post(
            admin_client,
            NOTICE,
            {
                "recipients": [reader.pk, admin_user.pk],
                "title": "Maintenance tonight",
                "body": "From 22:00.",
                "level": 3,
            },
        )
        answer = response.json()

        assert response.status_code == 200
        assert answer["_message"] == "The notice was sent to 2 people."
        assert answer["_redirect"] == ""
        # The form opens again, empty.
        assert answer["_initial"] == {}
        assert Notification.objects.filter(
            user=reader, title="Maintenance tonight", level=3
        ).exists()

    def test_errors_come_back_by_field(self, admin_client):
        response = post(
            admin_client,
            NOTICE,
            {"recipients": [], "title": "", "body": "x", "url": "http://x"},
        )
        errors = response.json()

        assert response.status_code == 400
        assert set(errors) == {"title", "url"}
        assert Notification.objects.count() == 0

    def test_a_body_that_is_not_json_is_a_400(self, admin_client):
        response = admin_client.post(
            NOTICE, "{nope", content_type="application/json"
        )

        assert response.status_code == 400
        assert "detail" in response.json()

    def test_it_needs_its_permission(self, client):
        client.force_login(user_with("view_ticket"))

        assert client.get(NOTICE).status_code == 403
        assert post(client, NOTICE, {}).status_code == 403

    def test_a_signed_out_reader_is_sent_to_sign_in(self, client):
        response = client.get(NOTICE)

        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_a_relation_is_fed_like_any_form_s(self, admin_client):
        fields = config_of(admin_client.get(NOTICE))["schema"]["fields"]
        recipients = next(f for f in fields if f["name"] == "recipients")

        assert recipients["relation"] is True
        assert recipients.get("autocompleteUrl") or recipients.get("choices")

    def test_a_relation_accepts_only_its_queryset(self, admin_client):
        gone = UserFactory(username="gone", is_active=False)

        response = post(
            admin_client,
            NOTICE,
            {"recipients": [gone.pk], "title": "Hi", "body": "x"},
        )

        assert response.status_code == 400
        assert set(response.json()) == {"recipients"}


# ---------------------------------------------------------------------
# Several models: a customer with its first ticket
# ---------------------------------------------------------------------


def new_customer(**changes) -> dict:
    team = Team.objects.get(code="FO")
    data = {
        "customer__name": "Northwind",
        "customer__code": "NW",
        "customer__segment": "small",
        "ticket__title": "Set up the account",
        "ticket__team": team.pk,
        "ticket__priority": "normal",
    }
    data.update(changes)

    return data


class TestAFormOverSeveralModels:
    def test_each_part_is_a_section_of_prefixed_fields(
        self, admin_client, support_desk
    ):
        response = admin_client.get(NEW_CUSTOMER)
        schema = config_of(response)["schema"]
        sections = [(s["name"], s["title"]) for s in schema["sections"]]
        fields = {field["name"]: field for field in schema["fields"]}

        assert response.status_code == 200
        assert response.context["resource"].model is Customer
        assert ("customer", "Customer") in sections
        assert ("ticket", "First ticket") in sections
        assert fields["customer__name"]["section"] == "customer"
        assert fields["customer__name"]["width"] == 8
        assert fields["ticket__team"]["section"] == "ticket"
        assert fields["ticket__team"]["relation"] is True
        # The key of each record, and the link filled from the customer
        # part, are not questions.
        assert "customer__id" not in fields
        assert "ticket__customer" not in fields

    def test_both_records_are_written_and_linked(
        self, admin_client, support_desk
    ):
        response = post(admin_client, NEW_CUSTOMER, new_customer())
        answer = response.json()
        customer = Customer.objects.get(code="NW")
        ticket = customer.tickets.get()

        assert response.status_code == 200
        assert ticket.title == "Set up the account"
        assert ticket.reference == "SD-4"
        assert answer["_redirect"] == f"/example/customer/{customer.pk}/"
        assert answer["_message"] == "Northwind was added, with ticket SD-4."

    def test_an_error_in_one_part_writes_nothing(
        self, admin_client, support_desk
    ):
        response = post(
            admin_client, NEW_CUSTOMER, new_customer(ticket__team="")
        )

        assert response.status_code == 400
        assert set(response.json()) == {"ticket__team"}
        assert not Customer.objects.filter(code="NW").exists()

    def test_the_model_validators_run_under_the_prefixed_name(
        self, admin_client, support_desk
    ):
        Customer.objects.create(name="Other", code="NW")

        response = post(admin_client, NEW_CUSTOMER, new_customer())

        assert response.status_code == 400
        assert "customer__code" in response.json()
        assert not Ticket.objects.filter(title="Set up the account").exists()

    def test_a_failure_while_saving_rolls_every_part_back(
        self, admin_client, support_desk, monkeypatch
    ):
        from example.form_pages import NewCustomerForm

        def refuse(self, part, saved):
            if part.name == "ticket":
                raise serializers.ValidationError("No ticket today.")

            return {}

        monkeypatch.setattr(NewCustomerForm, "get_save_kwargs", refuse)

        response = post(admin_client, NEW_CUSTOMER, new_customer())

        assert response.status_code == 400
        assert response.json() == {"non_field_errors": ["No ticket today."]}
        assert not Customer.objects.filter(code="NW").exists()

    def test_it_needs_to_add_both_models(self, client, support_desk):
        client.force_login(user_with("view_customer", "add_customer"))

        assert client.get(NEW_CUSTOMER).status_code == 403

        client.force_login(
            user_with("view_customer", "add_customer", "add_ticket")
        )

        assert client.get(NEW_CUSTOMER).status_code == 200


# ---------------------------------------------------------------------
# One model: reassign a ticket
# ---------------------------------------------------------------------


class TestAFormOverOneModel:
    def test_it_opens_on_the_record(self, admin_client, support_desk):
        ticket = support_desk["login"]

        response = admin_client.get(reassign_url(ticket))
        config = config_of(response)

        assert response.status_code == 200
        assert response.context["object"] == ticket
        assert config["initial"]["team"] == support_desk["front"].pk
        assert config["initial"]["priority"] == "high"
        assert config["initialDisplay"]["team"] == {
            str(support_desk["front"].pk): "Front office"
        }
        assert config["cancelUrl"] == f"/example/ticket/{ticket.pk}/"

    def test_it_saves_the_record(self, admin_client, support_desk):
        ticket = support_desk["login"]
        infra = support_desk["infra"]

        response = post(
            admin_client,
            reassign_url(ticket),
            {"team": infra.pk, "assignee": None, "priority": "low"},
        )
        ticket.refresh_from_db()

        assert response.status_code == 200
        assert response.json()["_redirect"] == f"/example/ticket/{ticket.pk}/"
        assert ticket.team == infra
        assert ticket.assignee is None
        assert ticket.priority == "low"

    def test_it_needs_the_change_permission(self, client, support_desk):
        client.force_login(user_with("view_ticket"))

        assert client.get(reassign_url(support_desk["login"])).status_code in (
            403,
        )

    def test_a_record_out_of_reach_is_a_404(self, admin_client):
        assert (
            admin_client.get("/example/ticket/999999/reassign/").status_code
            == 404
        )


# ---------------------------------------------------------------------
# The declarations
# ---------------------------------------------------------------------


class TestDeclarations:
    def test_a_part_needs_a_model_or_a_serializer(self):
        with pytest.raises(ImproperlyConfigured, match="a model or"):
            FormPart("customer")

    def test_a_part_name_is_a_slug(self):
        with pytest.raises(ImproperlyConfigured, match="name"):
            FormPart("Customer Part", Customer)

    def test_a_link_names_a_field_of_the_model(self):
        with pytest.raises(ImproperlyConfigured, match="not a field"):
            FormPart("ticket", Ticket, links={"client": "customer"})

    def test_a_link_points_to_an_earlier_part(self):
        with pytest.raises(ImproperlyConfigured, match="not a part"):

            class Backwards(ModelsForm):
                parts = (
                    FormPart("ticket", Ticket, links={"customer": "customer"}),
                    FormPart("customer", Customer),
                )

    def test_a_part_and_a_field_cannot_share_a_name(self):
        with pytest.raises(ImproperlyConfigured, match="both a part"):

            class Clash(ModelsForm):
                customer = serializers.BooleanField()
                parts = (FormPart("customer", Customer),)

    def test_a_part_may_bring_its_own_serializer(self):
        class CustomerPart(FormModelSerializer):
            class Meta:
                model = Customer
                fields = ("name", "code")

            form_overrides = {"name": {"placeholder": "ACME"}}

        class Form(ModelsForm):
            parts = (FormPart("customer", serializer=CustomerPart),)

        fields = {
            field["name"]: field for field in Form.get_form_schema()["fields"]
        }

        assert set(fields) == {"customer__name", "customer__code"}
        assert fields["customer__name"]["placeholder"] == "ACME"

    def test_a_form_that_saves_nothing_must_say_what_it_does(self, admin_user):
        class Question(FormSerializer):
            answer = serializers.CharField()

        class Page(FormPageView):
            serializer_class = Question

        request = RequestFactory().post(
            "/q/",
            json.dumps({"answer": "42"}),
            content_type="application/json",
        )
        request.user = admin_user

        with pytest.raises(ImproperlyConfigured, match="form_valid"):
            Page.as_view(site=None)(request)

    def test_a_model_form_page_asks_the_model_permission(self, admin_user):
        class Page(FormPageView):
            serializer_class = type(
                "TeamForm",
                (FormModelSerializer,),
                {
                    "Meta": type(
                        "Meta", (), {"model": Team, "fields": ("name",)}
                    )
                },
            )

        view = Page(request=RequestFactory().get("/"))

        assert view.get_required_permissions() == ["example.add_team"]

    def test_permission_required_is_added(self):
        class Page(FormPageView):
            serializer_class = FormSerializer
            permission_required = ("example.view_ticket", "example.view_team")

        view = Page(request=RequestFactory().get("/"))

        assert view.get_required_permissions() == [
            "example.view_ticket",
            "example.view_team",
        ]


def test_permissions_exist():
    # The permission names the pages compute are real ones.
    for codename in ("add_customer", "add_ticket", "change_ticket"):
        assert Permission.objects.filter(codename=codename).exists()

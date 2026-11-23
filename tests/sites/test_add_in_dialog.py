"""*Add* buttons opening the form in a dialog (``add_in_dialog``).

The equipment of the example has it on: the list's *Add*, a supplier's
Equipment tab and the suppliers' outline open the equipment form over
the page. The tickets keep the default: their *Add* goes to the form.
"""

from __future__ import annotations

import json

import pytest
from django.test import RequestFactory, override_settings

from example.models import Supplier
from generic.sites import site
from generic.views import keep_popup, popup_params
from tests.testapp.models import Book

pytestmark = pytest.mark.django_db

EQUIPMENT = "/example/equipment/"
TICKETS = "/example/ticket/"
SUPPLIERS = "/example/supplier/"


def add_button(response):
    return next(
        item
        for item in response.context["toolbar_items"]
        if item.icon == "add"
    )


class TestTheOption:
    def test_it_is_off_by_default(self):
        from example.models import Ticket

        assert site.get_resource(Ticket).adds_in_dialog() is False

    def test_a_resource_turns_it_on(self):
        from example.models import Equipment

        assert site.get_resource(Equipment).adds_in_dialog() is True

    def test_the_setting_turns_it_on_for_every_resource(self):
        from example.models import Ticket

        with override_settings(GENERIC={"ADD_IN_DIALOG": True}):
            assert site.get_resource(Ticket).adds_in_dialog() is True

    def test_a_resource_wins_over_the_setting(self, monkeypatch):
        from example.models import Ticket

        resource = site.get_resource(Ticket)
        monkeypatch.setattr(resource, "add_in_dialog", False)

        with override_settings(GENERIC={"ADD_IN_DIALOG": True}):
            assert resource.adds_in_dialog() is False


class TestTheButtons:
    def test_the_list_s_add_opens_a_dialog(self, admin_client):
        response = admin_client.get(EQUIPMENT)
        button = add_button(response)

        assert button.dialog is True
        assert (
            f'data-record-dialog="{button.label}"' in response.content.decode()
        )

    def test_by_default_it_goes_to_the_form(self, admin_client):
        response = admin_client.get(TICKETS)

        assert add_button(response).dialog is False
        assert "data-record-dialog" not in response.content.decode()

    def test_a_related_table_s_add_says_so(self, admin_client):
        supplier = Supplier.objects.create(name="Acme")
        body = admin_client.get(
            f"/api/example/supplier/{supplier.pk}/summary/"
        ).json()
        related = {entry["name"]: entry for entry in body["related"]}

        assert related["equipment"]["addInDialog"] is True
        assert related["equipment"]["addUrl"]

    def test_an_outline_level_says_so(self, admin_client):
        outline = admin_client.get(SUPPLIERS).context["table_config"][
            "options"
        ]["outline"]
        top, equipment, visits = outline["levels"]

        assert equipment["addInDialog"] is True
        # The visits' resource keeps the default.
        assert visits["addInDialog"] is False
        assert top["addInDialog"] is False


class TestThePopupParameters:
    def request(self, query: str = ""):
        return RequestFactory().get(f"/x/{query}")

    def test_they_are_kept_across_a_redirect(self):
        request = self.request("?_popup=1&_relation_request=dialog-1&q=a")

        assert popup_params(request) == {
            "_popup": "1",
            "_relation_request": "dialog-1",
        }
        assert (
            keep_popup(request, "/next/?step=2")
            == "/next/?step=2&_popup=1&_relation_request=dialog-1"
        )

    def test_outside_a_popup_nothing_is_added(self):
        request = self.request("?_relation_request=dialog-1")

        assert popup_params(request) == {}
        assert keep_popup(request, "/next/") == "/next/"

    def test_a_parameter_the_address_has_is_left_alone(self):
        request = self.request("?_popup=1&_to_field=id")

        assert (
            keep_popup(request, "/next/?_to_field=pk#top")
            == "/next/?_to_field=pk&_popup=1#top"
        )


class TestAClassicFormInADialog:
    def test_its_answer_names_the_dialog(self, auth_client, library):
        response = auth_client.post(
            "/books/add/?_popup=1&_relation_request=dialog-7",
            {
                "title": "Framed",
                "author": str(library["austen"].pk),
                "genre": "fiction",
                "pages": "120",
                "price": "9.99",
            },
        )
        book = Book.objects.get(title="Framed")

        assert response.status_code == 200
        assert response.context["popup_response_data"] == {
            "action": "create",
            "value": str(book.pk),
            "obj": str(book),
            "requestId": "dialog-7",
        }

    def test_the_form_carries_the_request_through_its_post(
        self, auth_client, library
    ):
        response = auth_client.get(
            "/books/add/?_popup=1&_relation_request=dialog-7"
        )

        assert 'name="_relation_request" value="dialog-7"' in (
            response.content.decode()
        )


class TestAFormPageInADialog:
    URL = "/example/customer/new-with-ticket/"

    def test_it_knows_it_is_framed(self, admin_client):
        response = admin_client.get(
            f"{self.URL}?_popup=1&_relation_request=dialog-3"
        )
        config = response.context["form_config"]

        assert config["popup"] is True
        assert config["popupRequest"] == "dialog-3"
        assert response["X-Frame-Options"] == "SAMEORIGIN"

    def test_outside_a_dialog_it_is_a_page(self, admin_client):
        config = admin_client.get(self.URL).context["form_config"]

        assert config["popup"] is False
        assert config["popupRequest"] == ""

    def test_its_answer_names_what_was_saved(self, admin_client, support_desk):
        ticket = support_desk["login"]
        response = admin_client.post(
            f"/example/ticket/{ticket.pk}/reassign/",
            json.dumps(
                {
                    "team": support_desk["infra"].pk,
                    "assignee": None,
                    "priority": "low",
                }
            ),
            content_type="application/json",
        )
        answer = response.json()

        assert answer["id"] == ticket.pk
        assert answer["_label"] == str(ticket)

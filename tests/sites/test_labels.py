"""Labels to print, each with a QR code (generic.sites.labels).

The example's equipment has them: serial number, kind, supplier.
"""

from __future__ import annotations

import builtins

import pytest
from django.core.exceptions import ImproperlyConfigured

from example.models import Equipment, Ticket
from generic.sites import Labels, ModelResource, site
from generic.sites.labels import MAX_LABELS, check, qr_svg
from tests.sites.test_resource_api import user_with

pytestmark = pytest.mark.django_db

ACTIONS = "/api/example/equipment/actions/"
SHEET = "/example/equipment/labels/"


def run(client, ids=None, **body):
    payload = {"action": "print_labels", **body}

    if ids is not None:
        payload["ids"] = [str(pk) for pk in ids]

    return client.post(ACTIONS, payload, content_type="application/json")


class TestTheAction:
    def test_the_selection_opens_its_sheet(self, admin_client, workshop):
        laptop, headset = workshop["laptop"], workshop["headset"]
        response = run(admin_client, [laptop.pk, headset.pk])

        assert response.status_code == 200, response.content
        redirect = response.json()["redirect"]
        assert redirect.startswith(f"{SHEET}?ids=")
        assert set(redirect.split("=")[1].split(",")) == {
            str(laptop.pk),
            str(headset.pk),
        }

    def test_every_matching_row_too(self, admin_client, workshop):
        response = run(admin_client, all=True)

        assert response.json()["redirect"].count(",") == 1

    def test_too_many_are_refused(self, admin_client, workshop, monkeypatch):
        from generic.sites import labels

        monkeypatch.setattr(labels, "MAX_LABELS", 1)
        answer = run(admin_client, all=True).json()

        assert "redirect" not in answer
        assert answer["level"] == "error"

    def test_a_reader_may_print_them(self, client, workshop):
        client.force_login(user_with("view_equipment"))
        response = run(client, [workshop["laptop"].pk])

        assert response.status_code == 200, response.content
        assert "redirect" in response.json()

    def test_offered_in_the_selection_bar(self, rf, admin_user):
        request = rf.get("/")
        request.user = admin_user
        actions = site.get_resource(Equipment).get_actions(request)

        assert actions["print_labels"].description == "Print labels"

    def test_not_offered_where_none_is_declared(self, rf, admin_user):
        request = rf.get("/")
        request.user = admin_user

        assert "print_labels" not in site.get_resource(Ticket).get_actions(
            request
        )


class TestTheSheet:
    def test_a_label_per_record_with_its_values_and_code(
        self, admin_client, workshop
    ):
        laptop, headset = workshop["laptop"], workshop["headset"]
        response = admin_client.get(
            SHEET, {"ids": f"{laptop.pk},{headset.pk}"}
        )
        html = response.content.decode()

        assert response.status_code == 200
        assert html.count('class="print-label"') == 2
        assert html.count('class="print-label__code"') == 2
        assert "EQ-LA-1" in html
        assert "Nordic Devices" in html
        assert html.index("Latitude 5440") < html.index("Evolve2 55")

    def test_records_the_reader_may_not_see_are_left_out(
        self, client, workshop, monkeypatch
    ):
        client.force_login(user_with("view_equipment"))
        resource = site.get_resource(Equipment)
        hidden = workshop["headset"]
        allowed = resource.has_view_permission
        monkeypatch.setattr(
            resource,
            "has_view_permission",
            lambda request, obj=None: allowed(request, obj)
            and getattr(obj, "pk", None) != hidden.pk,
        )
        html = client.get(
            SHEET, {"ids": f"{workshop['laptop'].pk},{hidden.pk},abc"}
        ).content.decode()

        assert html.count('class="print-label"') == 1
        assert "Evolve2 55" not in html

    def test_without_records_it_says_how_to_get_some(self, admin_client):
        response = admin_client.get(SHEET)

        assert response.status_code == 200
        assert b"No record to label" in response.content

    def test_a_record_s_page_has_its_label(self, admin_client, workshop):
        laptop = workshop["laptop"]
        page = admin_client.get(f"/example/equipment/{laptop.pk}/label/")
        summary = admin_client.get(f"/example/equipment/{laptop.pk}/")

        assert page.content.decode().count('class="print-label"') == 1
        assert f"/example/equipment/{laptop.pk}/label/".encode() in (
            summary.content
        )

    def test_refused_without_the_view_permission(self, client, workshop):
        client.force_login(user_with("view_ticket"))

        assert client.get(SHEET).status_code == 403


class TestTheCode:
    def test_it_holds_the_record_s_absolute_address(self, rf, workshop):
        from generic.sites.labels import describe

        laptop = workshop["laptop"]
        request = rf.get("/", HTTP_HOST="desk.example.test")
        request.user = user_with("view_equipment")
        resource = site.get_resource(Equipment)
        label = describe(resource, request, resource.get_labels(), laptop)

        assert label["content"] == (
            f"http://desk.example.test/example/equipment/{laptop.pk}/"
        )
        assert str(label["code"]).startswith("<svg")
        assert [line["label"] for line in label["lines"]] == [
            "Serial number",
            "Kind",
            "Supplier",
        ]

    def test_content_may_name_a_field(self, rf, workshop):
        from generic.sites.labels import describe

        class Devices(ModelResource):
            labels = Labels(content="serial_number")

        resource = Devices(Equipment, site)
        request = rf.get("/")
        request.user = user_with("view_equipment")
        label = describe(
            resource, request, resource.get_labels(), workshop["laptop"]
        )

        assert label["content"] == "EQ-LA-1"

    def test_without_segno_the_address_is_written_out(self, monkeypatch):
        real = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name == "segno":
                raise ImportError(name)

            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse)

        assert qr_svg("https://desk.example.test/") is None

    def test_no_text_of_the_record_reaches_the_svg(self):
        svg = str(qr_svg('"><script>alert(1)</script>'))

        assert "script" not in svg
        assert "alert" not in svg


class TestCheckedWhereItIsWritten:
    @pytest.mark.parametrize(
        "declared, message",
        [
            (Labels(size="huge"), "size 'huge'"),
            (Labels(fields="name"), "not one string"),
            (Labels(fields=("nope",)), "neither a field"),
            (Labels(content="nope"), "neither a field"),
            ("yes", "True or Labels"),
        ],
    )
    def test_a_declaration_it_cannot_follow(self, declared, message):
        class Devices(ModelResource):
            labels = declared

        with pytest.raises(ImproperlyConfigured, match=message):
            check(Devices(Equipment, site))

    def test_true_takes_the_list_s_first_columns(self):
        class Devices(ModelResource):
            list_display = ("name", "serial_number", "kind", "state", "price")
            labels = True

        assert check(Devices(Equipment, site)).fields == (
            "serial_number",
            "kind",
            "state",
        )

    def test_the_most_a_sheet_holds(self):
        assert MAX_LABELS == 500

"""Custom fields: fields people add to a model while it runs.

The example's equipment is open to them (``auto(Equipment,
custom_fields=True)``): whoever holds ``example.customize_equipment``
adds fields from *Customize fields*, and every screen and endpoint of
the equipment then treats them as its own.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Equipment
from generic.customfields import CustomFields
from generic.customfields.models import (
    CustomField,
    CustomValue,
    parse_choices,
    translated,
)
from generic.customfields.values import load, write
from generic.history.models import HistoryEntry
from generic.sites import site

pytestmark = pytest.mark.django_db

EQUIPMENT = "/api/example/equipment/"
FIELDS = "/api/generic/customfield/"


def user_with(django_user_model, name: str, *codenames: str):
    user = django_user_model.objects.create_user(username=name)
    user.user_permissions.set(
        Permission.objects.filter(codename__in=codenames)
    )

    return user


def define(key: str, kind: str = "text", **options) -> CustomField:
    from django.contrib.contenttypes.models import ContentType

    options.setdefault("labels", {"en": key.replace("_", " ").title()})

    return CustomField.objects.create(
        content_type=ContentType.objects.get_for_model(Equipment),
        key=key,
        type=kind,
        **options,
    )


def resource():
    return site.get_resource(Equipment)


def rows(client, **params) -> list[dict]:
    response = client.get(EQUIPMENT, {"draw": 1, "length": 100, **params})

    assert response.status_code == 200, response.content

    return response.json()["data"]


def filtered(client, filters: dict) -> list[str]:
    return sorted(
        row["serial_number"]
        for row in rows(client, advanced_filters=json.dumps(filters))
    )


@pytest.fixture
def warranty(db) -> CustomField:
    return define(
        "warranty",
        "integer",
        labels={"en": "Warranty", "fr": "Garantie"},
        unit="months",
        minimum="0",
        maximum="60",
    )


@pytest.fixture
def colour(db) -> CustomField:
    return define(
        "colour",
        "choice",
        labels={"en": "Colour", "fr": "Couleur"},
        choices="black | Black | fr: Noir | #111111\nsilver | Silver",
    )


class TestTheDeclaration:
    def test_auto_takes_the_option(self):
        assert resource().custom_fields is True

    def test_off_by_default(self, support_desk):
        from example.models import Ticket

        assert site.get_resource(Ticket).get_custom_fields() == []

    @pytest.mark.parametrize(
        "declared",
        [
            {"types": ("text", "colour")},
            {"types": ()},
            {"max_fields": 0},
        ],
    )
    def test_bad_options_raise(self, declared):
        with pytest.raises(ValueError):
            CustomFields(**declared)

    def test_a_bad_value_raises_where_it_is_declared(self):
        from generic.sites import GenericSite, ModelResource

        class Odd(ModelResource):
            custom_fields = "yes"

        with pytest.raises(ImproperlyConfigured):
            GenericSite(name="odd").register(Equipment, Odd)

    def test_the_permission_is_made_after_migrate(self):
        assert Permission.objects.filter(
            content_type__app_label="example",
            codename="customize_equipment",
        ).exists()

    def test_making_it_again_saves_nothing_and_sends_nothing(self):
        # A flush between browser tests runs it under an event loop: a
        # post_save there would publish an event and fail.
        from django.apps import apps
        from django.db.models.signals import post_save

        from generic.customfields.signals import create_permissions

        Permission.objects.filter(codename="customize_equipment").delete()
        sent = []

        def heard(sender, **kwargs):
            sent.append(sender)

        post_save.connect(heard, sender=Permission)

        try:
            for _again in range(2):
                create_permissions(apps.get_app_config("generic"))
        finally:
            post_save.disconnect(heard, sender=Permission)

        assert sent == []
        assert (
            Permission.objects.filter(codename="customize_equipment").count()
            == 1
        )


class TestTheDefinition:
    def test_labels_follow_the_language(self, warranty):
        from django.utils import translation

        with translation.override("fr"):
            assert warranty.label() == "Garantie"

        with translation.override("de"):
            # Not written in German: the project's language.
            assert warranty.label() == "Warranty"

    def test_translated_falls_back_on_any_label(self):
        assert translated({"fr": "Couleur"}, "en") == "Couleur"
        assert translated({}, "en") == ""

    def test_choices_are_read_from_their_lines(self):
        choices = parse_choices(
            "black | Black | fr: Noir | #111111\nsilver\n\nblue | Blue"
        )

        assert choices == [
            {
                "value": "black",
                "labels": {"en": "Black", "fr": "Noir"},
                "color": "#111111",
            },
            {"value": "silver", "labels": {"en": "silver"}, "color": ""},
            # "Blue" is a CSS colour too, and a label first.
            {"value": "blue", "labels": {"en": "Blue"}, "color": ""},
        ]

    def test_a_choice_twice_is_refused(self):
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            parse_choices("black\nblack")


class TestTheTable:
    def test_a_column_per_field(self, admin_client, workshop, warranty):
        hidden = define("notes", "textarea", in_list=False)
        config = resource().get_table_config(_request(admin_client))
        columns = {column["data"]: column for column in config["columns"]}

        assert columns["cf_warranty"]["title"] == "Warranty (months)"
        assert columns["cf_warranty"]["type"] == "integer"
        assert columns[hidden.name].get("visible") is False

    def test_rows_carry_their_values(self, admin_client, workshop, warranty):
        write(resource(), workshop["laptop"], {"warranty": 24})
        found = {row["serial_number"]: row for row in rows(admin_client)}

        assert found["EQ-LA-1"]["cf_warranty"] == 24
        assert found["EQ-HE-2"]["cf_warranty"] is None

    def test_filtered_and_ordered(self, admin_client, workshop, warranty):
        write(resource(), workshop["laptop"], {"warranty": 24})
        write(resource(), workshop["headset"], {"warranty": 6})

        assert filtered(
            admin_client,
            {"cf_warranty": {"operator": "greater_than", "value": 12}},
        ) == ["EQ-LA-1"]

        ordered = rows(
            admin_client,
            **{
                "columns[0][data]": "cf_warranty",
                "order[0][column]": "0",
                "order[0][dir]": "asc",
            },
        )

        assert [row["serial_number"] for row in ordered] == [
            "EQ-HE-2",
            "EQ-LA-1",
        ]

    def test_a_choice_is_a_tag(self, admin_client, workshop, colour):
        write(resource(), workshop["laptop"], {"colour": "black"})
        found = {row["serial_number"]: row for row in rows(admin_client)}

        assert found["EQ-LA-1"]["cf_colour"] == [
            {"label": "Black", "color": "#111111", "value": "black"}
        ]
        assert filtered(
            admin_client,
            {"cf_colour": {"operator": "any_of", "value": ["black"]}},
        ) == ["EQ-LA-1"]

    def test_text_is_searched(self, admin_client, workshop):
        define("location", "text")
        write(resource(), workshop["headset"], {"location": "Basement"})
        found = rows(admin_client, **{"search[value]": "basement"})

        assert [row["serial_number"] for row in found] == ["EQ-HE-2"]

    def test_exported(self, admin_client, workshop, warranty):
        write(resource(), workshop["laptop"], {"warranty": 24})
        response = admin_client.get(f"{EQUIPMENT}export-csv/")
        body = b"".join(response.streaming_content).decode("utf-8-sig")
        header, *lines = body.splitlines()

        assert "Warranty (months)" in header
        assert any("24" in line for line in lines)

    def test_an_archived_field_is_no_column(
        self, admin_client, workshop, warranty
    ):
        warranty.archived = True
        warranty.save()

        assert "cf_warranty" not in rows(admin_client)[0]


class TestTheForm:
    def test_the_schema_has_a_section(self, admin_client, warranty):
        schema = admin_client.get(f"{EQUIPMENT}form-schema/").json()
        fields = {field["name"]: field for field in schema["fields"]}
        sections = [section["name"] for section in schema["sections"]]

        assert fields["cf_warranty"]["section"] == "custom-fields"
        assert fields["cf_warranty"]["maximum"] == 60
        assert sections[-1] == "custom-fields"

    def test_a_record_is_created_with_its_values(
        self, admin_client, workshop, warranty, colour
    ):
        response = admin_client.post(
            EQUIPMENT,
            {
                "name": "ThinkPad",
                "serial_number": "EQ-TP-3",
                "kind": "laptop",
                "state": "spare",
                "supplier": workshop["supplier"].pk,
                "cf_warranty": 36,
                "cf_colour": "silver",
            },
            content_type="application/json",
        )

        assert response.status_code == 201, response.content
        created = Equipment.objects.get(serial_number="EQ-TP-3")

        assert load(resource(), created) == {
            "warranty": 36,
            "colour": "silver",
        }
        assert response.json()["cf_warranty"] == 36

    def test_limits_are_kept(self, admin_client, workshop, warranty):
        laptop = workshop["laptop"]
        response = admin_client.patch(
            f"{EQUIPMENT}{laptop.pk}/",
            {"cf_warranty": 99},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "cf_warranty" in response.json()

    def test_a_value_is_cleared(self, admin_client, workshop, warranty):
        laptop = workshop["laptop"]
        write(resource(), laptop, {"warranty": 12})
        response = admin_client.patch(
            f"{EQUIPMENT}{laptop.pk}/",
            {"cf_warranty": None},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        assert not CustomValue.objects.filter(field=warranty).exists()

    def test_required_is_asked(self, admin_client, workshop):
        define("asset_tag", required=True)
        response = admin_client.post(
            EQUIPMENT,
            {
                "name": "ThinkPad",
                "serial_number": "EQ-TP-3",
                "kind": "laptop",
                "state": "spare",
                "supplier": workshop["supplier"].pk,
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "cf_asset_tag" in response.json()


class TestThePermissions:
    def test_a_field_some_may_not_see(
        self, client, django_user_model, workshop, warranty
    ):
        warranty.view_permission = "example.change_equipment"
        warranty.save()
        client.force_login(
            user_with(django_user_model, "reader", "view_equipment")
        )

        assert "cf_warranty" not in rows(client)[0]
        record = client.get(f"{EQUIPMENT}{workshop['laptop'].pk}/").json()
        assert "cf_warranty" not in record

    def test_a_field_some_may_not_change(
        self, client, django_user_model, workshop, warranty
    ):
        warranty.change_permission = "example.delete_equipment"
        warranty.save()
        client.force_login(
            user_with(
                django_user_model,
                "editor",
                "view_equipment",
                "change_equipment",
            )
        )
        laptop = workshop["laptop"]
        client.patch(
            f"{EQUIPMENT}{laptop.pk}/",
            {"cf_warranty": 12, "name": "Renamed"},
            content_type="application/json",
        )

        assert not CustomValue.objects.filter(field=warranty).exists()


class TestTheSummary:
    def test_a_section_of_its_own(self, admin_client, workshop, warranty):
        laptop = workshop["laptop"]
        write(resource(), laptop, {"warranty": 24})
        summary = admin_client.get(f"{EQUIPMENT}{laptop.pk}/summary/").json()
        section = summary["sections"][-1]

        assert section["name"] == "custom-fields"
        assert section["title"] == "Additional fields"
        assert section["fields"][0]["display"] == "24 months"


class TestTheHistory:
    def test_a_change_is_a_version(self, admin_client, workshop, warranty):
        laptop = workshop["laptop"]
        admin_client.patch(
            f"{EQUIPMENT}{laptop.pk}/",
            {"cf_warranty": 24, "name": "Latitude 7440"},
            content_type="application/json",
        )
        entry = HistoryEntry.objects.of(laptop).order_by("-version").first()

        assert entry.values["cf:warranty"] == 24
        assert entry.values["name"] == "Latitude 7440"

        history = admin_client.get(f"{EQUIPMENT}{laptop.pk}/history/").json()
        changes = {
            change["name"]: change
            for change in history["results"][0]["changes"]
        }

        assert changes["cf:warranty"]["label"] == "Warranty"
        assert changes["cf:warranty"]["to"] == "24"
        assert changes["name"]["to"] == "Latitude 7440"

    def test_a_save_carries_the_values(self, workshop, warranty):
        laptop = workshop["laptop"]
        write(resource(), laptop, {"warranty": 24})
        laptop.name = "Renamed"
        laptop.save()
        entry = HistoryEntry.objects.of(laptop).order_by("-version").first()

        assert entry.values["name"] == "Renamed"
        assert entry.values["cf:warranty"] == 24

    def test_a_deleted_record_takes_its_values(self, workshop, warranty):
        laptop = workshop["laptop"]
        write(resource(), laptop, {"warranty": 24})
        laptop.maintenances.all().delete()
        key = str(laptop.pk)
        laptop.delete()

        assert not CustomValue.objects.exists()
        entry = HistoryEntry.objects.of(Equipment).get(
            object_id=key, action="deleted"
        )
        assert entry.values["cf:warranty"] == 24


class TestCustomizing:
    def test_the_list_offers_it(self, admin_client):
        page = admin_client.get("/example/equipment/")

        assert "Customize fields" in page.content.decode()

    def test_not_without_the_permission(self, client, django_user_model):
        client.force_login(
            user_with(django_user_model, "reader", "view_equipment")
        )
        page = client.get("/example/equipment/")

        assert "Customize fields" not in page.content.decode()
        assert client.get(FIELDS).status_code == 403

    def test_a_field_is_added(self, client, django_user_model):
        client.force_login(
            user_with(
                django_user_model,
                "designer",
                "view_equipment",
                "customize_equipment",
            )
        )
        response = client.post(
            FIELDS,
            {
                "model": "example.equipment",
                "type": "decimal",
                "key": "weight",
                "label_en": "Weight",
                "label_fr": "Poids",
                "unit": "kg",
                "minimum": "0",
                "decimal_places": 1,
            },
            content_type="application/json",
        )

        assert response.status_code == 201, response.content
        definition = CustomField.objects.get(key="weight")
        assert definition.labels == {"en": "Weight", "fr": "Poids"}
        assert definition.content_type.model == "equipment"

        record = client.get(f"{FIELDS}{definition.pk}/").json()
        assert record["label_fr"] == "Poids"
        assert record["model"] == "example.equipment"

    @pytest.mark.parametrize(
        "changes, field",
        [
            ({"key": "Bad key"}, "key"),
            ({"key": "name"}, None),
            ({"minimum": "ten"}, "minimum"),
            ({"minimum": "9", "maximum": "1"}, "minimum"),
            ({"label_en": ""}, "label_en"),
            ({"type": "choice"}, "choices"),
            ({"view_permission": "nope"}, "view_permission"),
            ({"model": "example.ticket"}, "model"),
        ],
    )
    def test_what_is_refused(self, admin_client, changes, field):
        body = {
            "model": "example.equipment",
            "type": "integer",
            "key": "weight",
            "label_en": "Weight",
            **changes,
        }
        response = admin_client.post(
            FIELDS, body, content_type="application/json"
        )

        if field is None:
            # "cf_name" is not the model's "name": accepted.
            assert response.status_code == 201, response.content
            return

        assert response.status_code == 400, response.content
        assert field in response.json()

    def test_the_type_stays_once_values_exist(
        self, admin_client, workshop, warranty
    ):
        write(resource(), workshop["laptop"], {"warranty": 3})
        response = admin_client.patch(
            f"{FIELDS}{warranty.pk}/",
            {"type": "text"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "type" in response.json()

    def test_archive_and_restore(self, admin_client, warranty):
        response = admin_client.post(
            f"{FIELDS}actions/",
            {"action": "archive", "ids": [warranty.pk]},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        warranty.refresh_from_db()
        assert warranty.archived


def _request(client):
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory

    request = RequestFactory().get("/")
    request.user = get_user_model().objects.get(username="admin")

    return request


class TestUndo:
    def test_a_deleted_record_comes_back_with_its_values(
        self, admin_client, workshop, warranty
    ):
        headset = workshop["headset"]
        write(resource(), headset, {"warranty": 12})
        answer = admin_client.delete(f"{EQUIPMENT}{headset.pk}/?undo=1")

        assert answer.status_code == 200, answer.content
        assert not CustomValue.objects.exists()

        response = admin_client.post(
            f"{EQUIPMENT}undo/",
            {"token": answer.json()["undo"]["token"]},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        back = Equipment.objects.get(pk=headset.pk)
        assert load(resource(), back) == {"warranty": 12}

    def test_a_change_is_taken_back(self, admin_client, workshop, warranty):
        laptop = workshop["laptop"]
        write(resource(), laptop, {"warranty": 12})
        response = admin_client.post(
            f"{EQUIPMENT}bulk-edit/",
            {
                "ids": [str(laptop.pk)],
                "changes": {"state": {"mode": "set", "value": "repair"}},
                "commit": True,
            },
            content_type="application/json",
        )
        answer = response.json()
        write(resource(), Equipment.objects.get(pk=laptop.pk), {})

        assert "undo" in answer, answer
        undone = admin_client.post(
            f"{EQUIPMENT}undo/",
            {"token": answer["undo"]["token"]},
            content_type="application/json",
        )

        assert undone.status_code == 200, undone.content
        back = Equipment.objects.get(pk=laptop.pk)
        assert back.state == "in_use"
        assert load(resource(), back) == {"warranty": 12}


class TestTypes:
    @pytest.mark.parametrize(
        "kind, given, kept",
        [
            ("text", "Desk 4", "Desk 4"),
            ("textarea", "Line one\nline two", "Line one\nline two"),
            ("email", "it@example.test", "it@example.test"),
            ("url", "https://example.test/a", "https://example.test/a"),
            ("integer", 7, 7),
            ("decimal", "2.5", Decimal("2.50")),
            ("boolean", True, True),
            ("date", "2027-03-31", datetime.date(2027, 3, 31)),
            ("time", "08:30", datetime.time(8, 30)),
        ],
    )
    def test_written_through_the_api_and_read_back(
        self, admin_client, workshop, kind, given, kept
    ):
        define("value", kind)
        laptop = workshop["laptop"]
        response = admin_client.patch(
            f"{EQUIPMENT}{laptop.pk}/",
            {"cf_value": given},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        assert load(resource(), Equipment.objects.get(pk=laptop.pk)) == {
            "value": kept
        }
        assert rows(admin_client)[0]["cf_value"] is not None or (
            rows(admin_client)[1]["cf_value"] is not None
        )

    def test_a_date_and_time_keeps_its_instant(self, admin_client, workshop):
        define("seen", "datetime")
        laptop = workshop["laptop"]
        response = admin_client.patch(
            f"{EQUIPMENT}{laptop.pk}/",
            {"cf_seen": "2027-03-31T08:30:00+02:00"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        value = load(resource(), Equipment.objects.get(pk=laptop.pk))["seen"]
        assert value == datetime.datetime(
            2027, 3, 31, 6, 30, tzinfo=datetime.timezone.utc
        )

    def test_a_date_out_of_its_limits_is_refused(self, admin_client, workshop):
        define("ends", "date", minimum="2026-01-01")
        laptop = workshop["laptop"]
        response = admin_client.patch(
            f"{EQUIPMENT}{laptop.pk}/",
            {"cf_ends": "2025-12-31"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "cf_ends" in response.json()

    def test_facets_count_the_values(self, admin_client, workshop, colour):
        write(resource(), workshop["laptop"], {"colour": "black"})
        write(resource(), workshop["headset"], {"colour": "black"})
        response = admin_client.get(
            f"{EQUIPMENT}facets/", {"column": "cf_colour"}
        )

        assert response.status_code == 200, response.content
        assert "black" in json.dumps(response.json())

    def test_a_related_table_has_the_columns(
        self, admin_client, workshop, warranty
    ):
        supplier = workshop["supplier"]
        write(resource(), workshop["laptop"], {"warranty": 24})
        found = rows(
            admin_client, _related=f"example.supplier.equipment:{supplier.pk}"
        )

        assert {row["cf_warranty"] for row in found} == {24, None}


class TestTheDefinitionsPage:
    def test_narrowed_to_what_the_reader_may_customize(
        self, client, django_user_model, warranty
    ):
        from django.contrib.contenttypes.models import ContentType

        from example.models import Supplier

        CustomField.objects.create(
            content_type=ContentType.objects.get_for_model(Supplier),
            key="rating",
            labels={"en": "Rating"},
        )
        client.force_login(
            user_with(django_user_model, "designer", "customize_equipment")
        )
        found = client.get(FIELDS, {"draw": 1, "length": 10}).json()["data"]

        assert [row["key"] for row in found] == ["warranty"]

    def test_the_list_names_each_field_s_model(self, admin_client, warranty):
        found = admin_client.get(FIELDS, {"draw": 1, "length": 10}).json()

        assert found["data"][0]["model_display"] == "Equipment"

    def test_the_list_page_and_its_form_open(self, admin_client, warranty):
        assert admin_client.get("/generic/customfield/").status_code == 200
        form = admin_client.get(f"/generic/customfield/{warranty.pk}/change/")

        assert form.status_code == 200
        schema = admin_client.get(f"{FIELDS}form-schema/").json()
        names = [field["name"] for field in schema["fields"]]

        assert {"model", "key", "type", "label_en", "label_fr"} <= set(names)

    def test_a_definition_keeps_a_history(self, admin_client, warranty):
        admin_client.patch(
            f"{FIELDS}{warranty.pk}/",
            {"label_fr": "Garantie constructeur"},
            content_type="application/json",
        )
        warranty.refresh_from_db()

        assert warranty.labels["fr"] == "Garantie constructeur"
        assert warranty.labels["en"] == "Warranty"
        assert HistoryEntry.objects.of(warranty).count() == 2

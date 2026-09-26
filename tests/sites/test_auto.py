"""Pages worked out from the model: ``auto()`` and ``AutoResource``.

The example's equipment is declared with two lines; everything below is
what the framework made of them, and what a declaration still decides.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from example.models import Equipment, Maintenance, Supplier, TicketComment
from generic.sites import AutoResource, site
from generic.sites.auto import (
    PALETTE,
    infer_form_rows,
    infer_icon,
    infer_list_display,
    infer_search_fields,
    inline_fields,
)
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

EQUIPMENT = "/api/example/equipment/"


@pytest.fixture
def other_site():
    """A site of the test's own, emptied afterwards: registering a model
    connects its history and its live updates, which must not outlive
    the test."""
    from generic.sites.site import GenericSite

    created = GenericSite(name="auto_test")

    yield created

    for resource in created.get_resources():
        created.unregister(resource.model)


class TestTheList:
    def test_the_naming_field_comes_first(self):
        assert infer_list_display(Equipment) == (
            "name",
            "serial_number",
            "kind",
            "state",
            "supplier",
            "assigned_to",
            "purchased_on",
        )

    def test_long_text_is_no_column(self):
        assert "notes" not in infer_list_display(Supplier, limit=20)

    def test_without_a_name_the_first_text_names_the_row(self):
        """A visit has no ``name``: its description says what it was."""
        assert infer_list_display(Maintenance)[0] == "description"

    def test_a_secret_is_never_a_column(self):
        columns = infer_list_display(get_user_model(), limit=20)

        assert "password" not in columns
        assert "username" in columns

    def test_a_date_the_application_keeps_is_one(self):
        """``created_at`` is written by nobody, and worth a column."""
        assert "created_at" in infer_list_display(Author)

    def test_at_most_so_many(self):
        assert len(infer_list_display(Equipment, limit=3)) == 3


class TestTheRest:
    def test_the_search_reaches_the_records_a_row_points_at(self):
        fields = infer_search_fields(Equipment)

        assert fields[0] == "name"
        assert {"supplier__name", "assigned_to__name"} <= set(fields)
        # A choice is filtered, not searched.
        assert "kind" not in fields

    def test_every_choice_gets_its_own_colour(self):
        styles = site.get_resource(Equipment).tag_fields

        assert set(styles) == {"kind", "state"}
        assert styles["kind"].colors["laptop"] == PALETTE[0]
        assert styles["kind"].colors["screen"] == PALETTE[1]

    def test_the_form_goes_two_fields_a_row(self):
        assert infer_form_rows(Equipment) == (
            "name",
            ("serial_number", "kind"),
            ("state", "supplier"),
            ("assigned_to", "purchased_on"),
            "price",
            "notes",
        )

    def test_the_summary_adds_what_the_application_keeps(self, other_site):
        other_site.auto(Author)
        resource = other_site.get_resource(Author)

        rows = resource.detail_fieldsets[0][1]["fields"]

        assert "created_at" in rows
        assert "created_at" not in resource.fieldsets[0][1]["fields"]

    @pytest.mark.parametrize(
        "name,icon",
        [
            ("Equipment", "devices"),
            ("Supplier", "local_shipping"),
            ("MaintenanceVisit", "build"),
            ("TaskReports", "task_alt"),
            ("Frobnicator", "table_rows"),
        ],
    )
    def test_an_icon_from_the_name(self, name, icon):
        assert infer_icon(type(name, (), {})) == icon


class TestRelatedRows:
    def test_each_gets_a_table_on_the_summary(self):
        resource = site.get_resource(Equipment)

        assert [table.name for table in resource.related_tables] == [
            "maintenances"
        ]

    def test_a_reverse_foreign_key_is_edited_on_the_form(self):
        (inline,) = site.get_resource(Equipment).inlines

        assert inline.model is Maintenance
        assert inline.fk_name == "equipment"
        assert inline.fields == (
            "performed_on",
            "description",
            "cost",
            "is_done",
        )
        assert "tab" in inline.classes

    def test_a_row_shows_what_it_cannot_be_saved_without(self):
        """A comment's body is long text, and required: it is shown."""
        fk = TicketComment._meta.get_field("ticket")

        assert {"author", "body"} <= set(inline_fields(TicketComment, fk))

    def test_a_related_model_nobody_declared_gets_pages(self):
        """Maintenance is named by the equipment, and declared nowhere."""
        resource = site.get_resource(Maintenance)

        assert isinstance(resource, AutoResource)
        assert resource.show_in_navigation is False

    def test_it_is_out_of_the_navigation(self, rf, admin_user):
        request = rf.get("/")
        request.user = admin_user
        groups = site.get_navigation(request)
        equipment = next(
            group for group in groups if group["label"] == "Equipment"
        )

        assert [item["label"] for item in equipment["items"]] == [
            "Suppliers",
            "Equipment",
        ]

    def test_a_name_that_is_no_relation_is_refused(self, other_site):
        with pytest.raises(ImproperlyConfigured, match="maintenances"):
            other_site.auto(Equipment, related=("repairs",))

    def test_a_single_record_is_no_rows(self, other_site):
        with pytest.raises(ImproperlyConfigured, match="one record"):
            other_site.auto(Equipment, related=("supplier",))

    def test_rows_may_stay_off_the_form(self, other_site):
        """A relation with hundreds of rows: its table, and no tab."""
        other_site.auto(
            Equipment, related=("maintenances",), related_inlines=()
        )
        resource = other_site.get_resource(Equipment)

        assert resource.inlines == ()
        assert len(resource.related_tables) == 1

    def test_a_related_model_declared_later_keeps_its_declaration(
        self,
        other_site,
    ):
        other_site.auto(Supplier, related=("equipment",))
        other_site.auto(Equipment, list_display=("name",))
        other_site.complete_auto()

        assert other_site.get_resource(Equipment).list_display == ("name",)
        assert other_site.get_resource(Equipment).show_in_navigation

    def test_one_declared_nowhere_is_completed(self, other_site):
        other_site.auto(Supplier, related=("equipment",))

        assert not other_site.is_registered(Equipment)

        other_site.complete_auto()

        assert isinstance(other_site.get_resource(Equipment), AutoResource)


class TestADeclarationWins:
    def test_what_is_declared_is_kept(self, other_site):
        other_site.auto(Equipment, list_display=("name", "price"))
        resource = other_site.get_resource(Equipment)

        assert resource.list_display == ("name", "price")
        # And the rest is still worked out.
        assert "supplier__name" in resource.search_fields

    def test_a_class_declares_the_same_way(self, other_site):
        class EquipmentResource(AutoResource):
            icon = "laptop"
            exclude = ("notes", "price")

        other_site.register(Equipment, EquipmentResource)
        resource = other_site.get_resource(Equipment)

        assert resource.icon == "laptop"
        # Left out of the form, the list and the search alike.
        assert "price" not in resource.get_fields()
        assert "notes" not in resource.search_fields

    def test_declared_fields_keep_their_layout(self, other_site):
        other_site.auto(Supplier, fields=("name", "email"))
        resource = other_site.get_resource(Supplier)

        assert resource.get_fields() == ["name", "email"]

    def test_choices_may_stay_plain(self, other_site):
        other_site.auto(Equipment, tag_choices=False)

        assert other_site.get_resource(Equipment).tag_fields == {}


class TestThePagesWork:
    """What the two lines in example/resources.py give, end to end."""

    def test_the_list_shows_the_columns(self, admin_client, workshop):
        page = admin_client.get("/example/equipment/")
        columns = [
            column["data"]
            for column in page.context["table_config"]["columns"]
        ]

        assert page.status_code == 200
        assert columns[:3] == ["name", "serial_number", "kind"]

    def test_the_rows_carry_their_tags(self, admin_client, workshop):
        response = admin_client.get(
            f"{EQUIPMENT}?draw=1&length=10&search[value]=Latitude"
        )
        (row,) = response.json()["data"]

        assert row["kind"] == [
            {"label": "Laptop", "color": PALETTE[0], "value": "laptop"}
        ]

    def test_a_search_finds_the_supplier_s_name(self, admin_client, workshop):
        response = admin_client.get(
            f"{EQUIPMENT}?draw=1&length=10&search[value]=Nordic"
        )

        assert response.json()["recordsFiltered"] == 2

    def test_the_summary_has_the_related_table(self, admin_client, workshop):
        laptop = workshop["laptop"]
        page = admin_client.get(f"/example/equipment/{laptop.pk}/")
        summary = admin_client.get(f"{EQUIPMENT}{laptop.pk}/summary/").json()

        assert page.status_code == 200
        assert [table["name"] for table in page.context["related_tables"]] == [
            "maintenances"
        ]
        assert [
            (entry["name"], entry["count"]) for entry in summary["related"]
        ] == [("maintenances", 1)]

    def test_the_form_edits_the_related_rows(self, admin_client, workshop):
        laptop = workshop["laptop"]
        schema = admin_client.get(f"{EQUIPMENT}form-schema/").json()

        assert [inline["name"] for inline in schema["inlines"]] == [
            "maintenances"
        ]

        response = admin_client.patch(
            f"{EQUIPMENT}{laptop.pk}/",
            {
                "state": "repair",
                "_inlines": {
                    "maintenances": [
                        {"description": "Hinge tightened", "cost": "0"}
                    ]
                },
            },
            content_type="application/json",
        )

        assert response.status_code == 200, response.content

        laptop.refresh_from_db()

        assert laptop.state == Equipment.State.REPAIR
        assert laptop.maintenances.count() == 2

    def test_a_record_is_created_from_the_worked_out_form(
        self,
        admin_client,
        workshop,
    ):
        response = admin_client.post(
            EQUIPMENT,
            {
                "name": "ProArt 24",
                "serial_number": "EQ-SC-3",
                "kind": "screen",
                "supplier": workshop["supplier"].pk,
                "price": "320.00",
            },
            content_type="application/json",
        )

        assert response.status_code == 201, response.content
        assert Equipment.objects.get(serial_number="EQ-SC-3").price == (
            Decimal("320.00")
        )

    def test_a_supplier_still_used_cannot_be_deleted(
        self,
        admin_client,
        workshop,
    ):
        supplier = workshop["supplier"]
        page = admin_client.get(f"/example/supplier/{supplier.pk}/delete/")

        assert page.context["deletion"]["can_delete"] is False

    def test_a_reader_without_the_permission_is_refused(
        self,
        client,
        django_user_model,
        workshop,
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))

        assert client.get("/example/equipment/").status_code == 403

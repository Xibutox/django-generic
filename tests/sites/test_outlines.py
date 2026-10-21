"""Outlines: a list unfolding into its related records, level by level.

The example declares two: suppliers > equipment > maintenance visits,
with ``auto()``, and customers > tickets > time entries, by hand. The
browser names a level by its number and a record by its key; the rest
is the declaration's and the resources'.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Equipment, Maintenance, Supplier
from generic.sites import AutoResource, Level, ModelResource, Outline, site
from generic.sites.outlines import as_outline
from tests.testapp.models import Author, Document

pytestmark = pytest.mark.django_db

OUTLINE = "/api/example/supplier/outline/"
SUPPLIERS = "/example/supplier/"


def get(client, url: str = OUTLINE, status: int = 200, **params) -> dict:
    response = client.get(url, params)

    assert response.status_code == status, response.content

    return response.json() if status == 200 else {}


def names(answer: dict, column: str = "name") -> list[str]:
    return [item["row"][column] for item in answer["items"]]


@pytest.fixture
def stock(db) -> dict:
    """Two suppliers, three pieces of equipment, three visits."""
    acme = Supplier.objects.create(name="Acme", country="France")
    bolt = Supplier.objects.create(name="Bolt", country="Spain")
    Supplier.objects.create(name="Crane", country="France")
    laptop = Equipment.objects.create(
        name="Laptop", serial_number="L-1", supplier=acme
    )
    screen = Equipment.objects.create(
        name="Screen", serial_number="S-1", supplier=acme
    )
    phone = Equipment.objects.create(
        name="Phone", serial_number="P-1", supplier=bolt
    )

    for description in ("Battery", "Keyboard"):
        Maintenance.objects.create(equipment=laptop, description=description)

    Maintenance.objects.create(
        equipment=phone, description="Screen", cost=Decimal("12.50")
    )

    return {
        "acme": acme,
        "bolt": bolt,
        "laptop": laptop,
        "screen": screen,
        "phone": phone,
    }


def client_with(client, django_user_model, *codenames: str):
    user = django_user_model.objects.create_user(username="reader")
    user.user_permissions.set(
        Permission.objects.filter(codename__in=codenames)
    )
    client.force_login(user)

    return client


@pytest.fixture
def redeclare():
    """Give the example's supplier resource another outline for a
    test, its own put back afterwards."""
    resource = site.get_resource(Supplier)
    before = resource.outline

    def declare(outline):
        resource.outline = outline
        resource.__dict__.pop("_bound_outline", None)

        return resource

    yield declare

    declare(before)


@pytest.fixture
def other_site():
    from generic.sites.site import GenericSite

    created = GenericSite(name="outline_test")

    yield created

    for resource in created.get_resources():
        created.unregister(resource.model)


class TestTheDeclaration:
    def test_relation_names_are_an_outline(self):
        outline = as_outline(("equipment", "maintenances"), "R")

        assert [level.name for level in outline.levels] == [
            "equipment",
            "maintenances",
        ]
        assert as_outline("equipment", "R").levels == (Level("equipment"),)
        assert as_outline(None, "R") is None

    def test_the_example_walks_down_two_relations(self):
        bound = site.get_resource(Supplier).get_outline()

        assert [level.model for level in bound.levels] == [
            Supplier,
            Equipment,
            Maintenance,
        ]
        # Each level's records are found by their way back up.
        assert [level.back for level in bound.levels] == [
            "",
            "supplier",
            "equipment",
        ]

    def test_a_name_that_is_no_relation_is_refused(self, other_site):
        with pytest.raises(ImproperlyConfigured, match="maintenances"):
            other_site.auto(Equipment, outline=("repairs",))

    def test_each_name_is_a_relation_of_the_level_above(self, other_site):
        """``maintenances`` is the equipment's, not the supplier's."""
        with pytest.raises(ImproperlyConfigured, match="equipment"):
            other_site.auto(Supplier, outline=("maintenances",))

    def test_a_single_record_is_no_level(self, other_site):
        with pytest.raises(ImproperlyConfigured, match="one record"):
            other_site.auto(Equipment, outline=("supplier",))

    def test_something_else_is_refused(self, other_site):
        with pytest.raises(ImproperlyConfigured, match="Outline"):
            other_site.auto(Supplier, outline=3)

    @pytest.mark.parametrize(
        "options,message",
        [
            ({"page_size": 0}, "page_size"),
            ({"max_columns": 0}, "max_columns"),
            ({"columns": "name"}, "columns"),
        ],
    )
    def test_its_options_are_checked(self, other_site, options, message):
        with pytest.raises(ImproperlyConfigured, match=message):
            other_site.auto(Supplier, outline=Outline("equipment", **options))

    def test_at_least_one_level(self, other_site):
        with pytest.raises(ImproperlyConfigured, match="no level"):
            other_site.auto(Supplier, outline=Outline())

    def test_a_column_the_level_has_not_is_refused(
        self, redeclare, rf, admin_user
    ):
        resource = redeclare(Outline(Level("equipment", columns=("colour",))))
        request = rf.get("/")
        request.user = admin_user

        with pytest.raises(ImproperlyConfigured, match="colour"):
            resource.get_outline_config(request)

    def test_a_level_nobody_registered_is_named(
        self, other_site, rf, admin_user
    ):
        other_site.register(Supplier, ModelResource, outline=("equipment",))
        request = rf.get("/")
        request.user = admin_user

        with pytest.raises(ImproperlyConfigured, match="not registered"):
            other_site.get_resource(Supplier).get_outline_config(request)

    def test_auto_gives_the_levels_pages_of_their_own(self, other_site):
        """Maintenance is named by the outline only, and gets pages."""
        other_site.auto(Supplier, outline=("equipment", "maintenances"))
        other_site.complete_auto()

        for model in (Equipment, Maintenance):
            resource = other_site.get_resource(model)

            assert isinstance(resource, AutoResource)
            assert resource.show_in_navigation is False


class TestTheEndpoint:
    def test_the_top_is_the_list_with_what_each_holds(
        self, admin_client, stock
    ):
        answer = get(admin_client)

        assert names(answer) == ["Acme", "Bolt", "Crane"]
        assert [item["children"] for item in answer["items"]] == [2, 1, 0]
        assert answer["total"] == 3
        acme = answer["items"][0]
        assert acme["id"] == str(stock["acme"].pk)
        assert acme["url"] == f"/example/supplier/{stock['acme'].pk}/"
        # The row is the table's own: what its renderers read.
        assert acme["row"]["_pk"] == stock["acme"].pk

    def test_the_top_follows_the_table(self, admin_client, stock):
        filters = {
            "match": "all",
            "conditions": [
                {"column": "country", "operator": "equals", "value": "France"}
            ],
        }

        assert names(get(admin_client, filters=json.dumps(filters))) == [
            "Acme",
            "Crane",
        ]
        assert names(get(admin_client, search="bol")) == ["Bolt"]
        assert names(get(admin_client, ordering="-name")) == [
            "Crane",
            "Bolt",
            "Acme",
        ]

    def test_a_record_unfolds_into_the_next_level(self, admin_client, stock):
        answer = get(admin_client, level=1, parent=stock["acme"].pk)

        assert names(answer) == ["Laptop", "Screen"]
        assert [item["children"] for item in answer["items"]] == [2, 0]
        assert answer["items"][0]["url"] == (
            f"/example/equipment/{stock['laptop'].pk}/"
        )

    def test_the_last_level_holds_nothing(self, admin_client, stock):
        answer = get(admin_client, level=2, parent=stock["laptop"].pk)

        assert sorted(names(answer, "description")) == [
            "Battery",
            "Keyboard",
        ]
        assert {item["children"] for item in answer["items"]} == {0}

    def test_a_page_at_a_time(self, admin_client, stock):
        answer = get(
            admin_client, level=1, parent=stock["acme"].pk, offset=1, limit=1
        )

        assert names(answer) == ["Screen"]
        assert answer["total"] == 2

    @pytest.mark.parametrize(
        "params,status",
        [
            ({"level": 3, "parent": 1}, 404),
            ({"level": 1}, 400),
            ({"level": 1, "parent": "nope"}, 404),
            ({"level": 1, "parent": 999999}, 404),
            ({"level": -1}, 400),
            ({"limit": "a"}, 400),
        ],
    )
    def test_what_names_nothing_is_refused(
        self, admin_client, stock, params, status
    ):
        get(admin_client, status=status, **params)

    def test_a_parent_of_another_level_is_not_found(self, admin_client, stock):
        """Level 2's parents are equipment: a supplier's key names one
        only by chance, and Bolt's names none here."""
        Equipment.objects.filter(pk=stock["bolt"].pk).delete()

        get(admin_client, status=404, level=2, parent=stock["bolt"].pk)

    def test_a_list_without_an_outline_has_no_endpoint(self, admin_client):
        get(admin_client, "/api/example/equipment/outline/", status=404)


class TestWhoSeesWhat:
    def test_a_reader_goes_down_as_far_as_they_may_view(
        self, client, django_user_model, stock
    ):
        reader = client_with(
            client, django_user_model, "view_supplier", "view_equipment"
        )
        response = reader.get(SUPPLIERS)
        outline = response.context["table_config"]["options"]["outline"]

        assert [level["name"] for level in outline["levels"]] == [
            "",
            "equipment",
        ]
        # The last level shown holds nothing, as far as they know.
        answer = get(reader, level=1, parent=stock["acme"].pk)
        assert {item["children"] for item in answer["items"]} == {0}
        get(reader, status=404, level=2, parent=stock["laptop"].pk)

    def test_nothing_to_unfold_is_no_outline(
        self, client, django_user_model, stock
    ):
        reader = client_with(client, django_user_model, "view_supplier")
        response = reader.get(SUPPLIERS)

        assert "outline" not in response.context["table_config"]["options"]
        get(reader, status=404)

    def test_the_cells_are_the_ones_this_reader_may_write(
        self, client, django_user_model, admin_client, stock
    ):
        reader = client_with(
            client,
            django_user_model,
            "view_supplier",
            "view_equipment",
            "change_equipment",
        )
        mine = reader.get(SUPPLIERS).context["table_config"]["options"]
        theirs = admin_client.get(SUPPLIERS).context["table_config"]["options"]
        top, equipment = mine["outline"]["levels"]

        assert "editable" not in top
        assert set(equipment["editable"]) == {
            "name",
            "serial_number",
            "kind",
            "state",
            "assigned_to",
            "purchased_on",
        }
        assert (
            equipment["editableUrl"] == "/api/example/equipment/{_pk}/cells/"
        )
        # An administrator writes the suppliers too.
        assert "name" in theirs["outline"]["levels"][0]["editable"]


class TestTheConfiguration:
    def config(self, client) -> dict:
        response = client.get(SUPPLIERS)

        return response.context["table_config"]["options"]["outline"]

    def test_each_level_brings_its_own_columns(self, admin_client):
        top, equipment, visits = self.config(admin_client)["levels"]

        assert [column["data"] for column in top["columns"]] == [
            "name",
            "email",
            "phone",
            "website",
            "country",
            "is_preferred",
        ]
        # The column pointing back at the supplier says nothing here.
        assert "supplier" not in [
            column["data"] for column in equipment["columns"]
        ]
        assert visits["columns"][0]["data"] == "description"
        assert equipment["title"] == "Equipment"

    def test_a_level_names_its_columns(self, admin_client):
        outline = admin_client.get("/example/customer/").context[
            "table_config"
        ]["options"]["outline"]
        top, tickets, entries = outline["levels"]

        assert outline["title"] == "Tickets and time"
        assert [column["data"] for column in top["columns"]] == [
            "name",
            "segment",
            "account_manager",
            "ticket_count",
        ]
        assert [column["data"] for column in tickets["columns"]] == [
            "reference",
            "title",
            "assignee",
            "priority",
            "due_on",
        ]
        # Only what the ticket resource lets be written.
        assert set(tickets["editable"]) == {"assignee", "priority", "due_on"}

    def test_a_level_reached_by_a_foreign_key_adds_its_records(
        self, admin_client
    ):
        top, equipment, visits = self.config(admin_client)["levels"]

        assert top["addUrl"] == ""
        assert equipment["addUrl"].startswith(
            "/example/equipment/add/?supplier={parent}&"
        )
        assert visits["addUrl"].startswith(
            "/example/maintenance/add/?equipment={parent}&"
        )

    def test_nothing_is_edited_when_the_outline_says_so(
        self, redeclare, rf, admin_user
    ):
        resource = redeclare(
            Outline("equipment", Level("maintenances", editable=False))
        )
        request = rf.get("/")
        request.user = admin_user
        levels = resource.get_outline_config(request)["levels"]

        assert [("editable" in level) for level in levels] == [
            True,
            True,
            False,
        ]

        resource = redeclare(Outline("equipment", editable=False))
        levels = resource.get_outline_config(request)["levels"]

        assert not any("editable" in level for level in levels)


class TestManyToMany:
    def test_a_many_to_many_unfolds_either_way(
        self, other_site, rf, admin_user
    ):
        jane = Author.objects.create(name="Jane", email="jane@test")
        Author.objects.create(name="Paul", email="paul@test")
        other_site.auto(Author, outline=("documents",))
        other_site.auto(Document, outline=("authors",))
        other_site.complete_auto()

        for title in ("A", "B"):
            document = Document.objects.create(title=title, file="x.txt")
            document.authors.add(jane)

        request = rf.get("/")
        request.user = admin_user
        authors = other_site.get_resource(Author)
        bound = authors.get_outline()
        top = bound.answer(
            request,
            {},
            Author.objects.order_by("name"),
            {"request": request},
        )

        assert [item["children"] for item in top["items"]] == [2, 0]

        below = bound.answer(
            request, {"level": 1, "parent": jane.pk}, None, {}
        )

        assert sorted(item["row"]["title"] for item in below["items"]) == [
            "A",
            "B",
        ]
        assert (
            other_site.get_resource(Document).get_outline().levels[1].back
            == "documents"
        )

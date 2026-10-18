"""The chart its reader draws above the list (generic.sites.chart_builder):
the fields it offers, the chart it answers, what it refuses."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils import translation

from example.models import Equipment, Ticket
from generic.sites import (
    AutoResource,
    ChartBuilder,
    ModelResource,
    chart_builder,
    site,
)
from generic.sites.site import GenericSite
from tests.sites.test_resource_api import user_with

pytestmark = pytest.mark.django_db

EQUIPMENT = "/api/example/equipment/chart-builder/"
TICKETS = "/api/example/ticket/chart-builder/"


def described(model) -> dict:
    return site.get_resource(model).get_chart_builder().describe()


def offered(entries) -> list:
    return [entry["value"] for entry in entries]


def as_dict(body: dict, series: int = 0) -> dict:
    return dict(zip(body["categories"], body["series"][series]["data"]))


def bound(model, **attributes):
    """A resource of ``model`` on a site of its own, declared here."""
    resource = type("Resource", (ModelResource,), attributes)

    return resource(model, GenericSite(name="chart-builder-test"))


class TestWhatIsOffered:
    def test_auto_offers_it_with_the_fields_worked_out(self):
        builder = described(Equipment)

        # The list's columns first, then the rest of the model: what
        # sorts a record - a choice, a relation, a date - never what
        # names it (name, serial number) nor long text (notes).
        assert offered(builder["dimensions"]) == [
            "kind",
            "state",
            "supplier",
            "assigned_to",
            "purchased_on",
        ]
        assert offered(builder["values"]) == [
            "count",
            "sum:price",
            "avg:price",
        ]
        assert builder["defaults"]["group_by"] == "kind"
        assert builder["defaults"]["type"] == "bar"

    def test_a_model_resource_has_none_unless_asked(self):
        resource = bound(Equipment)

        assert resource.get_chart_builder() is None

    def test_auto_can_be_told_no(self):
        resource = type("Resource", (AutoResource,), {"chart_builder": False})(
            Equipment, GenericSite(name="chart-builder-test")
        )

        assert resource.get_chart_builder() is None

    def test_field_paths_name_what_it_groups_by(self):
        resource = bound(Ticket, chart_builder=("status", "team"))
        builder = resource.get_chart_builder().describe()

        assert offered(builder["dimensions"]) == ["status", "team"]
        # The numbers are still worked out.
        assert "sum:estimated_hours" in offered(builder["values"])

    def test_a_declaration_says_everything(self):
        resource = bound(
            Ticket,
            chart_builder=ChartBuilder(
                group_by=("priority",),
                values=(),
                types=("donut", "bar"),
            ),
        )
        builder = resource.get_chart_builder().describe()

        assert offered(builder["dimensions"]) == ["priority"]
        assert offered(builder["values"]) == ["count"]
        assert offered(builder["types"]) == ["donut", "bar"]
        assert builder["defaults"]["type"] == "donut"

    def test_an_excluded_field_is_never_offered(self):
        resource = type(
            "Resource",
            (AutoResource,),
            {"exclude": ("supplier", "price")},
        )(Equipment, GenericSite(name="chart-builder-test"))
        builder = resource.get_chart_builder()

        assert "supplier" not in builder.dimensions
        assert "sum:price" not in builder.measures

    def test_a_field_named_like_a_secret_is_never_offered(self):
        # Grouped, a secret is told: auto's rule for columns.
        field = models.CharField(choices=[("a", "A")])
        field.set_attributes_from_name("api_token")
        resource = site.get_resource(Equipment)

        assert not chart_builder.offered(resource, field, "api_token")

    @pytest.mark.parametrize(
        "declaration, message",
        [
            (("nope",), "not a field path"),
            (("title",), "a chart groups by"),
            (ChartBuilder(group_by=("status",), values=("title",)), "number"),
        ],
    )
    def test_a_wrong_declaration_is_refused_at_registration(
        self, declaration, message
    ):
        resource = type(
            "Resource", (ModelResource,), {"chart_builder": declaration}
        )

        with pytest.raises(ImproperlyConfigured, match=message):
            GenericSite(name="chart-builder-test").register(Ticket, resource)

    def test_an_unknown_type_is_refused(self):
        with pytest.raises(ImproperlyConfigured, match="unknown type"):
            ChartBuilder(types=("radar",))

    def test_labels_are_in_the_readers_language(self):
        with translation.override("fr"):
            builder = described(Equipment)

        values = {
            entry["value"]: entry["label"] for entry in builder["values"]
        }

        assert values["count"].startswith("Nombre de ")
        assert values["sum:price"] == "Prix (total)"


class TestTheChart:
    def test_it_counts_by_the_chosen_field(self, admin_client, workshop):
        body = admin_client.get(EQUIPMENT, {"group_by": "kind"}).json()

        assert body["type"] == "bar"
        assert as_dict(body) == {"Laptop": 1, "Headset": 1}
        assert body["dimension"] == {"name": "kind", "kind": "choice"}
        assert body["title"] == "Number of equipment by kind"

    def test_a_sum_split_by_a_second_field(self, admin_client, workshop):
        body = admin_client.get(
            EQUIPMENT,
            {
                "group_by": "state",
                "split_by": "kind",
                "value": "sum:price",
                "stacked": "1",
            },
        ).json()

        assert body["stacked"] is True
        assert body["split"] == {"name": "kind", "kind": "choice"}
        assert body["value"]["label"] == "Price (total)"
        assert {entry["name"]: entry["data"] for entry in body["series"]} == {
            "Laptop": [1200, 0],
            "Headset": [0, 0],
        }

    def test_an_average_reads_as_a_decimal(self, admin_client, workshop):
        body = admin_client.get(
            EQUIPMENT, {"group_by": "supplier", "value": "avg:price"}
        ).json()

        assert as_dict(body) == {"Nordic Devices": 600.0}
        assert body["value"]["format"] == "decimal"

    def test_dates_by_the_chosen_period(self, admin_client, workshop):
        Equipment.objects.filter(pk=workshop["laptop"].pk).update(
            purchased_on="2026-01-15"
        )
        Equipment.objects.filter(pk=workshop["headset"].pk).update(
            purchased_on="2026-05-02"
        )

        body = admin_client.get(
            EQUIPMENT, {"group_by": "purchased_on", "period": "quarter"}
        ).json()

        assert body["categories"] == ["Q1 2026", "Q2 2026"]
        assert body["dimension"]["period"] == "quarter"

    def test_a_pie_draws_one_series(self, admin_client, workshop):
        body = admin_client.get(
            EQUIPMENT,
            {"type": "pie", "group_by": "kind", "split_by": "state"},
        ).json()

        assert body["type"] == "pie"
        assert body["split"] is None

    def test_it_follows_the_tables_filters(self, admin_client, workshop):
        body = admin_client.get(
            EQUIPMENT,
            {
                "group_by": "kind",
                "filters": (
                    '{"match": "all", "conditions": [{"column": "state", '
                    '"operator": "any_of", "value": ["in_use"]}]}'
                ),
            },
        ).json()

        assert as_dict(body) == {"Laptop": 1}

    def test_it_counts_only_the_rows_the_reader_may_see(
        self, client, support_desk
    ):
        # A ticket list narrowed by the resource: the chart counts what
        # get_queryset gives, as the table does.
        client.force_login(user_with("view_ticket"))
        body = client.get(TICKETS, {"group_by": "status"}).json()

        assert sum(body["series"][0]["data"]) == Ticket.objects.count()


class TestRefusals:
    @pytest.mark.parametrize(
        "params, field",
        [
            ({}, "group_by"),
            ({"group_by": "name"}, "group_by"),
            ({"group_by": "kind", "type": "radar"}, "type"),
            ({"group_by": "kind", "split_by": "kind"}, "split_by"),
            ({"group_by": "kind", "split_by": "notes"}, "split_by"),
            ({"group_by": "kind", "type": "heatmap"}, "split_by"),
            ({"group_by": "kind", "value": "sum:name"}, "value"),
            ({"group_by": "kind", "value": "sum:supplier__id"}, "value"),
            ({"group_by": "purchased_on", "period": "decade"}, "period"),
        ],
    )
    def test_only_what_is_offered_is_accepted(
        self, admin_client, workshop, params, field
    ):
        response = admin_client.get(EQUIPMENT, params)

        assert response.status_code == 400
        assert field in response.json()

    def test_a_resource_without_it_has_no_endpoint(self, admin_client):
        response = admin_client.get(
            "/api/example/timeentry/chart-builder/", {"group_by": "agent"}
        )

        assert response.status_code == 404

    def test_a_reader_who_may_not_view_is_refused(self, client, workshop):
        client.force_login(user_with("view_ticket"))

        response = client.get(EQUIPMENT, {"group_by": "kind"})

        assert response.status_code == 403


class TestTheListPage:
    def test_the_panel_is_given_to_the_list(self, admin_client, workshop):
        response = admin_client.get("/example/equipment/")
        config = response.context["chart_builder"]["config"]

        assert config["url"] == EQUIPMENT
        assert config["table"] == "#datatable"
        assert config["builder"]["storageKey"].startswith(
            "generic.chart-builder."
        )
        assert b"data-chart-builder-table" in response.content
        assert b"genericChartBuilder" in response.content

    def test_no_panel_without_a_builder(self, admin_client):
        response = admin_client.get("/example/timeentry/")

        assert response.context["chart_builder"] is None
        assert b"genericChartBuilder" not in response.content

    def test_its_numbers_are_the_table_numbers(self, admin_client, workshop):
        # The figures: what the table shows when filtered on the bar.
        workshop["headset"].price = Decimal("80.00")
        workshop["headset"].save()

        body = admin_client.get(
            EQUIPMENT, {"group_by": "kind", "value": "sum:price"}
        ).json()

        assert as_dict(body) == {"Laptop": 1200, "Headset": 80}

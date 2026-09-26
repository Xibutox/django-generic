"""Charts: declared on a resource, computed by the database, served
with the table's filters and permissions."""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Sum
from django.template import Context, Template
from django.test import RequestFactory

from example.models import Customer, Ticket, TimeEntry
from generic.sites import Chart, chart_payload, site
from generic.sites.related import RELATED_PARAM
from tests.sites.test_resource_api import user_with

pytestmark = pytest.mark.django_db

CHARTS = "/api/example/ticket/charts/"
HOURS = "/api/example/timeentry/charts/"


def at(day: int, hour: int = 10) -> datetime.datetime:
    return datetime.datetime(2026, 3, day, hour, tzinfo=datetime.timezone.utc)


@pytest.fixture
def logged(support_desk) -> dict:
    """Time on the three tickets: Yanis 6 hours, Camille 1.5."""
    for ticket, agent, hours, billable in (
        ("login", "camille", "1.50", True),
        ("invoice", "yanis", "2.00", False),
        ("export", "yanis", "4.00", True),
    ):
        TimeEntry.objects.create(
            ticket=support_desk[ticket],
            agent=support_desk[agent],
            hours=Decimal(hours),
            is_billable=billable,
            spent_on=datetime.date(2026, 3, 10),
        )

    return support_desk


def as_dict(body: dict, series: int = 0) -> dict:
    return dict(zip(body["categories"], body["series"][series]["data"]))


class TestDeclarativeCharts:
    def test_a_choice_keeps_its_order_and_its_colours(
        self,
        admin_client,
        support_desk,
    ):
        body = admin_client.get(f"{CHARTS}by_status/").json()

        assert body["type"] == "donut"
        assert body["categories"] == ["Open", "Pending", "Closed"]
        assert body["keys"] == ["open", "pending", "closed"]
        assert body["series"][0]["data"] == [1, 1, 1]
        # From the resource's tag_fields: declared once, used twice.
        assert body["colors"] == ["#2563eb", "#d97706", "#64748b"]
        assert body["value"] == {
            "label": "Tickets",
            "format": "integer",
            "unit": "",
            "decimals": 0,
        }
        assert body["dimension"] == {"name": "status", "kind": "choice"}
        assert body["total"] == 3
        assert body["empty"] is False

    def test_a_many_to_many_counts_each_record_once_per_value(
        self,
        admin_client,
        support_desk,
    ):
        body = admin_client.get(f"{CHARTS}by_tag/").json()

        assert as_dict(body) == {
            "regression": 1,
            "release": 1,
            "billing": 1,
            "None": 1,
        }
        # The ticket without a tag comes last.
        assert body["keys"][-1] is None

    def test_a_second_dimension_makes_series(
        self,
        admin_client,
        support_desk,
    ):
        body = admin_client.get(f"{CHARTS}by_team/").json()

        assert body["categories"] == ["Front office", "Infrastructure"]
        assert [series["name"] for series in body["series"]] == [
            "Low",
            "Normal",
            "High",
        ]
        assert [series["data"] for series in body["series"]] == [
            [1, 0],
            [0, 1],
            [1, 0],
        ]
        assert body["series"][0]["key"] == "low"
        assert body["split"] == {"name": "priority", "kind": "choice"}

    def test_dates_are_bucketed_and_the_gaps_filled(
        self,
        admin_client,
        support_desk,
    ):
        for reference, opened in (
            ("SD-1", at(2)),
            ("SD-3", at(3)),
            ("SD-2", at(18)),
        ):
            Ticket.objects.filter(reference=reference).update(opened_at=opened)

        body = admin_client.get(f"{CHARTS}opened/", {"period": "week"}).json()
        totals = [
            sum(values)
            for values in zip(*(series["data"] for series in body["series"]))
        ]

        assert body["keys"] == ["2026-03-02", "2026-03-09", "2026-03-16"]
        assert totals == [2, 0, 1]
        assert body["ranges"][0] == {"from": "2026-03-02", "to": "2026-03-08"}
        assert body["dimension"]["period"] == "week"

    def test_the_period_can_be_switched(self, admin_client, support_desk):
        Ticket.objects.update(opened_at=at(12))

        body = admin_client.get(f"{CHARTS}opened/", {"period": "month"}).json()

        assert body["keys"] == ["2026-03-01"]
        assert body["categories"] == ["March 2026"]

    def test_only_an_offered_period_is_accepted(
        self,
        admin_client,
        support_desk,
    ):
        response = admin_client.get(f"{CHARTS}opened/", {"period": "year"})

        assert response.status_code == 400

    def test_a_sum_reads_as_decimal_hours(self, admin_client, logged):
        body = admin_client.get(f"{HOURS}hours_by_agent/").json()

        assert body["categories"] == ["Yanis Bertrand", "Camille Rousseau"]
        assert body["series"][0]["data"] == [6, 1.5]
        assert body["value"] == {
            "label": "Hours",
            "format": "decimal",
            "unit": "h",
            "decimals": 1,
        }

    def test_a_boolean_series_says_what_it_is(self, admin_client, logged):
        body = admin_client.get(f"{HOURS}hours_by_month/").json()

        assert [series["name"] for series in body["series"]] == [
            "Billable: Yes",
            "Billable: No",
        ]
        assert [series["data"] for series in body["series"]] == [[5.5], [2]]

    def test_a_limit_gathers_the_rest(self, logged):
        chart = Chart(
            "top",
            group_by="agent",
            value=Sum("hours"),
            limit=1,
        )
        resource = site.get_resource(TimeEntry)
        body = chart.get_payload(resource, None, TimeEntry.objects.all())

        assert body["categories"] == ["Yanis Bertrand", "Other"]
        assert body["series"][0]["data"] == [6, 1.5]
        assert body["keys"][-1] == "__other__"


class TestComputedCharts:
    def test_a_data_callable_computes_anything(self, admin_client, logged):
        body = admin_client.get(f"{CHARTS}effort/").json()

        assert body["categories"] == ["Front office", "Infrastructure"]
        assert body["series"][0] == {
            "name": "Estimated",
            "data": [2.0, 0.0],
        }
        assert body["series"][1]["type"] == "line"
        assert body["series"][1]["data"] == [5.5, 2.0]
        assert body["value"]["unit"] == "h"

    def test_the_callable_gets_the_filtered_records(
        self,
        admin_client,
        logged,
    ):
        body = admin_client.get(
            f"{CHARTS}effort/",
            {"search[value]": "invoice"},
        ).json()

        # SD-2 and SD-3 match; SD-1's hours are left out.
        assert body["categories"] == ["Front office", "Infrastructure"]
        assert body["series"][1]["data"] == [4.0, 2.0]

    def test_a_payload_for_any_view(self):
        body = chart_payload(
            categories=["Mon", "Tue"],
            series=[{"name": "Hours", "data": [Decimal("7.50"), None]}],
        )

        assert body["series"][0]["data"] == [7.5, 0]
        assert body["empty"] is False
        assert chart_payload(categories=[], series=[])["empty"] is True


class TestFiltersAndAccess:
    def test_the_table_filters_apply(self, admin_client, support_desk):
        body = admin_client.get(
            f"{CHARTS}by_status/",
            {
                "advanced_filters": json.dumps(
                    {
                        "team": {
                            "operator": "include",
                            "value": [support_desk["front"].pk],
                        }
                    }
                )
            },
        ).json()

        assert body["categories"] == ["Open", "Closed"]

    def test_a_related_chart_is_narrowed_to_the_record(
        self,
        admin_client,
        support_desk,
    ):
        front = support_desk["front"]
        body = admin_client.get(
            f"{CHARTS}by_status/",
            {RELATED_PARAM: f"example.team.tickets:{front.pk}"},
        ).json()

        assert body["total"] == 2

    def test_nothing_to_show_is_said(self, admin_client, support_desk):
        body = admin_client.get(
            f"{CHARTS}by_status/",
            {"search[value]": "nothing matches this"},
        ).json()

        assert body["empty"] is True
        assert body["categories"] == []

    def test_the_view_permission_is_needed(self, client, support_desk):
        client.force_login(user_with("view_team"))

        assert client.get(f"{CHARTS}by_status/").status_code == 403

    def test_an_unknown_chart_is_not_found(self, admin_client, db):
        assert admin_client.get(f"{CHARTS}nothing/").status_code == 404

    def test_a_chart_may_ask_for_more(self, client, support_desk):
        resource = site.get_resource(Ticket)
        chart = Chart(
            "secret",
            group_by="status",
            permission="example.delete_ticket",
        )
        request = RequestFactory().get("/")
        request.user = user_with("view_ticket")

        assert chart.is_visible(request, resource) is False


class TestPages:
    def test_the_list_draws_its_charts_over_the_table(
        self,
        admin_client,
        support_desk,
    ):
        charts = admin_client.get("/example/ticket/").context["charts"]
        configs = {
            entry["config"]["name"]: entry["config"] for entry in charts
        }

        assert list(configs) == ["by_status", "opened"]
        assert configs["by_status"]["url"] == f"{CHARTS}by_status/"
        assert configs["by_status"]["table"] == "#datatable"
        # A switch only where there are dates to bucket.
        assert configs["by_status"]["periods"] == []
        assert [
            period["value"] for period in configs["opened"]["periods"]
        ] == [
            "day",
            "week",
            "month",
            "quarter",
        ]

    def test_a_summary_page_narrows_its_charts(self, admin_client, logged):
        customer = Customer.objects.create(name="Northwind", code="NWT")
        response = admin_client.get(f"/example/customer/{customer.pk}/")
        detail = [entry["config"] for entry in response.context["charts"]]
        tickets = next(
            table
            for table in response.context["related_tables"]
            if table["name"] == "tickets"
        )

        assert [config["name"] for config in detail] == [
            "hours_by_month",
            "opened",
        ]
        assert detail[0]["extraParams"] == {
            RELATED_PARAM: f"example.customer.time_spent:{customer.pk}"
        }
        assert [entry["config"]["table"] for entry in tickets["charts"]] == [
            'table[data-related="tickets"]',
            'table[data-related="tickets"]',
        ]

    def test_the_template_tag_draws_a_chart(self, admin_user, support_desk):
        request = RequestFactory().get("/")
        request.user = admin_user
        html = Template(
            '{% load generic_ui %}{% generic_chart "example.ticket" '
            '"opened" height="12rem" %}'
        ).render(Context({"request": request}))

        assert "genericChart(" in html
        assert "12rem" in html

    def test_the_template_tag_draws_nothing_for_whom_may_not_see(
        self,
        support_desk,
    ):
        request = RequestFactory().get("/")
        request.user = user_with("view_team")
        html = Template(
            '{% load generic_ui %}{% generic_chart "example.ticket" "opened" %}'
        ).render(Context({"request": request}))

        assert "genericChart" not in html

    def test_the_template_tag_refuses_what_it_does_not_know(
        self,
        admin_user,
        support_desk,
    ):
        request = RequestFactory().get("/")
        request.user = admin_user

        with pytest.raises(ImproperlyConfigured):
            Template(
                '{% load generic_ui %}{% generic_chart "example.ticket" '
                '"opened" colour="red" %}'
            ).render(Context({"request": request}))


class TestDeclaration:
    @pytest.mark.parametrize(
        "options",
        [
            {},
            {"group_by": "status", "type": "radar"},
            {"group_by": "opened_at", "periods": ("fortnight",)},
            {"group_by": "status", "value_format": "money"},
        ],
    )
    def test_a_wrong_declaration_is_refused(self, options):
        with pytest.raises(ImproperlyConfigured):
            Chart("wrong", **options)

    def test_a_path_that_does_not_exist_is_refused(self, support_desk):
        resource = site.get_resource(Ticket)

        with pytest.raises(ImproperlyConfigured):
            Chart("wrong", group_by="nothing").get_payload(
                resource, None, Ticket.objects.all()
            )

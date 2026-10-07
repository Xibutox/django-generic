"""Key figures and record cards on the dashboard.

The example declares them on tickets (open, urgent, overdue,
satisfaction; the pressing tickets as cards) and on time entries (hours
this month). The browser names a resource and a declaration; the
filters, the aggregate and the order are the declaration's.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Sum
from django.utils import timezone

from example.models import Ticket, TimeEntry
from generic.sites import Cards, Kpi, ModelResource, site
from generic.sites.dashboard import check_declarations

pytestmark = pytest.mark.django_db

KPI = "/api/example/ticket/kpis/{}/"
CARDS = "/api/example/ticket/cards/{}/"


def get(client, url: str) -> dict:
    response = client.get(url)

    assert response.status_code == 200, response.content

    return response.json()


@pytest.fixture
def ticket_reader(client, django_user_model):
    """Reads tickets, nothing else."""
    user = django_user_model.objects.create_user(username="reader")
    user.user_permissions.set(
        Permission.objects.filter(codename="view_ticket")
    )
    client.force_login(user)

    return client


class TestKeyFigures:
    def test_a_count_follows_the_declared_filters(
        self, admin_client, support_desk
    ):
        answer = get(admin_client, KPI.format("open"))

        # SD-1 open, SD-2 pending; SD-3 is closed.
        assert answer["value"] == 2
        assert answer["display"] == "2"
        assert answer["level"] == "good"

    def test_the_tile_opens_the_list_with_the_same_filters(
        self, admin_client, support_desk
    ):
        answer = get(admin_client, KPI.format("open"))
        url = urlparse(answer["url"])
        tree = json.loads(parse_qs(url.query)["filters"][0])

        assert url.path == "/example/ticket/"
        assert tree["conditions"][0]["column"] == "status"

        rows = admin_client.get(
            "/api/example/ticket/",
            {"format": "datatables", "filters": json.dumps(tree)},
        ).json()

        assert rows["recordsFiltered"] == answer["value"]

    def test_thresholds_colour_the_figure(self, admin_client, support_desk):
        Ticket.objects.filter(pk=support_desk["login"].pk).update(
            priority=Ticket.Priority.URGENT
        )

        assert get(admin_client, KPI.format("urgent"))["level"] == "warning"

        for number in range(4):
            Ticket.objects.create(
                reference=f"U-{number}",
                title="Urgent",
                team=support_desk["front"],
                priority=Ticket.Priority.URGENT,
            )

        assert get(admin_client, KPI.format("urgent"))["level"] == "danger"

    def test_lower_is_worse_when_danger_is_below_warning(
        self, admin_client, support_desk
    ):
        Ticket.objects.filter(pk=support_desk["export"].pk).update(
            satisfaction=2.5
        )
        answer = get(admin_client, KPI.format("satisfaction"))

        assert answer["display"] == "2.5"
        assert answer["unit"] == "/ 5"
        assert answer["level"] == "danger"

        Ticket.objects.filter(pk=support_desk["export"].pk).update(
            satisfaction=4.5
        )

        assert get(admin_client, KPI.format("satisfaction"))["level"] == (
            "good"
        )

    def test_an_aggregate_over_nothing_is_no_figure(self, admin_client, db):
        answer = get(admin_client, KPI.format("satisfaction"))

        assert answer["value"] is None
        assert answer["level"] == ""

    def test_relative_dates_stay_true(self, admin_client, support_desk):
        today = timezone.localdate()
        Ticket.objects.filter(pk=support_desk["login"].pk).update(
            due_on=today - datetime.timedelta(days=5)
        )
        Ticket.objects.filter(pk=support_desk["invoice"].pk).update(
            due_on=today
        )

        assert get(admin_client, KPI.format("overdue"))["value"] == 1

    def test_a_sum_of_this_month(self, admin_client, support_desk):
        today = timezone.localdate()
        ticket = support_desk["login"]
        TimeEntry.objects.create(
            ticket=ticket,
            agent=support_desk["camille"],
            spent_on=today,
            hours=Decimal("1.5"),
        )
        TimeEntry.objects.create(
            ticket=ticket,
            agent=support_desk["camille"],
            spent_on=today.replace(day=1) - datetime.timedelta(days=1),
            hours=Decimal("4"),
        )
        answer = get(
            admin_client, "/api/example/timeentry/kpis/hours-this-month/"
        )

        assert answer["value"] == 1.5
        assert answer["unit"] == "h"

    def test_the_reader_s_rows_only(self, admin_client, support_desk):
        from example.resources import TicketResource

        resource = site.get_resource(Ticket)
        original = type(resource).get_queryset

        def front_only(self, request):
            return original(self, request).filter(team__code="FO")

        TicketResource.get_queryset = front_only

        try:
            # SD-1 is the front office's; SD-2 is not.
            assert get(admin_client, KPI.format("open"))["value"] == 1
        finally:
            TicketResource.get_queryset = original

    def test_refused_without_the_view_permission(
        self, client, django_user_model, support_desk
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))

        assert client.get(KPI.format("open")).status_code == 403

    def test_an_unknown_figure_is_not_found(self, admin_client, db):
        assert admin_client.get(KPI.format("nope")).status_code == 404

    def test_a_figure_s_own_permission(
        self, ticket_reader, support_desk, monkeypatch
    ):
        resource = site.get_resource(Ticket)
        guarded = Kpi("open", permission="example.change_ticket")
        monkeypatch.setitem(resource.__dict__, "_checked_kpis", [guarded])

        assert ticket_reader.get(KPI.format("open")).status_code == 404


class TestCards:
    def test_the_declared_records_in_the_declared_order(
        self, admin_client, support_desk
    ):
        today = timezone.localdate()
        Ticket.objects.filter(pk=support_desk["login"].pk).update(
            due_on=today + datetime.timedelta(days=3)
        )
        Ticket.objects.create(
            reference="SD-9",
            title="Server down",
            team=support_desk["infra"],
            priority=Ticket.Priority.URGENT,
            due_on=today,
        )
        Ticket.objects.create(
            reference="SD-8",
            title="No date yet",
            team=support_desk["infra"],
            priority=Ticket.Priority.URGENT,
        )
        answer = get(admin_client, CARDS.format("pressing"))
        labels = [item["label"] for item in answer["items"]]

        # Urgent or high, still open, soonest due first, undated last
        # (whatever the database's habit); SD-2 is normal.
        assert labels == [
            "SD-9 - Server down",
            "SD-1 - Login fails after password reset",
            "SD-8 - No date yet",
        ]
        assert answer["total"] == 3
        assert answer["url"].startswith("/example/ticket/?filters=")

    def test_each_card_carries_typed_values(self, admin_client, support_desk):
        answer = get(admin_client, CARDS.format("pressing"))
        card = answer["items"][0]

        assert card["url"] == f"/example/ticket/{support_desk['login'].pk}/"
        assert card["subtitle"]["type"] == "link"
        assert [cell["label"] for cell in card["cells"]] == [
            "Priority",
            "Status",
            "Assignee",
            "Due on",
        ]
        assert card["cells"][0]["type"] == "tags"
        assert card["cells"][2]["display"] == "Camille Rousseau"

    def test_the_total_counts_past_the_limit(
        self, admin_client, support_desk, monkeypatch
    ):
        resource = site.get_resource(Ticket)
        two = Cards("pressing", limit=1)
        monkeypatch.setitem(resource.__dict__, "_checked_cards", [two])

        answer = get(admin_client, CARDS.format("pressing"))

        assert len(answer["items"]) == 1
        assert answer["total"] == 3

    def test_refused_without_the_view_permission(
        self, client, django_user_model, support_desk
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))

        assert client.get(CARDS.format("pressing")).status_code == 403


class TestTheDashboard:
    def test_shows_what_the_reader_may_see(self, ticket_reader, db):
        response = ticket_reader.get("/")
        keys = [kpi["key"] for kpi in response.context["dashboard_kpis"]]

        assert keys == [
            "example.ticket.open",
            "example.ticket.urgent",
            "example.ticket.overdue",
            "example.ticket.satisfaction",
        ]
        assert [
            cards["key"] for cards in response.context["dashboard_cards"]
        ] == ["example.ticket.pressing"]
        assert b'data-kpi-url="/api/example/ticket/kpis/open/"' in (
            response.content
        )
        assert b"generic/js/dashboard.js" in response.content

    def test_the_admin_sees_every_resource_s(self, admin_client, db):
        response = admin_client.get("/")
        keys = [kpi["key"] for kpi in response.context["dashboard_kpis"]]

        assert "example.timeentry.hours-this-month" in keys

    def test_nothing_declared_nothing_loaded(
        self, client, django_user_model, db
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))
        response = client.get("/")

        assert response.context["dashboard_kpis"] == []
        assert b"generic/js/dashboard.js" not in response.content


class TestDeclarations:
    def resource(self, **attributes):
        from example.models import Ticket as Model

        klass = type("Probe", (ModelResource,), attributes)

        return klass(Model, site)

    def check(self, attribute: str, kind: type, *items) -> None:
        check_declarations(
            self.resource(**{attribute: items}), attribute, kind
        )

    def test_a_good_declaration_passes(self):
        self.check("kpis", Kpi, Kpi("a", value=Sum("estimated_hours")))
        self.check(
            "cards", Cards, Cards("b", fields=("status",), ordering=("-pk",))
        )

    @pytest.mark.parametrize(
        "item, message",
        [
            (Kpi("Bad Name"), "lower case"),
            (Kpi("a", value=3), "aggregate"),
            (Kpi("a", warning="many"), "numbers"),
            (Kpi("a", filters=["status"]), "filter tree"),
        ],
    )
    def test_key_figures_refuse_mistakes(self, item, message):
        with pytest.raises(ImproperlyConfigured, match=message):
            self.check("kpis", Kpi, item)

    @pytest.mark.parametrize(
        "item, message",
        [
            (Cards("a", limit=0), "between 1 and"),
            (Cards("a", fields="status"), "tuples"),
            (Cards("a", fields=("nope",)), "'nope'"),
            (Cards("a", ordering=("-nope",)), "ordered by"),
            (Cards("a", image="title"), "not a file field"),
        ],
    )
    def test_cards_refuse_mistakes(self, item, message):
        with pytest.raises(ImproperlyConfigured, match=message):
            self.check("cards", Cards, item)

    def test_the_same_name_twice(self):
        with pytest.raises(ImproperlyConfigured, match="same name"):
            self.check("kpis", Kpi, Kpi("a"), Kpi("a"))

    def test_not_a_declaration(self):
        with pytest.raises(ImproperlyConfigured, match="not a Kpi"):
            self.check("kpis", Kpi, "open")

    def test_filters_the_list_refuses_are_said_at_first_use(
        self, admin_client, monkeypatch
    ):
        resource = site.get_resource(Ticket)
        wrong = Kpi(
            "open",
            filters={
                "match": "all",
                "conditions": [
                    {"column": "secret", "operator": "contains", "value": "x"}
                ],
            },
        )
        monkeypatch.setitem(resource.__dict__, "_checked_kpis", [wrong])

        with pytest.raises(ImproperlyConfigured, match="refused by the list"):
            admin_client.get(KPI.format("open"))

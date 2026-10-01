"""Summary pages: a record, its figures, and its related tables."""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured

from example.models import Customer, Tag, Team, Ticket, TimeEntry
from generic.sites import RelatedTable, site
from generic.sites.related import RELATED_PARAM, bind_related_table
from tests.sites.test_resource_api import user_with

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/"


def references(response) -> list[str]:
    return sorted(row["reference"] for row in response.json()["data"])


@pytest.fixture
def customer(support_desk) -> Customer:
    """A customer owning two of the three tickets, with logged time."""
    customer = Customer.objects.create(name="Northwind", code="NWT")
    Ticket.objects.filter(reference__in=["SD-1", "SD-2"]).update(
        customer=customer
    )

    for ticket, agent, spent in (
        ("login", "camille", "1.50"),
        ("invoice", "yanis", "2.00"),
        ("export", "yanis", "4.00"),
    ):
        TimeEntry.objects.create(
            ticket=support_desk[ticket],
            agent=support_desk[agent],
            hours=Decimal(spent),
        )

    return customer


class TestBinding:
    def test_a_reverse_foreign_key_filters_on_its_key(self):
        bound = bind_related_table(
            RelatedTable("tickets"),
            site.get_resource(Team),
        )

        assert bound.model is Ticket
        assert bound.lookup == "team"
        assert bound.prefill == "team"

    def test_a_many_to_many_seen_from_the_other_side(self):
        bound = bind_related_table(
            RelatedTable("tickets"),
            site.get_resource(Tag),
        )

        assert (bound.lookup, bound.prefill) == ("tags", "tags")

    def test_a_many_to_many_declared_here_reaches_back(self):
        bound = bind_related_table(
            RelatedTable("tags"),
            site.get_resource(Ticket),
        )

        assert bound.model is Tag
        assert bound.lookup == "tickets"
        assert bound.prefill is None

    def test_a_path_prefills_only_a_direct_key(self):
        bound = site.get_resource(Customer).get_bound_related_table(
            "time_spent"
        )

        assert bound.lookup == "ticket__customer"
        assert bound.prefill is None

    @pytest.mark.parametrize(
        "definition, model",
        [
            (RelatedTable("nothing"), Team),
            # A single record, not a collection.
            (RelatedTable("team"), Ticket),
            # A model without the path back.
            (RelatedTable("time", model=TimeEntry), Customer),
        ],
    )
    def test_a_wrong_declaration_is_refused(self, definition, model):
        with pytest.raises(ImproperlyConfigured):
            bind_related_table(definition, site.get_resource(model))


class TestRelatedRows:
    @staticmethod
    def get(client, key: str, pk, **params):
        return client.get(
            TICKETS,
            {"draw": 1, "length": 50, RELATED_PARAM: f"{key}:{pk}", **params},
        )

    def test_rows_are_narrowed_to_the_record(self, admin_client, support_desk):
        response = self.get(
            admin_client,
            "example.team.tickets",
            support_desk["front"].pk,
        )

        assert response.status_code == 200
        assert references(response) == ["SD-1", "SD-3"]
        # The total is the record's, not the whole table's.
        assert response.json()["recordsTotal"] == 2

    def test_the_search_applies_within_the_record(
        self,
        admin_client,
        support_desk,
    ):
        response = self.get(
            admin_client,
            "example.team.tickets",
            support_desk["front"].pk,
            **{"search[value]": "invoice"},
        )

        assert references(response) == ["SD-3"]

    def test_a_path_through_another_model(self, admin_client, customer):
        response = admin_client.get(
            "/api/example/timeentry/",
            {
                "draw": 1,
                RELATED_PARAM: f"example.customer.time_spent:{customer.pk}",
            },
        )

        assert response.json()["recordsTotal"] == 2

    @pytest.mark.parametrize(
        "key",
        [
            "example.team.everything",
            # Declared, but it lists agents, not tickets.
            "example.team.agents",
            "not-even-a-key",
        ],
    )
    def test_only_a_declared_table_of_this_model_is_accepted(
        self,
        admin_client,
        support_desk,
        key,
    ):
        response = self.get(admin_client, key, support_desk["front"].pk)

        assert response.status_code == 404

    @pytest.mark.parametrize("pk", [999, "abc"])
    def test_an_unknown_record_is_not_found(self, admin_client, db, pk):
        response = self.get(admin_client, "example.team.tickets", pk)

        assert response.status_code == 404

    def test_the_record_must_be_one_the_user_may_see(
        self,
        client,
        support_desk,
    ):
        # Tickets, yes; teams, no: a team's tickets are out of reach.
        client.force_login(user_with("view_ticket"))
        response = self.get(
            client,
            "example.team.tickets",
            support_desk["front"].pk,
        )

        assert response.status_code == 403

    def test_a_bulk_action_on_all_rows_stays_within_the_record(
        self,
        admin_client,
        support_desk,
    ):
        front = support_desk["front"]
        response = admin_client.post(
            f"{TICKETS}actions/?{RELATED_PARAM}=example.team.tickets:{front.pk}",
            {"action": "transition:close", "all": True},
            content_type="application/json",
        )

        assert response.json()["count"] == 2
        assert Ticket.objects.get(reference="SD-2").status == "pending"

    def test_an_export_stays_within_the_record(
        self,
        admin_client,
        support_desk,
    ):
        response = admin_client.get(
            f"{TICKETS}export-csv/",
            {
                RELATED_PARAM: f"example.team.tickets:{support_desk['front'].pk}"
            },
        )
        content = (
            b"".join(response.streaming_content)
            if response.streaming
            else response.content
        )
        text = io.StringIO(content.decode("utf-8-sig")).read()

        assert "SD-1" in text
        assert "SD-2" not in text


class TestSummary:
    @staticmethod
    def summary(client, url: str) -> dict:
        return client.get(url).json()

    @staticmethod
    def entry(summary: dict, name: str) -> dict:
        for section in summary["sections"]:
            for field in section["fields"]:
                if field["name"] == name:
                    return field

        raise KeyError(name)

    def test_values_come_typed_and_formatted(
        self,
        admin_client,
        support_desk,
    ):
        login = support_desk["login"]
        body = self.summary(admin_client, f"{TICKETS}{login.pk}/summary/")

        # A choice in tag_fields: a tag, coloured by its value.
        assert self.entry(body, "status") == {
            "name": "status",
            "label": "Status",
            "type": "tags",
            "items": [{"label": "Open", "color": "#2563eb", "value": "open"}],
            "more": 0,
            "wide": False,
        }
        assert self.entry(body, "team")["url"] == (
            f"/example/team/{support_desk['front'].pk}/"
        )
        assert [
            (item["label"], item["url"])
            for item in self.entry(body, "tags")["items"]
        ] == [
            ("regression", f"/example/tag/{support_desk['regression'].pk}/"),
            ("release", f"/example/tag/{support_desk['release'].pk}/"),
        ]
        assert self.entry(body, "is_billable")["value"] is True
        assert self.entry(body, "estimated_hours")["display"] == "2.00"
        assert self.entry(body, "description")["empty"] is True
        assert (
            body["object"]["label"]
            == "SD-1 - Login fails after password reset"
        )

    def test_figures_come_from_the_resource(
        self,
        admin_client,
        support_desk,
        customer,
    ):
        login = support_desk["login"]
        body = self.summary(admin_client, f"{TICKETS}{login.pk}/summary/")
        stats = {stat["name"]: stat for stat in body["stats"]}

        assert stats["hours_logged"]["display"] == "1.50"
        assert stats["comment_total"]["display"] == "2"

    def test_related_tables_come_with_a_count_and_an_add(
        self,
        admin_client,
        customer,
    ):
        body = self.summary(
            admin_client,
            f"/api/example/customer/{customer.pk}/summary/",
        )
        related = {entry["name"]: entry for entry in body["related"]}

        assert related["tickets"]["count"] == 2
        assert related["time_spent"]["count"] == 2
        assert related["tickets"]["addUrl"].startswith(
            f"/example/ticket/add/?customer={customer.pk}&_next="
        )
        # Through a path there is nothing to fill in.
        assert related["time_spent"]["addUrl"] == ""

    def test_a_record_may_carry_more_tabs_than_a_bar_can_hold(
        self,
        admin_client,
        customer,
        support_desk,
    ):
        """The customer is the example's crowded page: six tables and
        the history, which is what the tab bar's overflow is for."""
        body = self.summary(
            admin_client,
            f"/api/example/customer/{customer.pk}/summary/",
        )

        assert [entry["name"] for entry in body["related"]] == [
            "tickets",
            "time_spent",
            "conversation",
            "teams",
            "agents",
            "subjects",
        ]
        assert body["history"] is not None

    def test_a_path_through_many_rows_counts_each_one_once(
        self,
        admin_client,
        customer,
        support_desk,
    ):
        """Reached through the tickets, one team would otherwise arrive
        once per ticket it owns."""
        Ticket.objects.filter(customer=customer).update(
            team=support_desk["front"]
        )

        body = self.summary(
            admin_client,
            f"/api/example/customer/{customer.pk}/summary/",
        )
        related = {entry["name"]: entry for entry in body["related"]}

        assert Ticket.objects.filter(customer=customer).count() == 2
        assert related["teams"]["count"] == 1
        # The comments of this customer's tickets, not of every ticket.
        assert related["conversation"]["count"] == 2

    def test_what_the_user_may_not_open_is_left_out(
        self,
        worker_client,
        support_desk,
        customer,
    ):
        login = support_desk["login"]
        body = self.summary(worker_client, f"{TICKETS}{login.pk}/summary/")

        # The customer is named but not linked; time entries are hidden.
        assert self.entry(body, "customer")["display"] == "Northwind"
        assert self.entry(body, "customer")["url"] == ""
        assert [entry["name"] for entry in body["related"]] == ["comments"]

    def test_the_bulk_actions_are_offered_but_not_deleting(
        self,
        admin_client,
        support_desk,
    ):
        login = support_desk["login"]
        body = self.summary(admin_client, f"{TICKETS}{login.pk}/summary/")

        # Transitions are not among them: they have their own buttons,
        # offered from the record's state.
        assert [entry["name"] for entry in body["actions"]] == [
            "check",
            "mark_billable",
        ]
        assert [entry["name"] for entry in body["transitions"]] == [
            "close",
            "resolve",
            "wait",
        ]


class TestSummaryPage:
    def test_the_page_embeds_its_summary_and_tables(
        self,
        admin_client,
        support_desk,
    ):
        front = support_desk["front"]
        response = admin_client.get(f"/example/team/{front.pk}/")
        tickets = next(
            table
            for table in response.context["related_tables"]
            if table["name"] == "tickets"
        )["config"]

        assert response.status_code == 200
        assert b'id="record-summary"' in response.content
        assert tickets["options"]["extraParams"] == {
            RELATED_PARAM: f"example.team.tickets:{front.pk}"
        }
        # The column naming the team would say the same on every row.
        assert "team" not in [column["data"] for column in tickets["columns"]]

    def test_the_summary_needs_the_view_permission(
        self,
        auth_client,
        support_desk,
    ):
        response = auth_client.get(
            f"/example/ticket/{support_desk['login'].pk}/"
        )

        assert response.status_code == 403

    def test_rows_open_on_their_summary(self, admin_client, support_desk):
        options = admin_client.get("/example/ticket/").context["table_config"][
            "options"
        ]

        assert options["rowActions"][0]["name"] == "open"
        assert options["rowActions"][0]["url"] == "/example/ticket/{_pk}/"

    def test_a_foreign_key_links_to_the_related_page(
        self,
        admin_client,
        worker_client,
        support_desk,
    ):
        seen_by_admin = {
            column["data"]: column
            for column in admin_client.get("/example/ticket/").context[
                "table_config"
            ]["columns"]
        }

        assert seen_by_admin["team"]["linkUrl"] == "/example/team/{_fk_team}/"
        assert seen_by_admin["customer"]["linkUrl"] == (
            "/example/customer/{_fk_customer}/"
        )

    def test_no_link_to_what_the_user_may_not_open(
        self,
        worker_client,
        support_desk,
    ):
        columns = {
            column["data"]: column
            for column in worker_client.get("/example/ticket/").context[
                "table_config"
            ]["columns"]
        }

        assert columns["team"]["linkUrl"] == "/example/team/{_fk_team}/"
        assert not columns["customer"].get("linkUrl")

    def test_a_change_page_returns_to_the_summary(
        self,
        admin_client,
        support_desk,
    ):
        login = support_desk["login"]
        response = admin_client.get(f"/example/ticket/{login.pk}/change/")

        assert response.context["form_config"]["returnUrl"] == (
            f"/example/ticket/{login.pk}/"
        )

    def test_an_add_from_a_related_table_comes_back(
        self,
        admin_client,
        support_desk,
    ):
        front = support_desk["front"]
        response = admin_client.get(
            "/example/ticket/add/",
            {"team": front.pk, "_next": f"/example/team/{front.pk}/"},
        )
        config = response.context["form_config"]

        assert config["returnUrl"] == f"/example/team/{front.pk}/"
        assert config["initial"] == {"team": str(front.pk)}

    def test_a_next_leading_elsewhere_is_ignored(self, admin_client, db):
        response = admin_client.get(
            "/example/ticket/add/",
            {"_next": "https://elsewhere.example/"},
        )

        assert response.context["form_config"]["returnUrl"] == ""

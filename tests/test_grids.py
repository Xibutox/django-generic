"""Grids: rows added in the table, and grids over any set of records.

Two ways a grid knows what it is: the relation of a record's page
(``_related``) and a grid the resource declares (``_grid``). Either
way the browser only names it - which columns a new row writes, what it
gets without asking and which rows are shown are the server's.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from example.models import Customer, Ticket, TimeEntry
from generic.sites import Grid, site

pytestmark = pytest.mark.django_db

ENTRY_ROWS = "/api/example/timeentry/rows/"
TICKET_ROWS = "/api/example/ticket/rows/"
TICKETS = "/api/example/ticket/"
TRIAGE = "example.ticket.triage"


def post(client, url: str, data: dict):
    return client.post(url, data, content_type="application/json")


def patch(client, url: str, data: dict):
    return client.patch(url, data, content_type="application/json")


def related(ticket) -> str:
    return f"_related=example.ticket.time_entries:{ticket.pk}"


def options_of(client, url: str) -> dict:
    return client.get(url).context["table_config"]["options"]


def references(client, query: str) -> set[str]:
    response = client.get(f"{TICKETS}?draw=1&length=100&{query}")

    assert response.status_code == 200, response.content

    return {row["reference"] for row in response.json()["data"]}


@pytest.fixture
def ticket(support_desk):
    return support_desk["login"]


@pytest.fixture
def entry(support_desk) -> TimeEntry:
    return TimeEntry.objects.create(
        ticket=support_desk["login"],
        agent=support_desk["camille"],
        hours=Decimal("1.50"),
        spent_on=datetime.date(2026, 9, 1),
    )


@pytest.fixture
def corrector_client(client, django_user_model):
    """May correct the hours, never add any."""
    user = django_user_model.objects.create_user(username="corrector")
    user.user_permissions.set(
        Permission.objects.filter(
            codename__in=(
                "view_timeentry",
                "change_timeentry",
                "view_ticket",
                "view_agent",
            )
        )
    )
    client.force_login(user)

    return client


@pytest.fixture
def declare():
    """Give a resource grids of the test's own, for the test only."""
    touched = []

    def run(model, *grids):
        resource = site.get_resource(model)
        resource.grids = grids
        resource.__dict__.pop("_bound_grids", None)
        touched.append(resource)

        return resource

    yield run

    for resource in touched:
        del resource.grids
        resource.__dict__.pop("_bound_grids", None)


class TestAddingARow:
    """On a record's page: the row belongs to the record at once."""

    def test_the_page_offers_it(self, admin_client, ticket):
        added = options_of(
            admin_client, f"/example/tickets/{ticket.pk}/work/"
        )["gridAdd"]

        assert added["url"] == (
            f"{ENTRY_ROWS}?_related=example.ticket.time_entries%3A{ticket.pk}"
        )
        # Its own columns: not the ticket, which the page fills in, and
        # not the ticket's status, which has no record to write to yet.
        assert set(added["columns"]) == {
            "spent_on",
            "hours",
            "is_billable",
            "note",
            "agent",
        }
        # The model's defaults, a callable one called for this request.
        assert added["initial"]["spent_on"] == (
            timezone.localdate().isoformat()
        )
        assert added["initial"]["is_billable"] is True

    def test_the_row_belongs_to_the_record(
        self,
        admin_client,
        ticket,
        support_desk,
    ):
        response = post(
            admin_client,
            f"{ENTRY_ROWS}?{related(ticket)}",
            {
                "agent": support_desk["yanis"].pk,
                "hours": "1.25",
                "note": "Pairing",
            },
        )

        assert response.status_code == 201, response.content

        created = TimeEntry.objects.get(note="Pairing")

        assert created.ticket == ticket
        assert created.hours == Decimal("1.25")
        # The answer is the row, as the table draws it.
        assert response.json()["_pk"] == created.pk

    def test_what_is_missing_is_said_under_its_cell(
        self,
        admin_client,
        ticket,
    ):
        """Left empty, a control is not sent: its cell still gets the
        message, because the row shows it."""
        response = post(
            admin_client, f"{ENTRY_ROWS}?{related(ticket)}", {"note": "x"}
        )

        assert response.status_code == 400
        assert {"agent", "hours"} <= set(response.json())

    def test_the_row_cannot_be_given_to_another_record(
        self,
        admin_client,
        ticket,
        support_desk,
    ):
        other = support_desk["invoice"]
        response = post(
            admin_client,
            f"{ENTRY_ROWS}?{related(ticket)}",
            {
                "ticket": other.pk,
                "agent": support_desk["yanis"].pk,
                "hours": "1",
            },
        )

        assert response.status_code == 400
        assert "ticket" in response.json()
        assert not TimeEntry.objects.filter(ticket=other).exists()

    def test_a_column_of_another_record_cannot_be_set(
        self,
        admin_client,
        ticket,
        support_desk,
    ):
        response = post(
            admin_client,
            f"{ENTRY_ROWS}?{related(ticket)}",
            {
                "agent": support_desk["yanis"].pk,
                "hours": "1",
                "ticket__status": "closed",
            },
        )

        assert response.status_code == 400
        assert "ticket__status" in response.json()

    def test_a_reader_who_may_not_add_is_offered_nothing(
        self,
        corrector_client,
        ticket,
        support_desk,
    ):
        options = options_of(
            corrector_client, f"/example/tickets/{ticket.pk}/work/"
        )

        assert "gridAdd" not in options
        assert "editable" in options
        assert (
            post(
                corrector_client,
                f"{ENTRY_ROWS}?{related(ticket)}",
                {"agent": support_desk["yanis"].pk, "hours": "1"},
            ).status_code
            == 403
        )

    def test_a_table_nothing_could_attach_the_row_to_adds_none(
        self,
        admin_client,
        support_desk,
    ):
        """The customer's time goes through its tickets: a new row
        would have no ticket, so none is offered."""
        customer = Customer.objects.create(name="Northwind", code="NWT")
        page = admin_client.get(f"/example/customer/{customer.pk}/")
        tables = {
            table["name"]: table for table in page.context["related_tables"]
        }

        assert "gridAdd" not in tables["time_spent"]["config"]["options"]
        assert (
            post(
                admin_client,
                f"{ENTRY_ROWS}?_related=example.customer.time_spent:"
                f"{customer.pk}",
                {"agent": support_desk["yanis"].pk, "hours": "1"},
            ).status_code
            == 403
        )

    def test_the_resource_decides_what_is_created(
        self,
        admin_client,
        ticket,
        support_desk,
    ):
        """``create_editable`` is the whole of the creation."""
        resource = site.get_resource(TimeEntry)
        original = resource.create_editable

        def stamped(request, values, fixed):
            return original(request, {**values, "note": "stamped"}, fixed)

        resource.create_editable = stamped

        try:
            response = post(
                admin_client,
                f"{ENTRY_ROWS}?{related(ticket)}",
                {"agent": support_desk["yanis"].pk, "hours": "2"},
            )
        finally:
            del resource.create_editable

        assert response.status_code == 201
        assert TimeEntry.objects.get(pk=response.json()["_pk"]).note == (
            "stamped"
        )


class TestTheTriageGrid:
    """A set the project chose: every open ticket, or one team's."""

    def test_the_rows_are_the_grid_s(self, admin_client, support_desk):
        assert references(admin_client, f"_grid={TRIAGE}") == {"SD-1", "SD-2"}

    def test_an_argument_narrows_them(self, admin_client, support_desk):
        front = support_desk["front"]

        assert references(admin_client, f"_grid={TRIAGE}:{front.pk}") == {
            "SD-1"
        }

    @pytest.mark.parametrize(
        "grid",
        [
            f"{TRIAGE}:abc",  # the scope's int() refuses it
            "example.ticket.nope",  # nobody declares it
        ],
    )
    def test_what_names_nothing_is_not_found(
        self,
        admin_client,
        support_desk,
        grid,
    ):
        response = admin_client.get(f"{TICKETS}?draw=1&_grid={grid}")

        assert response.status_code == 404

    def test_another_model_s_grid_is_not_this_endpoint_s(
        self,
        admin_client,
        support_desk,
    ):
        response = admin_client.get(
            f"/api/example/timeentry/?draw=1&_grid={TRIAGE}"
        )

        assert response.status_code == 404

    def test_the_page_shows_it(self, admin_client, support_desk):
        response = admin_client.get("/example/triage/")
        options = response.context["table_config"]["options"]

        assert response.status_code == 200
        assert response.context["page_title"] == "Triage"
        assert options["extraParams"] == {"_grid": TRIAGE}
        assert options["editableUrl"].endswith(f"/cells/?_grid={TRIAGE}")
        # The reference after SD-3, where its control starts.
        assert options["gridAdd"]["initial"]["reference"] == "SD-4"

    def test_one_team_s_page(self, admin_client, support_desk):
        front = support_desk["front"]
        response = admin_client.get(f"/example/teams/{front.pk}/triage/")
        added = response.context["table_config"]["options"]["gridAdd"]

        assert response.status_code == 200
        # A new ticket starts in the team - and says which, by name.
        assert added["initial"]["team"] == front.pk
        assert added["labels"]["team"] == {str(front.pk): "Front office"}

    @pytest.mark.parametrize("argument", ["abc", "99999"])
    def test_a_team_that_is_not_there_is_not_found(
        self,
        admin_client,
        support_desk,
        argument,
    ):
        response = admin_client.get(f"/example/teams/{argument}/triage/")

        assert response.status_code == 404

    def test_a_reader_who_may_not_see_tickets_is_refused(
        self,
        client,
        django_user_model,
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))

        assert client.get("/example/triage/").status_code == 403

    def test_a_new_ticket_starts_where_the_grid_says(
        self,
        admin_client,
        support_desk,
    ):
        front = support_desk["front"]
        response = post(
            admin_client,
            f"{TICKET_ROWS}?_grid={TRIAGE}:{front.pk}",
            {"reference": "SD-50", "title": "Printer"},
        )

        assert response.status_code == 201, response.content

        created = Ticket.objects.get(reference="SD-50")

        assert created.team == front
        assert created.status == Ticket.Status.OPEN

    def test_the_reader_may_change_where_a_control_starts(
        self,
        admin_client,
        support_desk,
    ):
        infra = support_desk["infra"]
        response = post(
            admin_client,
            f"{TICKET_ROWS}?_grid={TRIAGE}:{support_desk['front'].pk}",
            {"reference": "SD-51", "title": "Router", "team": infra.pk},
        )

        assert response.status_code == 201, response.content
        assert Ticket.objects.get(reference="SD-51").team == infra


class TestAGridsOwnRules:
    def test_a_grid_may_write_fewer_columns(
        self,
        admin_client,
        entry,
        declare,
    ):
        declare(TimeEntry, Grid("hours", editable=("hours",)))
        url = f"/api/example/timeentry/{entry.pk}/cells/"
        query = "?_grid=example.timeentry.hours"

        assert patch(admin_client, url + query, {"note": "x"}).status_code == (
            400
        )
        assert patch(
            admin_client, url + query, {"hours": "2"}
        ).status_code == (200)

    def test_what_it_imposes_is_not_the_reader_s(
        self,
        admin_client,
        support_desk,
        declare,
    ):
        """A value of a column the new row does not write is set, and
        the reader cannot send one."""
        ticket = support_desk["login"]
        declare(
            TimeEntry,
            Grid(
                "logging",
                editable=("hours", "agent", "spent_on"),
                add_values=lambda request, argument: {
                    "ticket": ticket,
                    "is_billable": False,
                },
            ),
        )
        url = f"{ENTRY_ROWS}?_grid=example.timeentry.logging"
        row = {"hours": "1", "agent": support_desk["camille"].pk}

        refused = post(admin_client, url, {**row, "is_billable": True})
        created = post(admin_client, url, row)

        assert refused.status_code == 400
        assert created.status_code == 201, created.content

        entry = TimeEntry.objects.get(pk=created.json()["_pk"])

        assert entry.ticket == ticket
        assert entry.is_billable is False

    def test_a_field_the_row_does_not_show_is_named_for_the_row(
        self,
        admin_client,
        support_desk,
        declare,
    ):
        declare(TimeEntry, Grid("notes", editable=("note",)))
        response = post(
            admin_client,
            f"{ENTRY_ROWS}?_grid=example.timeentry.notes",
            {"note": "x"},
        )

        assert response.status_code == 400

        detail = " ".join(response.json()["detail"])

        assert "Ticket" in detail
        assert "Agent" in detail

    def test_a_grid_may_add_nothing(self, admin_client, entry, declare):
        declare(TimeEntry, Grid("reading", allow_add=False))
        resource = site.get_resource(TimeEntry)
        options = resource.get_bound_grid("reading").get_table_config(
            admin_client.get("/").wsgi_request
        )["options"]

        assert "gridAdd" not in options
        assert (
            post(
                admin_client,
                f"{ENTRY_ROWS}?_grid=example.timeentry.reading",
                {"hours": "1"},
            ).status_code
            == 403
        )


class TestDeclaringOne:
    @pytest.mark.parametrize(
        "grid,complaint",
        [
            (Grid("a", columns=("nowhere",)), "list_display"),
            (Grid("b", editable=("ticket",)), "editable_fields"),
            (Grid("c", add_fields=("ticket__status",)), "another record"),
            (Grid("d", scope="no_such_method"), "not a method"),
        ],
    )
    def test_a_mistake_is_an_error_at_start_up(
        self,
        declare,
        grid,
        complaint,
    ):
        resource = declare(TimeEntry, grid)

        with pytest.raises(ImproperlyConfigured, match=complaint):
            resource.get_grids()

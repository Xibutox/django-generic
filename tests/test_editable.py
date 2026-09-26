"""Cells edited in the table itself.

The interesting half is the one that crosses models: a timesheet row
carrying a field of the ticket it points at, written under the
ticket's permission rather than the timesheet's.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Agent, TimeEntry
from generic.sites import ModelResource, site
from generic.sites.editable import columns_of, resolve

pytestmark = pytest.mark.django_db


def cells(pk: int) -> str:
    return f"/api/example/timeentry/{pk}/cells/"


def patch(client, url: str, data: dict):
    return client.patch(url, data, content_type="application/json")


def permissions(*codenames: str):
    return Permission.objects.filter(codename__in=codenames)


@pytest.fixture
def entry(support_desk) -> TimeEntry:
    return TimeEntry.objects.create(
        ticket=support_desk["login"],
        agent=support_desk["camille"],
        hours=Decimal("1.50"),
        spent_on=datetime.date(2026, 9, 1),
        note="Investigation",
    )


@pytest.fixture
def keeper(django_user_model):
    """Somebody who may correct a timesheet, and nothing else.

    No ticket permission on purpose: the column that reaches into the
    ticket has to refuse them.
    """
    user = django_user_model.objects.create_user(username="keeper")
    user.user_permissions.set(
        permissions("view_timeentry", "change_timeentry", "view_agent")
    )

    return user


@pytest.fixture
def keeper_client(client, keeper):
    client.force_login(keeper)

    return client


class TestWhatCanBeEdited:
    def test_a_field_of_the_row_resolves_to_itself(self):
        resource = site.get_resource(TimeEntry)
        column = resolve(resource, "hours")

        assert column.model is TimeEntry
        assert column.field_name == "hours"
        assert column.path == ()

    def test_a_path_resolves_to_the_record_it_ends_on(self):
        from example.models import Ticket

        column = resolve(site.get_resource(TimeEntry), "ticket__status")

        assert column.model is Ticket
        assert column.field_name == "status"
        assert column.path == ("ticket",)

    def test_a_column_that_is_not_on_the_table_is_refused(self):
        class Quiet(ModelResource):
            list_display = ("hours",)
            editable_fields = ("note",)

        with pytest.raises(ImproperlyConfigured) as refusal:
            columns_of(Quiet(TimeEntry, site))

        assert "list_display" in str(refusal.value)

    def test_a_computed_column_cannot_be_edited(self):
        with pytest.raises(ImproperlyConfigured) as refusal:
            resolve(site.get_resource(TimeEntry), "duration_display")

        assert "save_editable" in str(refusal.value)

    def test_a_many_valued_path_is_refused(self):
        """A row has one record to write to; ``tickets__title`` has
        none in particular."""
        with pytest.raises(ImproperlyConfigured) as refusal:
            resolve(site.get_resource(Agent), "tickets__title")

        assert "single-valued" in str(refusal.value)


def options_for(client, url: str) -> dict:
    return client.get(url).context["table_config"]["options"]


def config_for(user, editable=None) -> dict:
    """The time entry table as a page would ask for it."""
    from django.test import RequestFactory

    request = RequestFactory().get("/")
    request.user = user

    return site.get_resource(TimeEntry).get_table_config(
        request,
        editable=editable,
    )["options"]


class TestWhoOffersIt:
    """Declaring the fields turns nothing on. A table asks."""

    def test_a_list_page_reads(self, admin_client, entry):
        """The default, and the reason this is not one attribute: a
        list is usually read on the way to somewhere else."""
        options = options_for(admin_client, "/example/timeentry/")

        assert "editable" not in options

    def test_a_related_table_that_asks_for_it_offers_it(
        self,
        admin_client,
        entry,
        support_desk,
    ):
        """The customer's "Time spent" tab declares editable=True."""
        from example.models import Customer

        customer = Customer.objects.create(name="Northwind", code="NWT")
        support_desk["login"].customer = customer
        support_desk["login"].save()

        page = admin_client.get(f"/example/customer/{customer.pk}/")
        tables = {
            table["name"]: table for table in page.context["related_tables"]
        }

        assert "editable" in tables["time_spent"]["config"]["options"]

    def test_a_page_may_ask_for_it_whatever_the_declaration_says(
        self,
        admin_client,
        entry,
    ):
        """The shape this is really for: a page about one record."""
        options = options_for(
            admin_client,
            f"/example/tickets/{entry.ticket.pk}/work/",
        )

        assert "editable" in options
        assert options["extraParams"]["_related"].endswith(
            f":{entry.ticket.pk}"
        )

    def test_the_record_s_page_leads_to_the_page_built_for_it(
        self,
        admin_client,
        entry,
    ):
        """A page built around a record is only useful if the record
        says where it is."""
        page = admin_client.get(f"/example/ticket/{entry.ticket.pk}/")
        urls = [item.url for item in page.context["toolbar_items"]]

        assert f"/example/tickets/{entry.ticket.pk}/work/" in urls

    def test_nobody_is_led_to_a_page_they_cannot_open(
        self,
        worker_client,
        entry,
    ):
        """The desk agent may read tickets but not time entries."""
        page = worker_client.get(f"/example/ticket/{entry.ticket.pk}/")
        urls = [item.url for item in page.context["toolbar_items"]]

        assert not any(url.endswith("/work/") for url in urls)
        assert (
            worker_client.get(
                f"/example/tickets/{entry.ticket.pk}/work/"
            ).status_code
            == 403
        )

    def test_the_resource_may_light_up_its_own_list(self, admin_user):
        resource = site.get_resource(TimeEntry)
        before = config_for(admin_user)

        resource.list_editable = True

        try:
            after = config_for(admin_user)
        finally:
            resource.list_editable = False

        assert "editable" not in before
        assert "editable" in after


class TestAGridLeadsNowhere:
    """An editable table is where the work happens: nothing in it opens
    anything else."""

    def columns(self, options_source):
        return {column["data"]: column for column in options_source["columns"]}

    def test_no_cell_is_a_link(self, admin_user):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = admin_user
        resource = site.get_resource(TimeEntry)

        grid = self.columns(resource.get_table_config(request, editable=True))
        listed = self.columns(resource.get_table_config(request))

        # The list still links the row to its page and a relation to
        # the record it names...
        assert listed["spent_on"]["linkUrl"]
        assert listed["agent"]["linkUrl"]
        # ...and the grid does neither.
        assert not any(
            "linkUrl" in column or "tagUrl" in column
            for column in grid.values()
        )

    def test_a_linked_cell_keeps_the_type_it_would_have_had(self, admin_user):
        """The date that was the row's link is drawn as a date, and a
        relation's label as the text it is."""
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = admin_user
        grid = self.columns(
            site.get_resource(TimeEntry).get_table_config(
                request, editable=True
            )
        )

        assert grid["spent_on"]["type"] == "date"
        assert grid["ticket"]["type"] == "text"

    def test_no_row_opens_or_offers_a_menu(self, admin_client, entry):
        options = options_for(
            admin_client,
            f"/example/tickets/{entry.ticket.pk}/work/",
        )

        assert options["rowActions"] == []
        assert options["grid"] is True

    def test_the_set_can_still_be_acted_on(self, admin_client, entry):
        """Selection and bulk actions act on the rows in view, which is
        what the page is for."""
        options = options_for(
            admin_client,
            f"/example/tickets/{entry.ticket.pk}/work/",
        )

        assert [action["name"] for action in options["bulkActions"]] == [
            "mark_billable",
            "delete_selected",
        ]

    def test_a_grid_keeps_its_own_layout(self, admin_user):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = admin_user
        resource = site.get_resource(TimeEntry)

        grid = resource.get_table_config(request, editable=True)["options"]
        listed = resource.get_table_config(request)["options"]

        assert grid["stateKey"] != listed["stateKey"]

    def test_a_reader_who_may_write_nothing_still_sees_a_grid(
        self,
        user,
        entry,
    ):
        """The page is a working grid whoever opens it; only the
        controls depend on the reader."""
        user.user_permissions.set(permissions("view_timeentry"))
        options = config_for(user, editable=True)

        assert "editable" not in options
        assert options["rowActions"] == []


class TestWhatTheTableIsTold:
    def test_the_columns_come_with_how_to_edit_them(
        self,
        admin_client,
        entry,
    ):
        options = options_for(
            admin_client,
            f"/example/tickets/{entry.ticket.pk}/work/",
        )
        described = options["editable"]

        # The relation travels with every write, so the endpoint knows
        # which table the cell was written in.
        assert options["editableUrl"].endswith(
            f"/cells/?_related=example.ticket.time_entries%3A{entry.ticket.pk}"
        )
        assert described["hours"]["type"] == "decimal"
        assert described["is_billable"]["type"] == "boolean"
        # A relation is an autocomplete, as it is on a form.
        assert described["agent"]["autocompleteUrl"]
        # And the write goes to the field, under the public name.
        assert described["ticket__status"]["field"] == "status"

    def test_a_column_the_reader_may_not_write_is_not_described(
        self,
        keeper,
        entry,
    ):
        described = config_for(keeper, editable=True)["editable"]

        assert "hours" in described
        # They may not change tickets, so the cell is drawn as text.
        assert "ticket__status" not in described

    def test_a_reader_who_may_change_nothing_is_told_nothing(
        self,
        user,
        entry,
    ):
        """A table with no editable cell should not even mention it."""
        user.user_permissions.set(permissions("view_timeentry"))

        assert "editable" not in config_for(user, editable=True)


class TestWriting:
    def test_a_cell_of_the_row_is_saved(self, admin_client, entry):
        response = patch(admin_client, cells(entry.pk), {"hours": "2.25"})
        entry.refresh_from_db()

        assert response.status_code == 200
        assert entry.hours == Decimal("2.25")

    def test_several_cells_at_once(self, admin_client, entry):
        patch(
            admin_client,
            cells(entry.pk),
            {"note": "Rewritten", "is_billable": True},
        )
        entry.refresh_from_db()

        assert (entry.note, entry.is_billable) == ("Rewritten", True)

    def test_a_cell_of_another_model_is_saved_on_that_model(
        self,
        admin_client,
        entry,
        support_desk,
    ):
        patch(admin_client, cells(entry.pk), {"ticket__status": "closed"})
        entry.refresh_from_db()
        support_desk["login"].refresh_from_db()

        assert support_desk["login"].status == "closed"

    def test_both_models_in_one_call(self, admin_client, entry):
        response = patch(
            admin_client,
            cells(entry.pk),
            {"hours": "3.00", "ticket__status": "resolved"},
        )
        entry.refresh_from_db()
        entry.ticket.refresh_from_db()

        assert response.status_code == 200
        assert entry.hours == Decimal("3.00")
        assert entry.ticket.status == "resolved"

    def test_the_row_comes_back_as_the_table_draws_it(
        self,
        admin_client,
        entry,
    ):
        """A change often moves more than the cell it was typed in."""
        body = patch(
            admin_client,
            cells(entry.pk),
            {"ticket__status": "closed"},
        ).json()

        # The key, not the label: a choice column carries its choices
        # in the table configuration and the browser draws the word.
        assert body["hours"] == "1.50"
        assert body["ticket__status"] == "closed"

    def test_nothing_is_written_when_one_cell_is_refused(
        self,
        admin_client,
        entry,
    ):
        """All of a row or none of it: the two records are one change."""
        response = patch(
            admin_client,
            cells(entry.pk),
            {"hours": "9.00", "ticket__status": "not-a-status"},
        )
        entry.refresh_from_db()

        assert response.status_code == 400
        assert entry.hours == Decimal("1.50")


class TestRefusals:
    def test_a_column_nobody_declared_is_refused(self, admin_client, entry):
        response = patch(admin_client, cells(entry.pk), {"ticket": 1})

        assert response.status_code == 400
        assert "ticket" in response.json()

    def test_an_invalid_value_is_named_by_its_column(
        self,
        admin_client,
        entry,
    ):
        """The error has to land on the cell it was typed in, which is
        the public name and not the field's."""
        response = patch(
            admin_client,
            cells(entry.pk),
            {"ticket__status": "nonsense"},
        )

        assert response.status_code == 400
        assert "ticket__status" in response.json()

    def test_the_other_model_s_permission_is_the_one_that_decides(
        self,
        keeper_client,
        entry,
    ):
        """They may correct the timesheet and not the ticket."""
        allowed = patch(keeper_client, cells(entry.pk), {"hours": "4.00"})
        refused = patch(
            keeper_client,
            cells(entry.pk),
            {"ticket__status": "closed"},
        )
        entry.refresh_from_db()
        entry.ticket.refresh_from_db()

        assert allowed.status_code == 200
        assert entry.hours == Decimal("4.00")
        assert refused.status_code == 400
        assert entry.ticket.status != "closed"

    def test_a_reader_who_may_not_change_the_row_is_refused(
        self,
        auth_client,
        entry,
    ):
        response = patch(auth_client, cells(entry.pk), {"hours": "5.00"})

        assert response.status_code == 403

    def test_an_empty_body_says_so(self, admin_client, entry):
        assert patch(admin_client, cells(entry.pk), {}).status_code == 400

    def test_a_table_with_no_editable_column_has_no_endpoint(
        self,
        admin_client,
        support_desk,
    ):
        team = support_desk["login"].team
        response = patch(
            admin_client,
            f"/api/example/team/{team.pk}/cells/",
            {"name": "Renamed"},
        )

        assert response.status_code == 404


class TestReprogrammingIt:
    def test_the_resource_decides_what_finally_happens(
        self,
        admin_client,
        entry,
    ):
        """``save_editable`` is the whole of the write, and replacing
        it replaces the write."""
        resource = site.get_resource(TimeEntry)
        seen = {}

        def save_editable(request, obj, changes):
            seen["changes"] = changes
            obj.note = "written by the hook"
            obj.save(update_fields=["note"])

        original = resource.save_editable
        resource.save_editable = save_editable

        try:
            patch(admin_client, cells(entry.pk), {"hours": "8.00"})
        finally:
            resource.save_editable = original

        entry.refresh_from_db()

        assert seen["changes"] == {"hours": "8.00"}
        assert entry.note == "written by the hook"
        # The default write never ran.
        assert entry.hours == Decimal("1.50")

    def test_a_column_can_be_frozen_by_the_application(
        self,
        admin_client,
        admin_user,
        entry,
    ):
        resource = site.get_resource(TimeEntry)

        def can_edit_column(request, column, obj=None):
            return column != "hours"

        original = resource.can_edit_column
        resource.can_edit_column = can_edit_column

        try:
            response = patch(admin_client, cells(entry.pk), {"hours": "8.00"})
            described = config_for(admin_user, editable=True)["editable"]
        finally:
            resource.can_edit_column = original

        entry.refresh_from_db()

        assert response.status_code == 400
        assert entry.hours == Decimal("1.50")
        # And the table never offered it in the first place.
        assert "hours" not in described

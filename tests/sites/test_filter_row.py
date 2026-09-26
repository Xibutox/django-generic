"""The row of search fields under a table's headers, as declared."""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from example.models import Ticket
from generic.sites import site

pytestmark = pytest.mark.django_db


def options_of(response) -> dict:
    return response.context["table_config"]["options"]


class TestDeclaration:
    def test_a_list_shows_the_row_from_the_start(
        self, admin_client, support_desk
    ):
        response = admin_client.get("/example/ticket/")

        assert options_of(response)["filterRow"] == "open"

    def test_a_resource_may_keep_the_row_behind_its_button(
        self, admin_client, support_desk
    ):
        response = admin_client.get("/example/tag/")

        assert options_of(response)["filterRow"] == "toggle"

    def test_a_date_opening_its_record_is_still_filtered_as_a_date(
        self, admin_client, support_desk
    ):
        # The first column of the time entries links to the entry; its
        # field in the row read "30d" as words to look for, and the
        # endpoint refused the filter.
        response = admin_client.get("/example/timeentry/")
        columns = {
            column["data"]: column
            for column in response.context["table_config"]["columns"]
        }

        assert columns["spent_on"]["type"] == "link"
        assert columns["spent_on"]["filterType"] == "date"

    def test_a_related_table_follows_its_resource(
        self, admin_client, support_desk
    ):
        front = support_desk["front"]
        response = admin_client.get(f"/example/team/{front.pk}/")
        tickets = next(
            table
            for table in response.context["related_tables"]
            if table["name"] == "tickets"
        )

        assert tickets["config"]["options"]["filterRow"] == "open"

    def test_a_resource_may_leave_the_row_out(
        self, admin_client, support_desk, monkeypatch
    ):
        resource = site.get_resource(Ticket)
        monkeypatch.setattr(type(resource), "filter_row", False)

        response = admin_client.get("/example/ticket/")

        assert options_of(response)["filterRow"] is False

    @pytest.mark.parametrize("value", ["opened", True, None, 0])
    def test_anything_else_is_a_declaration_error(
        self, rf, admin_user, monkeypatch, value
    ):
        resource = site.get_resource(Ticket)
        monkeypatch.setattr(type(resource), "filter_row", value)
        request = rf.get("/example/ticket/")
        request.user = admin_user

        with pytest.raises(
            ImproperlyConfigured, match="TicketResource.filter_row"
        ):
            resource.get_table_options(request)

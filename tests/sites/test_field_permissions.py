"""Field permissions: a field some readers may not see, or not change.

The example's articles carry a unit cost for whoever may change them
(``ArticleResource.field_permissions``): a reader who may only view
the articles gets them without it, through every screen and endpoint.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission

from example.models import Article
from generic.sites import site
from generic.sites.serializers import restricted

pytestmark = pytest.mark.django_db

ARTICLES = "/api/example/article/"
BOM = "/api/example/article/trees/bom/"


def permissions(*codenames: str):
    return Permission.objects.filter(codename__in=codenames)


def user_with(django_user_model, name: str, *codenames: str):
    user = django_user_model.objects.create_user(username=name)
    user.user_permissions.set(permissions(*codenames))

    return user


@pytest.fixture
def resource():
    return site.get_resource(Article)


@pytest.fixture
def reader(django_user_model):
    """Reads the articles: not what they cost."""
    return user_with(django_user_model, "reader", "view_article")


@pytest.fixture
def maintainer(django_user_model):
    return user_with(
        django_user_model, "maintainer", "view_article", "change_article"
    )


@pytest.fixture
def article(db) -> Article:
    return Article.objects.create(
        reference="SP-1",
        name="Spoke",
        kind="part",
        unit_cost=Decimal("0.40"),
    )


def rows(client, **params) -> list[dict]:
    response = client.get(ARTICLES, params)

    assert response.status_code == 200, response.content

    return response.json()["data"]


class TestTheRules:
    def test_a_string_is_the_permission_to_see_the_field(
        self, resource, rf, reader, maintainer
    ):
        request = rf.get("/")
        request.user = reader

        assert resource.get_hidden_fields(request) == {"unit_cost"}
        assert resource.get_locked_fields(request) == {"unit_cost"}

        request.user = maintainer

        assert resource.get_hidden_fields(request) == frozenset()
        assert resource.get_locked_fields(request) == frozenset()

    def test_a_pair_is_the_permissions_to_see_and_to_change(
        self, resource, rf, monkeypatch, maintainer
    ):
        monkeypatch.setattr(
            resource,
            "field_permissions",
            {"unit_cost": (None, "example.delete_article")},
        )
        request = rf.get("/")
        request.user = maintainer

        assert resource.get_hidden_fields(request) == frozenset()
        assert resource.get_locked_fields(request) == {"unit_cost"}

    def test_a_dict_names_them(self, resource, monkeypatch):
        monkeypatch.setattr(
            resource,
            "field_permissions",
            {"unit_cost": {"change": "example.delete_article"}},
        )

        assert resource.get_field_permissions() == {
            "unit_cost": (None, "example.delete_article")
        }

    def test_nobody_in_particular_sees_no_guarded_field(self, resource):
        assert resource.get_hidden_fields(None) == {"unit_cost"}

    def test_a_serializer_with_nothing_to_hide_is_itself(self, resource):
        serializer = resource.get_table_serializer_class()

        assert restricted(serializer) is serializer
        assert restricted(serializer, frozenset({"unit_cost"})) is (
            restricted(serializer, frozenset({"unit_cost"}))
        )


class TestTheList:
    def test_the_rows_leave_the_field_out(
        self, client, reader, maintainer, article
    ):
        client.force_login(reader)
        assert "unit_cost" not in rows(client)[0]

        client.force_login(maintainer)
        assert rows(client)[0]["unit_cost"] is not None

    def test_the_page_draws_no_column_for_it(self, resource, rf, reader):
        request = rf.get("/")
        request.user = reader
        columns = resource.get_table_config(request)["columns"]

        assert "unit_cost" not in [column["data"] for column in columns]
        assert "reference" in [column["data"] for column in columns]

    def test_it_is_not_filtered_on(self, client, reader, article):
        client.force_login(reader)
        filters = {"unit_cost": {"operator": "greater_or_equal", "value": 1}}
        response = client.get(
            ARTICLES, {"advanced_filters": json.dumps(filters)}
        )

        # Not a column of this table: refused, never answered.
        assert response.status_code == 400

    def test_it_is_not_ordered_by(self, client, reader, article):
        Article.objects.create(
            reference="AA-1", name="Axle", kind="part", unit_cost=9
        )
        client.force_login(reader)
        ordered = rows(
            client,
            **{
                "columns[0][data]": "unit_cost",
                "order[0][column]": "0",
                "order[0][dir]": "desc",
            },
        )

        # The list's own ordering, by reference: the cost is not asked.
        assert [row["reference"] for row in ordered] == ["AA-1", "SP-1"]

    def test_the_export_leaves_it_out(self, client, reader, article):
        client.force_login(reader)
        response = client.get(f"{ARTICLES}export-csv/")
        body = b"".join(response.streaming_content).decode("utf-8-sig")

        assert response.status_code == 200
        assert "Unit cost" not in body.splitlines()[0]
        assert "0.40" not in body


class TestTheRecord:
    def test_the_form_leaves_it_out(self, client, reader, article):
        client.force_login(reader)
        schema = client.get(f"{ARTICLES}form-schema/").json()
        record = client.get(f"{ARTICLES}{article.pk}/").json()

        assert "unit_cost" not in json.dumps(schema)
        assert "unit_cost" not in record

    def test_the_summary_leaves_it_out(self, client, reader, article):
        client.force_login(reader)
        summary = client.get(f"{ARTICLES}{article.pk}/summary/").json()
        names = [
            entry["name"]
            for section in summary["sections"]
            for entry in section["fields"]
        ]

        assert "unit_cost" not in names
        assert "reference" in names

    def test_the_tree_leaves_it_out(self, client, reader, article):
        client.force_login(reader)
        answer = client.get(BOM).json()

        assert "node.unit_cost" not in [
            column["key"] for column in answer["columns"]
        ]


class TestWriting:
    @pytest.fixture
    def locked(self, resource, monkeypatch):
        """The maintainers see the cost; only who may delete sets it."""
        monkeypatch.setattr(
            resource,
            "field_permissions",
            {"unit_cost": (None, "example.delete_article")},
        )

    def test_the_form_shows_it_read_only(
        self, client, locked, maintainer, article
    ):
        client.force_login(maintainer)
        schema = client.get(f"{ARTICLES}form-schema/").json()
        fields = {
            entry["name"]: entry
            for entry in schema["fields"]
            if isinstance(entry, dict) and "name" in entry
        }

        assert fields["unit_cost"]["readOnly"] is True

    def test_a_change_sent_anyway_is_not_saved(
        self, client, locked, maintainer, article
    ):
        client.force_login(maintainer)
        response = client.patch(
            f"{ARTICLES}{article.pk}/",
            {"name": "Long spoke", "unit_cost": "99"},
            content_type="application/json",
        )
        article.refresh_from_db()

        assert response.status_code == 200, response.content
        assert article.name == "Long spoke"
        assert article.unit_cost == Decimal("0.40")

    def test_a_locked_column_is_not_written_in_the_table(
        self, resource, rf, locked, maintainer
    ):
        request = rf.get("/")
        request.user = maintainer

        assert resource.may_write_column(request, "unit_cost") is False
        assert resource.may_write_column(request, "name") is True


class TestTheTickets:
    """The rest of what a page shows, on the example's tickets: their
    charts, their chart builder, their calendar, their history."""

    @pytest.fixture
    def guarded(self, monkeypatch):
        from example.models import Ticket

        resource = site.get_resource(Ticket)
        monkeypatch.setattr(
            resource,
            "field_permissions",
            {
                "priority": "example.manage_ticket_costs",
                "due_on": (None, "example.manage_ticket_costs"),
                "estimated_hours": "example.manage_ticket_costs",
            },
        )

        return resource

    @pytest.fixture
    def worker_request(self, rf, worker):
        request = rf.get("/")
        request.user = worker

        return request

    def test_a_chart_through_a_hidden_field_is_not_shown(
        self, guarded, worker_request
    ):
        visible = {
            chart.name
            for chart in guarded.get_charts(worker_request)
            if chart.is_visible(worker_request, guarded)
        }

        assert "by_status" in visible
        assert "opened" not in visible  # split by priority
        assert "by_team" not in visible

    def test_a_chart_reads_what_it_sums(self):
        from django.db.models import Sum

        from generic.sites import Chart

        chart = Chart("cost", group_by="team__name", value=Sum("hours"))

        assert chart.get_fields_read() == {"team", "hours"}

    def test_the_chart_builder_offers_none_of_them(
        self, guarded, worker_request
    ):
        builder = guarded.get_chart_builder_for(worker_request)
        offered = builder.describe()

        assert "priority" not in [
            entry["value"] for entry in offered["dimensions"]
        ]
        assert not any(
            "estimated_hours" in entry["value"] for entry in offered["values"]
        )
        # The full builder is left as it was, for the others.
        assert "priority" in guarded.get_chart_builder().dimensions

    def test_the_chart_builder_refuses_them(
        self, client, guarded, worker, support_desk
    ):
        client.force_login(worker)
        response = client.get(
            "/api/example/ticket/chart-builder/", {"group_by": "priority"}
        )

        assert response.status_code == 400
        assert "group_by" in response.json()

    def test_a_calendar_on_a_locked_date_is_not_dragged(
        self, guarded, worker_request
    ):
        bound = guarded.get_calendar("due")

        assert bound.can_move(worker_request) is False

    def test_the_history_leaves_a_hidden_field_out(
        self, client, guarded, worker, support_desk
    ):
        ticket = support_desk["export"]
        ticket.estimated_hours = Decimal("3")
        ticket.title = "Export, slower"
        ticket.save()
        client.force_login(worker)

        answer = client.get(f"/api/example/ticket/{ticket.pk}/history/").json()
        names = {
            change["name"]
            for entry in answer["results"]
            for change in entry["changes"]
        } | {
            value["name"]
            for entry in answer["results"]
            for value in entry["values"]
        }

        assert "title" in names
        assert "estimated_hours" not in names
        assert "priority" not in names

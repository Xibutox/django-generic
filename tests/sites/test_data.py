"""Pages for rows that are not a model's: ``DataResource``.

The example's external services come from a status API - a list of
dicts, dates as text - and get a list page and a page per service, read
only. Everything below goes through them, or through a resource of the
test's own.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

from example import external
from generic.api import (
    BooleanColumn,
    CharColumn,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    FloatColumn,
    IntegerColumn,
    TagsColumn,
)
from generic.sites import (
    DataResource,
    RelatedRows,
    RowLink,
    site,
)
from generic.sites.data import column_for
from generic.sites.site import AlreadyRegistered, GenericSite
from tests.sites.test_resource_api import user_with

pytestmark = pytest.mark.django_db

LIST = "/data/services/"
API = "/api/data/services/"


@pytest.fixture(autouse=True)
def fresh_services():
    """The example keeps the API's answer a minute: not across tests."""
    cache.delete_many([external.CACHE_KEY, external.INCIDENTS_CACHE_KEY])

    yield

    cache.delete_many([external.CACHE_KEY, external.INCIDENTS_CACHE_KEY])


def rows(client, **params):
    response = client.get(API, {"draw": 1, "length": 100, **params})

    assert response.status_code == 200, response.content

    return [row["_pk"] for row in response.json()["data"]]


def tree(*conditions):
    return json.dumps({"match": "all", "conditions": list(conditions)})


class TestTheDeclaration:
    def test_a_type_is_enough_for_a_column(self):
        assert isinstance(column_for("a", str), CharColumn)
        assert isinstance(column_for("a", int), IntegerColumn)
        assert isinstance(column_for("a", float), FloatColumn)
        assert isinstance(column_for("a", Decimal), DecimalColumn)
        assert isinstance(column_for("a", bool), BooleanColumn)
        assert isinstance(column_for("a", datetime.date), DateColumn)
        assert isinstance(column_for("a", datetime.datetime), DateTimeColumn)
        assert isinstance(column_for("a", list), TagsColumn)

    def test_a_column_is_copied_not_shared(self):
        declared = CharColumn(title="Name")

        assert column_for("a", declared) is not declared

    def test_anything_else_is_refused(self):
        with pytest.raises(ImproperlyConfigured):
            column_for("a", object())

    def test_a_name_is_a_piece_of_address(self):
        class Bad(DataResource):
            name = "Not/OK"
            columns = {"a": str}

        with pytest.raises(ImproperlyConfigured):
            Bad(GenericSite(name="data_test"))

    def test_the_name_defaults_to_the_class(self):
        class WeatherStationResource(DataResource):
            columns = {"a": str}

        resource = WeatherStationResource(GenericSite(name="data_test"))

        assert resource.name == "weatherstation"

    def test_columns_are_required(self):
        class Empty(DataResource):
            name = "empty"

        with pytest.raises(ImproperlyConfigured):
            Empty(GenericSite(name="data_test"))

    def test_a_name_is_registered_once(self):
        other = GenericSite(name="data_test")

        class One(DataResource):
            name = "one"
            columns = {"a": str}

        other.register_data(One)

        with pytest.raises(AlreadyRegistered):
            other.register_data(One)

        other.unregister_data("one")
        assert other.get_data_resource("one") is None

    def test_only_data_resources_register_as_data(self):
        with pytest.raises(ImproperlyConfigured):
            GenericSite(name="data_test").register_data(dict)


class TestPermissions:
    def test_anonymous_goes_to_sign_in(self, client):
        response = client.get(LIST)

        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_the_declared_permission_is_required(self, client):
        client.force_login(user_with("view_team"))

        assert client.get(LIST).status_code == 403
        assert client.get(API).status_code == 403
        assert client.get(f"{LIST}paylane/").status_code == 403

    def test_with_it_everything_opens(self, client):
        client.force_login(user_with("view_ticket"))

        assert client.get(LIST).status_code == 200
        assert client.get(API).status_code == 200
        assert client.get(f"{LIST}paylane/").status_code == 200

    def test_a_callable_or_nothing(self, rf, django_user_model):
        user = django_user_model.objects.create_user("someone")
        request = rf.get("/")
        request.user = user

        class Open(DataResource):
            name = "open"
            columns = {"a": str}

        class Staff(Open):
            name = "staff"
            permission = staticmethod(lambda user: user.is_staff)

        other = GenericSite(name="data_test")

        assert Open(other).has_view_permission(request)
        assert not Staff(other).has_view_permission(request)

    def test_read_only_whoever_asks(self, admin_client):
        resource = site.get_data_resource("services")

        for method in ("post", "put", "patch", "delete"):
            response = getattr(admin_client, method)(f"{API}paylane/")

            assert response.status_code in {403, 404, 405}

        assert not resource.has_add_permission(None)
        assert not resource.has_change_permission(None)
        assert not resource.has_delete_permission(None)


class TestTheListPage:
    def test_the_table_is_configured_from_the_columns(self, admin_client):
        config = admin_client.get(LIST).context["table_config"]
        columns = {column["data"]: column for column in config["columns"]}

        assert config["url"] == API
        assert columns["name"]["type"] == "link"
        assert columns["name"]["linkUrl"] == "/data/services/{_pk}/"
        assert columns["status"]["filterType"] == "multiselect"
        assert columns["status"]["facets"] is True
        assert columns["description"]["visible"] is False
        assert config["options"]["rowActions"][0]["url"] == (
            "/data/services/{_pk}/"
        )

    def test_it_is_in_the_navigation(self, admin_client):
        navigation = admin_client.get("/").context["chrome"]["navigation"]
        urls = [item["url"] for group in navigation for item in group["items"]]

        assert LIST in urls

    def test_and_on_the_dashboard(self, admin_client):
        groups = admin_client.get("/").context["app_list"]
        urls = [
            entry["list_url"]
            for group in groups
            for entry in group["resources"]
        ]

        assert LIST in urls

    def test_not_for_whoever_may_not_see_it(self, client):
        client.force_login(user_with("view_team"))
        navigation = client.get("/").context["chrome"]["navigation"]
        urls = [item["url"] for group in navigation for item in group["items"]]

        assert LIST not in urls


class TestTheEndpoint:
    def test_every_row_ordered_as_declared(self, admin_client):
        response = admin_client.get(API, {"draw": 4})
        body = response.json()

        assert body["draw"] == 4
        assert body["recordsTotal"] == len(external.SERVICES)
        assert body["data"][0]["name"] == "BackupBay"

    def test_a_filter_of_each_kind(self, admin_client):
        assert rows(
            admin_client,
            filters=tree(
                {
                    "column": "status",
                    "operator": "any_of",
                    "value": ["major_outage"],
                }
            ),
        ) == ["smsgate"]
        assert rows(
            admin_client,
            filters=tree(
                {"column": "response_ms", "operator": "lt", "value": "90"}
            ),
        ) == ["idgate", "pingwatch"]
        assert rows(
            admin_client,
            filters=tree(
                {
                    "column": "regions",
                    "operator": "any_of",
                    "value": ["ap-south"],
                }
            ),
        ) == ["mapkit", "pingwatch"]
        assert rows(
            admin_client,
            filters=tree({"column": "last_incident", "operator": "empty"}),
        ) == ["pingwatch"]
        assert (
            rows(
                admin_client,
                filters=tree({"column": "checked_at", "operator": "today"}),
            )
            != []
        )

    def test_the_counts_follow_the_filters(self, admin_client):
        body = admin_client.get(
            API,
            {
                "draw": 1,
                "filters": tree({"column": "critical", "operator": "is_true"}),
            },
        ).json()

        assert body["recordsTotal"] == len(external.SERVICES)
        assert body["recordsFiltered"] == 6

    def test_a_column_not_declared_is_refused(self, admin_client):
        response = admin_client.get(
            API,
            {
                "filters": tree(
                    {"column": "id", "operator": "contains", "value": ["a"]}
                )
            },
        )

        assert response.status_code == 400

    def test_the_search_and_the_order(self, admin_client):
        assert rows(admin_client, **{"search[value]": "cloudnest"}) == [
            "cloudnest",
            "cloudnest-storage",
        ]
        assert rows(
            admin_client,
            **{
                "order[0][column]": "0",
                "order[0][dir]": "desc",
                "columns[0][data]": "uptime_90d",
            },
        )[:2] == ["pingwatch", "idgate"]

    def test_facets_count_the_values(self, admin_client):
        body = admin_client.get(f"{API}facets/", {"column": "status"}).json()
        counts = {entry["value"]: entry["count"] for entry in body["values"]}

        assert counts["operational"] == 9
        assert body["values"][0]["tag"]["color"] == "#16a34a"

    def test_a_number_facets_as_a_range(self, admin_client):
        body = admin_client.get(
            f"{API}facets/", {"column": "response_ms"}
        ).json()

        assert body == {
            "column": "response_ms",
            "kind": "range",
            "min": 60,
            "max": 900,
            "empty": 1,
        }

    def test_exports_write_dates_as_dates(self, admin_client):
        response = admin_client.get(f"{API}export-csv/", {"ordering": "name"})
        lines = b"".join(response.streaming_content).decode("utf-8-sig")
        first = lines.splitlines()[1].split(";")

        assert first[0] == "BackupBay"
        # "2026-09-25T..Z" from the API, a local date and time here.
        assert "T" not in first[9] and "Z" not in first[9]

        assert admin_client.get(f"{API}export/").status_code == 200


class TestARowsPage:
    def test_it_shows_the_row_as_its_columns_say(self, admin_client):
        response = admin_client.get(f"{LIST}paylane/")
        summary = response.context["summary"]
        fields = {
            field["name"]: field
            for section in summary["sections"]
            for field in section["fields"]
        }

        assert response.context["page_title"] == "Paylane"
        assert [stat["name"] for stat in summary["stats"]] == [
            "status",
            "uptime_90d",
            "response_ms",
        ]
        assert fields["status_page"]["type"] == "url"
        assert fields["checked_at"]["type"] == "datetime"
        assert fields["last_incident"]["type"] == "date"
        assert fields["regions"]["items"][0]["label"] == "Western Europe"
        assert fields["description"]["wide"] is True
        assert summary["urls"]["change"] == ""
        assert summary["urls"]["delete"] == ""

    def test_the_summary_endpoint_says_the_same(self, admin_client):
        body = admin_client.get(f"{API}paylane/summary/").json()

        assert body["object"]["label"] == "Paylane"
        assert body["object"]["model"] == "data.services"

    def test_an_unknown_key_is_not_found(self, admin_client):
        assert admin_client.get(f"{LIST}nothing/").status_code == 404
        assert admin_client.get(f"{API}nothing/summary/").status_code == 404


INCIDENTS = "/api/data/incidents/"


def related(key: str) -> str:
    return f"services.incidents:{key}"


class TestRelatedRows:
    """A service's page has a tab of its incidents; each incident has
    its own page, leading back to its service."""

    def test_the_services_page_has_a_tab_of_its_incidents(self, admin_client):
        response = admin_client.get(f"{LIST}cloudnest/")
        tables = response.context["related_tables"]
        summary = response.context["summary"]

        assert [table["name"] for table in tables] == ["incidents"]
        assert summary["related"][0]["count"] == 2
        assert summary["related"][0]["title"] == "Incidents"

        config = tables[0]["config"]
        names = [column["data"] for column in config["columns"]]

        assert config["url"] == INCIDENTS
        assert config["options"]["extraParams"] == {
            "_related": related("cloudnest")
        }
        assert config["options"]["syncUrl"] is False
        # The service, the same on every line, is left out.
        assert "service_name" not in names

    def test_the_tab_asks_for_that_services_rows_only(self, admin_client):
        body = admin_client.get(
            INCIDENTS, {"draw": 1, "_related": related("cloudnest")}
        ).json()

        assert [row["_pk"] for row in body["data"]] == [
            "inc-2049",
            "inc-2033",
        ]
        assert body["recordsTotal"] == 2

    def test_filters_facets_and_exports_follow_the_tab(self, admin_client):
        params = {"_related": related("paylane")}
        facets = admin_client.get(
            f"{INCIDENTS}facets/", {"column": "status", **params}
        ).json()
        export = admin_client.get(f"{INCIDENTS}export-csv/", params)
        lines = b"".join(export.streaming_content).decode("utf-8-sig")

        assert {entry["value"] for entry in facets["values"]} == {
            "investigating",
            "resolved",
        }
        assert len(lines.splitlines()) == 3

    def test_the_tab_is_resolved_through_the_declaration(self, admin_client):
        unknown = admin_client.get(
            INCIDENTS, {"_related": "services.secrets:cloudnest"}
        )
        elsewhere = admin_client.get(
            f"{API}", {"_related": related("cloudnest")}
        )
        missing = admin_client.get(INCIDENTS, {"_related": related("nothing")})

        assert unknown.status_code == 400
        # A tab of incidents asked of the services' endpoint.
        assert elsewhere.status_code == 400
        assert missing.status_code == 404

    def test_the_parent_must_be_visible_too(self, client, monkeypatch):
        services = site.get_data_resource("services")
        monkeypatch.setattr(services, "permission", "example.view_team")
        client.force_login(user_with("view_ticket"))

        assert client.get(INCIDENTS).status_code == 200
        assert (
            client.get(
                INCIDENTS, {"_related": related("cloudnest")}
            ).status_code
            == 403
        )

    def test_an_incident_leads_back_to_its_service(self, admin_client):
        config = admin_client.get("/data/incidents/").context["table_config"]
        column = next(
            column
            for column in config["columns"]
            if column["data"] == "service_name"
        )
        row = admin_client.get(INCIDENTS, {"draw": 1}).json()["data"][0]

        assert column["type"] == "link"
        assert column["linkUrl"] == "/data/services/{_link_service_name}/"
        assert row["_link_service_name"] in {
            key for key, *_ in external.SERVICES
        }

        page = admin_client.get("/data/incidents/inc-2049/")
        fields = {
            field["name"]: field
            for section in page.context["summary"]["sections"]
            for field in section["fields"]
        }

        assert fields["service_name"] == {
            "type": "link",
            "display": "CloudNest Compute",
            "url": "/data/services/cloudnest/",
            "name": "service_name",
            "label": "Service",
            "wide": False,
        }

    def test_no_link_to_what_the_reader_may_not_open(
        self, client, monkeypatch
    ):
        services = site.get_data_resource("services")
        monkeypatch.setattr(services, "permission", "example.view_team")
        client.force_login(user_with("view_ticket"))

        config = client.get("/data/incidents/").context["table_config"]
        column = next(
            column
            for column in config["columns"]
            if column["data"] == "service_name"
        )
        page = client.get("/data/incidents/inc-2049/")
        fields = {
            field["name"]: field
            for section in page.context["summary"]["sections"]
            for field in section["fields"]
        }

        assert "linkUrl" not in column
        assert fields["service_name"]["url"] == ""

    def test_timestamps_read_as_the_models_are(self, admin_client):
        row = admin_client.get(INCIDENTS, {"draw": 1}).json()["data"][0]

        # "2026-09-25T11:07:01Z" from the API; ISO in the active time
        # zone here, as a model's timestamp travels - the browser draws
        # it in the reader's language.
        assert row["started_at"].endswith(("+01:00", "+02:00"))
        assert row["started_at"][10] == "T"


class TestDeclaringRelations:
    @pytest.fixture
    def other(self):
        return GenericSite(name="data_test")

    def test_rows_may_be_fetched_per_parent(self, other, rf, admin_user):
        class Teams(DataResource):
            name = "teams"
            columns = {"id": str}
            related_tables = (
                RelatedRows(
                    "members",
                    resource="members",
                    rows=lambda request, team: [{"id": team["id"] + "-1"}],
                ),
            )

            def get_rows(self, request):
                return [{"id": "a"}]

        class Members(DataResource):
            name = "members"
            columns = {"id": str}

            def get_rows(self, request):
                return []

        teams = other.register_data(Teams)
        other.register_data(Members)
        request = rf.get("/")
        request.user = admin_user

        assert teams.get_related_rows(
            request, teams.get_related("members"), {"id": "a"}
        ) == [{"id": "a-1"}]

    def test_a_relation_needs_a_field_or_rows(self, other):
        class One(DataResource):
            name = "one"
            columns = {"id": str}
            related_tables = (RelatedRows("more", resource="one"),)

        with pytest.raises(ImproperlyConfigured):
            other.register_data(One).check()

    def test_a_relation_names_a_registered_resource(self, other):
        class One(DataResource):
            name = "one"
            columns = {"id": str}
            related_tables = (
                RelatedRows("more", resource="nowhere", field="id"),
            )

        with pytest.raises(ImproperlyConfigured):
            other.register_data(One).check()

    def test_a_link_is_one_of_the_columns(self, other):
        class One(DataResource):
            name = "one"
            columns = {"id": str}
            links = {"elsewhere": "one"}

        with pytest.raises(ImproperlyConfigured):
            other.register_data(One).check()

    def test_a_link_names_a_registered_resource(self, other):
        class One(DataResource):
            name = "one"
            columns = {"id": str}
            links = {"id": "nowhere"}

        with pytest.raises(ImproperlyConfigured):
            other.register_data(One).check()

    def test_a_plain_name_is_a_link_by_the_field_itself(self, other):
        class One(DataResource):
            name = "one"
            columns = {"id": str}
            links = {"id": "one"}

        assert other.register_data(One).get_link("id") == RowLink("one")


class TestObjectsAsRows:
    def test_rows_may_be_objects(self, rf, admin_user):
        class Reading:
            def __init__(self, key, value):
                self.key = key
                self.value = value

        class Readings(DataResource):
            name = "readings"
            key = "key"
            columns = {"key": str, "value": float}

            def get_rows(self, request):
                return [Reading("a", 1.5), Reading("b", 2.5)]

        resource = Readings(GenericSite(name="data_test"))
        request = rf.get("/")
        request.user = admin_user
        row = resource.get_row(request, "b")

        assert row.value == 2.5
        assert resource.get_object_label(row) == "b"

        described = resource.describe(request, row, "value")

        assert described["type"] == "number"

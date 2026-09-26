"""Searches that ignore accents: generic.search.

The suite installs the app, as a project would, so every test here
runs the real folding - SQLite's Python function locally, PostgreSQL's
``unaccent`` when ``DATABASE_URL`` points at one. The last class turns
the app off to prove that a project without it sees no change.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

import generic.search
from example import external
from example.models import Customer
from generic.checks import check_search_rank
from generic.search import fold, normalize, text_lookup
from generic.search.operations import CreateSearchIndex, InstallUnaccent
from generic.search.ranking import can_rank, rank
from generic.sites import site

pytestmark = pytest.mark.django_db

CUSTOMERS = "/api/example/customer/"

#: Written the way PostgreSQL's unaccent rules write them.
FOLDED = {
    "Société Générale": "Societe Generale",
    "Élodie Lefèvre": "Elodie Lefevre",
    "Cœur de lion": "Coeur de lion",
    "Æsop": "AEsop",
    "Straße": "Strasse",
    "Søren Łukasz": "Soren Lukasz",
    "naïve façade": "naive facade",
    "plain ascii": "plain ascii",
}


@pytest.fixture
def customers(db):
    """Two companies whose names differ only by their accents."""
    return {
        "accented": Customer.objects.create(
            name="Société Générale",
            code="SG",
            city="Orléans",
        ),
        "plain": Customer.objects.create(
            name="Societe Anonyme", code="SA", city="Paris"
        ),
        "other": Customer.objects.create(
            name="Northwind", code="NW", city="Lyon"
        ),
    }


class Recorder:
    """A schema editor that only writes down what it is asked to run."""

    connection = connection

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql, params=()) -> None:
        self.statements.append(sql)


def names(response) -> list[str]:
    assert response.status_code == 200, response.content

    return sorted(row["name"] for row in response.json()["data"])


def table(client, **params):
    return client.get(CUSTOMERS, {"draw": 1, "length": 50, **params})


def contains(column: str, value: str) -> str:
    return json.dumps(
        {
            "match": "all",
            "conditions": [
                {"column": column, "operator": "contains", "value": value}
            ],
        }
    )


class TestFolding:
    @pytest.mark.parametrize("text, expected", FOLDED.items())
    def test_it_spells_letters_without_their_accents(self, text, expected):
        assert fold(text) == expected

    def test_nothing_stays_nothing(self):
        assert fold(None) is None

    def test_a_number_is_read_as_its_text(self):
        assert fold(12) == "12"

    def test_normalize_sets_case_aside_too(self):
        assert normalize("ÉTÉ") == "ete"

    @pytest.mark.parametrize("text, expected", FOLDED.items())
    def test_the_database_folds_as_python_does(self, text, expected):
        """SQLite through the registered function, PostgreSQL through
        unaccent: the same fixture, the same answers."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT generic_unaccent(%s)", [text])
            folded = cursor.fetchone()[0]

        assert folded == expected

    def test_the_lookup_goes_through_the_transform(self):
        assert text_lookup("title") == "title__unaccented__icontains"
        assert (
            text_lookup("title", "istartswith")
            == "title__unaccented__istartswith"
        )


class TestTheOrm:
    def test_a_plain_search_finds_the_accented_name(self, customers):
        found = Customer.objects.filter(**{text_lookup("name"): "societe"})

        assert {customer.code for customer in found} == {"SG", "SA"}

    def test_an_accented_search_finds_the_plain_name(self, customers):
        found = Customer.objects.filter(**{text_lookup("name"): "SOCIÉTÉ"})

        assert {customer.code for customer in found} == {"SG", "SA"}

    def test_like_wildcards_in_the_term_stay_literal(self, customers):
        found = Customer.objects.filter(**{text_lookup("name"): "%"})

        assert not found.exists()

    def test_a_search_on_a_number_still_works(self, support_desk):
        from example.models import Ticket

        found = Ticket.objects.filter(**{text_lookup("estimated_hours"): "2"})

        assert [ticket.reference for ticket in found] == ["SD-1"]


class TestEverySearch:
    """Each place the framework matches text, one test each."""

    def test_the_table_search(self, admin_client, customers):
        response = table(admin_client, **{"search[value]": "societe"})

        assert names(response) == [
            "Societe Anonyme",
            "Société Générale",
        ]

    def test_a_negated_search_term_leaves_accented_rows_out(
        self, admin_client, customers
    ):
        response = table(admin_client, **{"search[value]": "-société"})

        assert names(response) == ["Northwind"]

    def test_a_column_filter(self, admin_client, customers):
        response = table(admin_client, filters=contains("city", "orleans"))

        assert names(response) == ["Société Générale"]

    def test_the_filter_editors_value_search(self, admin_client, customers):
        response = admin_client.get(
            f"{CUSTOMERS}facets/", {"column": "city", "q": "orleans"}
        )

        assert response.status_code == 200, response.content
        assert [entry["value"] for entry in response.json()["values"]] == [
            "Orléans"
        ]

    def test_the_resource_autocomplete(self, admin_client, customers):
        response = admin_client.get(
            f"{CUSTOMERS}autocomplete/", {"q": "generale"}
        )

        assert [row["text"] for row in response.json()["results"]] == [
            "Société Générale"
        ]

    def test_the_command_palette(self, admin_client, customers):
        response = admin_client.get("/api/search/", {"q": "generale"})
        labels = [
            item["label"]
            for group in response.json()["groups"]
            for item in group["items"]
        ]

        assert "Société Générale" in labels

    def test_the_classic_list_view(self, auth_client, library):
        from tests.testapp.models import Book

        Book.objects.filter(title="Emma").update(title="Émma")
        response = auth_client.get("/books/", {"q": "emma"})

        assert [row.instance.title for row in response.context["table"]] == [
            "Émma"
        ]

    def test_the_wiki_search(self, rf, user):
        from generic.wiki.integration import search_pages
        from generic.wiki.models import WikiPage

        WikiPage.objects.create(title="Réglement intérieur", slug="reglement")
        request = rf.get("/")
        request.user = user

        groups = search_pages(request, "reglement")

        assert [item["label"] for item in groups[0]["items"]] == [
            "Réglement intérieur"
        ]


class TestRowsThatAreNotInTheDatabase:
    """A DataResource is searched in Python, by the same rules."""

    @pytest.fixture(autouse=True)
    def renamed_service(self):
        rows = external.fetch_services()
        rows[0] = {**rows[0], "name": "Messagerie Été"}
        cache.set(external.CACHE_KEY, rows)

        yield

        cache.delete(external.CACHE_KEY)

    def rows(self, client, **params):
        response = client.get(
            "/api/data/services/", {"draw": 1, "length": 100, **params}
        )

        assert response.status_code == 200, response.content

        return [row["name"] for row in response.json()["data"]]

    def test_the_search_box(self, admin_client):
        assert self.rows(admin_client, **{"search[value]": "ete"}) == [
            "Messagerie Été"
        ]

    def test_a_column_filter(self, admin_client):
        found = self.rows(
            admin_client, filters=contains("name", "messagerie ete")
        )

        assert found == ["Messagerie Été"]


class TestRanking:
    def test_without_postgresql_the_order_is_kept(self, customers):
        queryset = Customer.objects.order_by("code")

        if can_rank(queryset):
            pytest.skip("ranks on PostgreSQL: covered below")

        assert rank(queryset, ("name",), "societe") is queryset

    def test_an_empty_term_changes_nothing(self, customers):
        queryset = Customer.objects.all()

        assert rank(queryset, ("name",), "  ") is queryset

    @pytest.mark.skipif(
        connection.vendor != "postgresql", reason="pg_trgm is PostgreSQL's"
    )
    def test_the_closest_match_comes_first(self, customers):
        Customer.objects.create(name="Generali", code="GE")
        queryset = Customer.objects.order_by("code")

        ranked = rank(queryset, ("name", "city"), "generale")

        assert ranked[0].code == "SG"

    @pytest.mark.skipif(
        connection.vendor != "postgresql", reason="pg_trgm is PostgreSQL's"
    )
    def test_the_autocomplete_ranks_when_asked(
        self, admin_client, customers, monkeypatch
    ):
        resource = site.get_resource(Customer)
        monkeypatch.setattr(resource, "search_rank", True)
        Customer.objects.create(name="Aaa Societe Lointaine", code="AA")

        response = admin_client.get(
            f"{CUSTOMERS}autocomplete/", {"q": "societe generale"}
        )

        texts = [row["text"] for row in response.json()["results"]]

        assert texts[0] == "Société Générale"


class TestTheSearchIndex:
    def test_it_is_nothing_outside_postgresql(self):
        if connection.vendor == "postgresql":
            pytest.skip("PostgreSQL builds it: covered below")

        editor = Recorder()

        CreateSearchIndex("customer", ("name",), name="x").database_forwards(
            "example", editor, None, None
        )
        InstallUnaccent().database_forwards(
            "generic_search", editor, None, None
        )

        assert editor.statements == []

    def test_it_deconstructs_for_a_migration_file(self):
        operation = CreateSearchIndex(
            "customer", ("name", "city"), name="customer_search"
        )

        assert operation.deconstruct() == (
            "CreateSearchIndex",
            ["customer", ("name", "city")],
            {"name": "customer_search"},
        )
        assert operation.index_names() == [
            "customer_search_0",
            "customer_search_1",
        ]

    @pytest.mark.skipif(
        connection.vendor != "postgresql", reason="a GIN index"
    )
    def test_a_table_search_uses_it(self, customers):
        """The expression indexed is the one a search compiles to."""
        with connection.cursor() as cursor:
            cursor.execute("SET enable_seqscan = off")
            sql, params = (
                Customer.objects.filter(**{text_lookup("name"): "societe"})
                .values("pk")
                .query.sql_with_params()
            )
            cursor.execute(f"EXPLAIN {sql}", params)
            plan = "\n".join(row[0] for row in cursor.fetchall())
            cursor.execute("SET enable_seqscan = on")

        assert "customer_search" in plan, plan


class TestTheCheck:
    def test_ranking_without_the_app_is_named(self, settings, monkeypatch):
        resource = site.get_resource(Customer)
        monkeypatch.setattr(resource, "search_rank", True)
        settings.INSTALLED_APPS = [
            app for app in settings.INSTALLED_APPS if app != "generic.search"
        ]

        warnings = check_search_rank()

        assert [warning.id for warning in warnings] == ["generic.W007"]

    def test_nothing_to_say_with_the_app(self, monkeypatch):
        resource = site.get_resource(Customer)
        monkeypatch.setattr(resource, "search_rank", True)

        assert check_search_rank() == []


class TestWithoutTheApp:
    """A project that did not install it sees what it always saw."""

    @pytest.fixture(autouse=True)
    def switched_off(self, monkeypatch):
        monkeypatch.setattr(generic.search, "is_enabled", lambda: False)

    def test_the_lookup_is_the_old_one(self):
        assert text_lookup("title") == "title__icontains"

    def test_python_only_sets_case_aside(self):
        assert normalize("Été") == "été"

    def test_a_plain_search_no_longer_finds_accents(
        self, admin_client, customers
    ):
        response = table(admin_client, **{"search[value]": "generale"})

        assert names(response) == []

    def test_no_query_names_the_function(self, admin_client, customers):
        with CaptureQueriesContext(connection) as queries:
            table(admin_client, **{"search[value]": "societe"})

        assert not any("generic_unaccent" in query["sql"] for query in queries)


@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL's")
def test_installing_twice_is_harmless():
    """What a second project sharing the database, or a re-run, does."""
    with connection.schema_editor() as editor:
        InstallUnaccent().database_forwards(
            "generic_search", editor, None, None
        )

    with connection.cursor() as cursor:
        cursor.execute("SELECT generic_unaccent(%s)", ["\u00e9t\u00e9"])

        assert cursor.fetchone()[0] == "ete"

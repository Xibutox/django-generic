"""Records side by side (generic.sites.compare).

The example compares tickets on their summary page's sections
(``compare_fields = True``) and articles on a few fields.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Ticket
from generic.sites import ModelResource, site
from generic.sites.compare import MAX_COMPARED, check

pytestmark = pytest.mark.django_db

URL = "/api/example/ticket/compare/"
PAGE = "/example/ticket/compare/"


def compare(client, *records, status=200) -> dict:
    ids = ",".join(str(getattr(record, "pk", record)) for record in records)
    response = client.get(URL, {"ids": ids})

    assert response.status_code == status, response.content

    return response.json()


def rows(answer: dict) -> dict:
    return {
        row["name"]: row
        for section in answer["sections"]
        for row in section["rows"]
    }


@pytest.fixture
def reader_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="reader")
    user.user_permissions.set(
        Permission.objects.filter(codename="view_ticket")
    )
    client.force_login(user)

    return client


class TestTheComparison:
    def test_a_column_per_record_in_the_order_named(
        self, admin_client, support_desk
    ):
        login, invoice = support_desk["login"], support_desk["invoice"]
        answer = compare(admin_client, invoice, login)

        assert [record["id"] for record in answer["records"]] == [
            str(invoice.pk),
            str(login.pk),
        ]
        assert answer["records"][0]["label"].startswith("SD-2")
        assert answer["records"][0]["url"] == f"/example/ticket/{invoice.pk}/"
        assert answer["missing"] == 0

    def test_the_summary_page_s_sections_and_fields(
        self, admin_client, support_desk
    ):
        answer = compare(
            admin_client, support_desk["login"], support_desk["invoice"]
        )

        assert [section["title"] for section in answer["sections"]] == [
            "",
            "Description",
            "Billing and outcome",
        ]
        assert "priority" in rows(answer)
        assert rows(answer)["priority"]["label"] == "Priority"

    def test_rows_that_differ_are_marked(self, admin_client, support_desk):
        login, export = support_desk["login"], support_desk["export"]
        compared = rows(compare(admin_client, login, export))

        # Both in the front office; one high, the other low.
        assert compared["team"]["same"] is True
        assert compared["priority"]["same"] is False
        # Drawn as the tags the resource colours them with.
        assert [
            value["items"][0]["label"]
            for value in compared["priority"]["values"]
        ] == ["High", "Low"]

    def test_each_value_is_typed_as_the_summary_page_types_it(
        self, admin_client, support_desk
    ):
        compared = rows(
            compare(
                admin_client, support_desk["login"], support_desk["export"]
            )
        )
        tags = compared["tags"]["values"]

        assert tags[0]["type"] == "tags"
        assert {item["label"] for item in tags[0]["items"]} == {
            "regression",
            "release",
        }
        assert tags[1]["empty"] is True
        assert compared["tags"]["same"] is False

    def test_another_resource_compares_the_fields_it_names(self, admin_client):
        from example.models import Article

        first = Article.objects.create(
            reference="A-1", name="Bolt", unit_cost="1.00"
        )
        second = Article.objects.create(
            reference="A-2", name="Nut", unit_cost="2.00"
        )
        response = admin_client.get(
            "/api/example/article/compare/",
            {"ids": f"{first.pk},{second.pk}"},
        )

        assert response.status_code == 200, response.content
        assert list(rows(response.json())) == [
            "kind",
            "unit",
            "unit_cost",
            "family",
            "component_count",
        ]


class TestWhatItIsAskedFor:
    def test_one_record_is_not_a_comparison(self, admin_client, support_desk):
        compare(admin_client, support_desk["login"], status=400)

    def test_too_many_are_refused(self, admin_client, support_desk):
        compare(admin_client, *range(1, MAX_COMPARED + 2), status=400)

    def test_the_same_record_twice_counts_once(
        self, admin_client, support_desk
    ):
        login = support_desk["login"]

        compare(admin_client, login, login, status=400)

    def test_records_not_there_are_left_out_and_counted(
        self, admin_client, support_desk
    ):
        login, invoice = support_desk["login"], support_desk["invoice"]
        answer = compare(admin_client, login, invoice, 999999, "abc")

        assert len(answer["records"]) == 2
        assert answer["missing"] == 2

    def test_records_the_reader_may_not_see_are_left_out(
        self, admin_client, support_desk, monkeypatch
    ):
        resource = site.get_resource(Ticket)
        hidden = support_desk["invoice"]
        allowed = resource.has_view_permission
        monkeypatch.setattr(
            resource,
            "has_view_permission",
            lambda request, obj=None: allowed(request, obj)
            and getattr(obj, "pk", None) != hidden.pk,
        )
        answer = compare(
            admin_client,
            support_desk["login"],
            hidden,
            support_desk["export"],
        )

        assert str(hidden.pk) not in [r["id"] for r in answer["records"]]
        assert answer["missing"] == 1

    def test_refused_without_the_view_permission(
        self, client, django_user_model, support_desk
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))
        response = client.get(URL, {"ids": "1,2"})

        assert response.status_code == 403

    def test_a_reader_compares_too(self, reader_client, support_desk):
        answer = compare(
            reader_client, support_desk["login"], support_desk["invoice"]
        )

        assert len(answer["records"]) == 2

    def test_a_resource_without_it_answers_not_found(self, admin_client):
        response = admin_client.get(
            "/api/example/team/compare/", {"ids": "1,2"}
        )

        assert response.status_code == 404


class TestThePageAndTheTable:
    def test_the_page_is_drawn(self, admin_client, support_desk):
        response = admin_client.get(PAGE, {"ids": "1,2"})

        assert response.status_code == 200
        assert b'class="generic-compare"' in response.content
        assert b"compare-config" in response.content

    def test_the_list_offers_it_in_the_selection_bar(
        self, admin_client, rf, admin_user
    ):
        request = rf.get("/")
        request.user = admin_user
        options = site.get_resource(Ticket).get_compare_options(request)

        assert options["url"] == PAGE
        assert options["label"] == "Compare the selected tickets"
        assert options["max"] == MAX_COMPARED

    def test_no_button_on_the_list(self, admin_client):
        response = admin_client.get("/example/ticket/")

        assert b'href="/example/ticket/compare/"' not in response.content


class TestCheckedWhereItIsWritten:
    @pytest.mark.parametrize(
        "declared, message",
        [
            ("priority", "not one string"),
            (("nope",), "neither a field"),
        ],
    )
    def test_a_declaration_it_cannot_follow(self, declared, message):
        class Tickets(ModelResource):
            compare_fields = declared

        with pytest.raises(ImproperlyConfigured, match=message):
            check(Tickets(Ticket, site))

    def test_nothing_declared_compares_nothing(self):
        class Tickets(ModelResource):
            pass

        assert check(Tickets(Ticket, site)) == []

"""The endpoint behind each resource, and the pages drawn from it."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import Permission

from example.models import Agent, Tag, Team, Ticket, TicketComment
from generic.sites import GenericSite, ModelResource, site
from tests.factories import UserFactory

TICKETS = "/api/example/ticket/"
TEAMS = "/api/example/team/"

pytestmark = pytest.mark.django_db


def references(response) -> list[str]:
    return sorted(row["reference"] for row in response.json()["data"])


def user_with(*codenames: str):
    user = UserFactory(username="limited")
    user.user_permissions.set(
        Permission.objects.filter(
            content_type__app_label="example",
            codename__in=codenames,
        )
    )

    return user


class TestTableSerializer:
    @pytest.mark.parametrize("model", [Ticket, Team, Agent, Tag])
    def test_every_example_resource_describes_its_columns(self, model):
        serializer = site.get_resource(model).get_table_serializer_class()

        assert serializer.get_datatable_columns()

    def test_a_column_named_after_its_field_needs_no_source(self):
        # DRF refuses ``source`` when it repeats the field name, which
        # is what a plain field, a foreign key and a many-to-many are.
        serializer = site.get_resource(Ticket).get_table_serializer_class()
        fields = serializer().fields

        assert fields["reference"].source == "reference"
        assert fields["team"].source == "team"
        assert fields["tags"].source == "tags"

    def test_a_path_through_a_relation_reads_through_it(self):
        probe = GenericSite(name="probe")
        probe.register(
            Agent,
            ModelResource,
            realtime=False,
            list_display=("name", "team__code"),
        )
        serializer = probe.get_resource(Agent).get_table_serializer_class()

        assert serializer().fields["team__code"].source == "team.code"


class TestList:
    def test_rows_follow_the_datatables_protocol(
        self,
        worker_client,
        support_desk,
    ):
        response = worker_client.get(
            TICKETS,
            {"draw": 3, "start": 0, "length": 2},
        )
        body = response.json()

        assert response.status_code == 200
        assert body["draw"] == 3
        assert body["recordsTotal"] == 3
        assert body["recordsFiltered"] == 3
        assert len(body["data"]) == 2
        assert {"_pk", "reference", "team", "tags", "comment_count"} <= set(
            body["data"][0]
        )

    def test_relations_are_shown_by_their_label(
        self,
        worker_client,
        support_desk,
    ):
        response = worker_client.get(TICKETS, {"draw": 1, "length": 10})
        row = next(
            row
            for row in response.json()["data"]
            if row["reference"] == "SD-1"
        )

        assert row["_pk"] == support_desk["login"].pk
        assert row["team"] == "Front office"
        assert row["assignee"] == "Camille Rousseau"
        # Declared in tag_fields: each tag with its key, for its link.
        assert row["tags"] == [
            {"label": "regression", "id": support_desk["regression"].pk},
            {"label": "release", "id": support_desk["release"].pk},
        ]
        assert row["comment_count"] == 2

    def test_the_search_box_reads_every_word(
        self, worker_client, support_desk
    ):
        response = worker_client.get(
            TICKETS,
            {"draw": 1, "length": 10, "search[value]": "invoice !blank"},
        )

        assert references(response) == ["SD-3"]

    def test_viewing_needs_the_view_permission(
        self, auth_client, support_desk
    ):
        assert auth_client.get(TICKETS).status_code == 403

    def test_an_anonymous_user_is_refused(self, client):
        assert client.get(TICKETS).status_code in (401, 403)


class TestRecord:
    def test_a_record_comes_with_its_labels_and_inlines(
        self,
        worker_client,
        support_desk,
    ):
        login = support_desk["login"]
        body = worker_client.get(f"{TICKETS}{login.pk}/").json()

        assert body["_display"]["team"] == {
            str(support_desk["front"].pk): "Front office"
        }
        assert body["_display"]["tags"] == {
            str(support_desk["regression"].pk): "regression",
            str(support_desk["release"].pk): "release",
        }
        assert [row["body"] for row in body["_inlines"]["comments"]] == [
            "Reproduced on staging.",
            "Fixed in the next release.",
        ]
        assert body["age"] == "0 days"

    def test_a_record_is_created_with_its_inline_rows(
        self,
        worker_client,
        support_desk,
    ):
        response = worker_client.post(
            TICKETS,
            {
                "reference": "SD-9",
                "title": "Printer on fire",
                "team": support_desk["infra"].pk,
                "tags": [support_desk["billing"].pk],
                "_inlines": {
                    "comments": [
                        {"author": "Ada", "body": "Smoke seen.", "position": 1}
                    ]
                },
            },
            content_type="application/json",
        )

        assert response.status_code == 201, response.json()

        ticket = Ticket.objects.get(reference="SD-9")
        assert list(ticket.comments.values_list("body", flat=True)) == [
            "Smoke seen."
        ]
        assert list(ticket.tags.all()) == [support_desk["billing"]]

    def test_inline_rows_are_removed_and_changed_in_one_request(
        self,
        worker_client,
        support_desk,
    ):
        login = support_desk["login"]
        first, second = login.comments.order_by("position")

        # The second comment takes the first one's position, which the
        # unique constraint only allows once the first one is gone.
        response = worker_client.patch(
            f"{TICKETS}{login.pk}/",
            {
                "title": "Login fails after a reset",
                "_inlines": {
                    "comments": [
                        {"id": first.pk, "_delete": True},
                        {
                            "id": second.pk,
                            "author": "Yanis",
                            "body": "Fixed.",
                            "position": 1,
                        },
                    ]
                },
            },
            content_type="application/json",
        )

        assert response.status_code == 200, response.json()
        assert list(login.comments.values_list("position", "body")) == [
            (1, "Fixed.")
        ]

    def test_an_invalid_inline_row_saves_nothing(
        self,
        worker_client,
        support_desk,
    ):
        login = support_desk["login"]

        response = worker_client.patch(
            f"{TICKETS}{login.pk}/",
            {
                "title": "Changed",
                "_inlines": {
                    "comments": [
                        {"author": "", "body": "No author.", "position": 9}
                    ]
                },
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "_inlines" in response.json()

        login.refresh_from_db()
        assert login.title == "Login fails after password reset"
        assert login.comments.count() == 2

    def test_changing_needs_the_change_permission(
        self,
        worker_client,
        support_desk,
    ):
        response = worker_client.patch(
            f"{TEAMS}{support_desk['front'].pk}/",
            {"name": "Renamed"},
            content_type="application/json",
        )

        assert response.status_code == 403

    def test_a_protected_record_is_refused_with_the_reason(
        self,
        admin_client,
        support_desk,
    ):
        front = support_desk["front"]
        response = admin_client.delete(f"{TEAMS}{front.pk}/")

        assert response.status_code == 400
        assert response.json()["protected"]
        assert Team.objects.filter(pk=front.pk).exists()

    def test_deleting_takes_the_cascade_with_it(
        self,
        worker_client,
        support_desk,
    ):
        login = support_desk["login"]

        assert worker_client.delete(f"{TICKETS}{login.pk}/").status_code == 204
        assert not TicketComment.objects.filter(ticket_id=login.pk).exists()

    def test_the_deletion_preview_names_the_record(
        self,
        worker_client,
        support_desk,
    ):
        login = support_desk["login"]
        body = worker_client.get(f"{TICKETS}{login.pk}/deletion-preview/")

        assert body.json()["canDelete"] is True
        assert body.json()["object"]["label"] == (
            "SD-1 - Login fails after password reset"
        )


class TestFormSchema:
    @staticmethod
    def schema(client) -> dict:
        return client.get(f"{TICKETS}form-schema/").json()

    @staticmethod
    def field(schema: dict, name: str) -> dict:
        return next(item for item in schema["fields"] if item["name"] == name)

    def test_sections_come_from_the_fieldsets(self, worker_client):
        sections = {
            section["name"]: section
            for section in self.schema(worker_client)["sections"]
        }

        assert sections["assignment"]["description"] == (
            "Who is on it, and by when."
        )
        assert sections["billing-and-outcome"]["collapsed"] is True
        assert sections["history"]["tab"] is True

    def test_a_searchable_relation_is_fed_by_its_autocomplete(
        self,
        worker_client,
    ):
        team = self.field(self.schema(worker_client), "team")

        assert team["autocompleteUrl"] == "/api/example/team/autocomplete/"

    def test_the_popup_links_follow_the_permissions(
        self,
        worker_client,
        admin_client,
    ):
        seen_by_worker = self.field(self.schema(worker_client), "team")
        seen_by_admin = self.field(self.schema(admin_client), "team")

        assert not seen_by_worker.get("relatedCreateUrl")
        assert not seen_by_worker.get("relatedUpdateUrl")
        assert seen_by_admin["relatedCreateUrl"] == "/example/team/add/"
        assert seen_by_admin["relatedUpdateUrl"] == (
            "/example/team/{id}/change/"
        )

    def test_a_computed_value_is_read_only(self, worker_client):
        assert self.field(self.schema(worker_client), "age")["readOnly"]

    def test_a_row_inside_fields_shares_the_width(self, admin_client, db):
        # fields = (..., ("spent_on", "hours"), ...), the admin's way of
        # putting two fields on a line, used to fail with a 500.
        response = admin_client.get("/api/example/timeentry/form-schema/")
        fields = {item["name"]: item for item in response.json()["fields"]}

        assert response.status_code == 200
        assert fields["spent_on"]["width"] == fields["hours"]["width"] == 6
        assert fields["ticket"]["width"] == 12

    def test_the_record_key_is_carried_but_hidden(self, worker_client):
        schema = self.schema(worker_client)
        inline_key = next(
            field
            for field in schema["inlines"][0]["fields"]
            if field["name"] == "id"
        )

        assert self.field(schema, "id")["hidden"] is True
        assert inline_key["hidden"] is True
        assert "hidden" not in self.field(schema, "reference")

    def test_the_inlines_are_described(self, worker_client):
        inline = self.schema(worker_client)["inlines"][0]

        assert inline["name"] == "comments"
        assert inline["presentation"] == "tabular"
        assert inline["maxRows"] == 20
        assert inline["canAdd"] and inline["canDelete"]

    def test_an_inline_answers_to_its_own_permissions(self, client):
        client.force_login(
            user_with("view_ticket", "change_ticket", "view_ticketcomment")
        )
        inline = self.schema(client)["inlines"][0]

        assert not inline["canAdd"]
        assert not inline["canChange"]
        assert not inline["canDelete"]


class TestAutocomplete:
    def test_results_are_searched_and_labelled(
        self,
        worker_client,
        support_desk,
    ):
        body = worker_client.get(f"{TEAMS}autocomplete/", {"q": "front"})

        assert body.json() == {
            "results": [
                {"id": support_desk["front"].pk, "text": "Front office"}
            ],
            "pagination": {"more": False},
        }

    def test_values_already_held_are_labelled_by_key(
        self,
        worker_client,
        support_desk,
    ):
        keys = f"{support_desk['front'].pk},{support_desk['infra'].pk}"
        body = worker_client.get(f"{TEAMS}autocomplete/", {"ids": keys})

        assert sorted(item["text"] for item in body.json()["results"]) == [
            "Front office",
            "Infrastructure",
        ]

    def test_results_come_in_pages(
        self, worker_client, support_desk, settings
    ):
        settings.GENERIC = {
            "AUTOCOMPLETE_PAGE_SIZE": 2,
            "AUTOCOMPLETE_MIN_INPUT_LENGTH": 0,
        }
        url = f"{TEAMS}autocomplete/"

        first = worker_client.get(url, {"q": ""}).json()
        second = worker_client.get(url, {"q": "", "page": 2}).json()

        assert [item["text"] for item in first["results"]] == [
            "Front office",
            "Infrastructure",
        ]
        assert first["pagination"]["more"] is True
        assert [item["text"] for item in second["results"]] == ["Spare"]
        assert second["pagination"]["more"] is False


class TestBulkActions:
    URL = f"{TICKETS}actions/"

    def run(self, client, payload: dict, query: str = ""):
        return client.post(
            f"{self.URL}{query}",
            payload,
            content_type="application/json",
        )

    def test_an_action_runs_on_the_ticked_rows(
        self,
        worker_client,
        support_desk,
    ):
        response = self.run(
            worker_client,
            {
                # A transition of the ticket's state, as a bulk action.
                "action": "transition:close",
                "ids": [support_desk["login"].pk, support_desk["invoice"].pk],
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "message": (
                "Close: 2 done, 0 skipped (not in a state that allows it, "
                "or not allowed)."
            ),
            "level": "success",
            "count": 2,
        }
        assert not Ticket.objects.exclude(status=Ticket.Status.CLOSED).exists()

    def test_all_means_every_row_the_table_shows(
        self,
        worker_client,
        support_desk,
    ):
        response = self.run(
            worker_client,
            {"action": "mark_billable", "all": True},
            query="?search%5Bvalue%5D=invoice",
        )

        assert response.json()["count"] == 2
        assert sorted(
            Ticket.objects.filter(is_billable=True).values_list(
                "reference", flat=True
            )
        ) == ["SD-1", "SD-2", "SD-3"]

    def test_an_unknown_action_is_refused(self, worker_client, support_desk):
        response = self.run(
            worker_client,
            {"action": "launch_rockets", "ids": [support_desk["login"].pk]},
        )

        assert response.status_code == 400

    def test_deleting_needs_the_delete_permission(self, client, support_desk):
        client.force_login(user_with("view_ticket", "change_ticket"))

        response = self.run(
            client,
            {"action": "delete_selected", "ids": [support_desk["login"].pk]},
        )

        assert response.status_code == 400
        assert Ticket.objects.filter(pk=support_desk["login"].pk).exists()

    def test_an_empty_selection_is_refused(self, worker_client, support_desk):
        response = self.run(worker_client, {"action": "close", "ids": []})

        assert response.status_code == 400


class TestPages:
    @pytest.mark.parametrize(
        "path",
        [
            "/example/ticket/",
            "/example/ticket/add/",
            "/example/team/",
            "/example/agent/",
            "/example/tag/",
        ],
    )
    def test_every_generated_page_renders(self, admin_client, path):
        assert admin_client.get(path).status_code == 200

    def test_the_list_page_carries_the_table_configuration(
        self,
        worker_client,
        support_desk,
    ):
        response = worker_client.get("/example/ticket/")
        config = json.dumps(response.context["table_config"], default=str)

        assert "/api/example/ticket/actions/" in config
        assert "resource.example.ticket" in config

    def test_the_change_page_carries_the_form_configuration(
        self,
        worker_client,
        support_desk,
    ):
        response = worker_client.get(
            f"/example/ticket/{support_desk['login'].pk}/change/"
        )

        assert response.status_code == 200
        assert b'id="resource-form-config"' in response.content

    def test_an_anonymous_user_is_sent_to_sign_in(self, client):
        response = client.get("/example/ticket/")

        assert response.status_code == 302
        assert response.url.startswith("/login/")

    def test_a_page_the_user_may_not_see_is_forbidden(self, auth_client):
        assert auth_client.get("/example/ticket/").status_code == 403

    def test_an_unknown_record_is_not_found(self, admin_client):
        assert admin_client.get("/example/ticket/999/change/").status_code == (
            404
        )

"""Several records changed at once (generic.sites.bulk_edit)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from rest_framework import serializers

from example.models import Ticket
from generic.history.models import HistoryEntry
from generic.sites import ModelResource
from generic.sites.bulk_edit import infer
from generic.sites.site import GenericSite
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/"
URL = f"{TICKETS}bulk-edit/"


def send(client, changes, commit=True, ids=None, query="", **selection):
    body = {"changes": changes, "commit": commit, **selection}

    if ids is not None:
        body["ids"] = [str(pk) for pk in ids]

    return client.post(f"{URL}{query}", body, content_type="application/json")


def answer(response) -> dict:
    assert response.status_code == 200, response.content

    return response.json()


def everyone(desk) -> list:
    return [desk["login"].pk, desk["invoice"].pk, desk["export"].pk]


def tags_of(ticket) -> set:
    return set(ticket.tags.values_list("name", flat=True))


class TestTheDialog:
    def test_it_offers_the_declared_fields_with_what_may_be_done(
        self, admin_client, support_desk
    ):
        described = answer(admin_client.get(URL))
        modes = {
            field["name"]: [mode["value"] for mode in field["modes"]]
            for field in described["fields"]
        }

        assert set(modes) == {
            "team",
            "assignee",
            "customer",
            "priority",
            "tags",
            "is_billable",
            "due_on",
        }
        # Required: only set. Optional: cleared too. Many: added to,
        # removed from.
        assert modes["team"] == ["set"]
        assert modes["assignee"] == ["set", "clear"]
        assert modes["tags"] == ["add", "remove", "set", "clear"]
        assert modes["is_billable"] == ["set"]

    def test_each_field_is_described_as_the_form_describes_it(
        self, admin_client, support_desk
    ):
        fields = {
            field["name"]: field
            for field in answer(admin_client.get(URL))["fields"]
        }

        assert fields["tags"]["type"] == "multiselect"
        assert fields["tags"]["autocompleteUrl"] == (
            "/api/example/tag/autocomplete/"
        )
        assert [
            choice["value"] for choice in fields["priority"]["choices"]
        ] == [
            "low",
            "normal",
            "high",
            "urgent",
        ]
        # Nothing is required: the reader picks the field first.
        assert not any(field["required"] for field in fields.values())

    def test_the_list_offers_it_to_who_may_change(
        self, admin_client, support_desk
    ):
        page = admin_client.get("/example/ticket/")
        options = page.context["table_config"]["options"]

        assert options["bulkEdit"] == {
            "url": URL,
            "label": "Edit the selected tickets",
        }

    def test_a_reader_who_may_not_change_is_offered_nothing(
        self, client, support_desk
    ):
        from django.contrib.auth.models import Permission

        reader = UserFactory(username="reader")
        reader.user_permissions.set(
            Permission.objects.filter(codename="view_ticket")
        )
        client.force_login(reader)

        page = client.get("/example/ticket/")

        assert page.context["table_config"]["options"]["bulkEdit"] == {}
        assert client.get(URL).status_code == 403
        assert (
            send(
                client,
                {"priority": "low"},
                ids=everyone(support_desk),
            ).status_code
            == 403
        )

    def test_a_resource_declaring_nothing_offers_nothing(
        self, admin_client, support_desk
    ):
        page = admin_client.get("/example/tag/")

        assert page.context["table_config"]["options"]["bulkEdit"] == {}
        assert admin_client.get("/api/example/tag/bulk-edit/").status_code == (
            403
        )


class TestTheReview:
    def test_it_says_what_would_happen_and_writes_nothing(
        self, admin_client, support_desk
    ):
        reviewed = answer(
            send(
                admin_client,
                {"priority": {"mode": "set", "value": "urgent"}},
                commit=False,
                ids=everyone(support_desk),
            )
        )

        assert reviewed["committed"] is False
        assert reviewed["counts"] == {
            "selected": 3,
            "changed": 3,
            "unchanged": 0,
            "refused": 0,
            "invalid": 0,
        }
        assert reviewed["message"] == "3 tickets will change."
        assert not Ticket.objects.filter(priority="urgent").exists()
        assert not HistoryEntry.objects.filter(
            source__startswith="Bulk edit"
        ).exists()

    def test_records_already_holding_the_value_are_counted_apart(
        self, admin_client, support_desk
    ):
        reviewed = answer(
            send(
                admin_client,
                {"priority": {"mode": "set", "value": "high"}},
                commit=False,
                ids=everyone(support_desk),
            )
        )

        assert reviewed["counts"]["changed"] == 2
        assert reviewed["counts"]["unchanged"] == 1


class TestTheWrite:
    def test_the_selected_records_take_the_value(
        self, admin_client, support_desk
    ):
        login, invoice = support_desk["login"], support_desk["invoice"]

        written = answer(
            send(
                admin_client,
                {
                    "priority": {"mode": "set", "value": "urgent"},
                    "team": {"mode": "set", "value": support_desk["spare"].pk},
                },
                ids=[login.pk, invoice.pk],
            )
        )

        assert written["committed"] is True
        assert written["message"] == "2 tickets changed."
        assert written["level"] == "success"
        assert set(
            Ticket.objects.filter(priority="urgent").values_list(
                "reference", flat=True
            )
        ) == {"SD-1", "SD-2"}
        assert set(
            Ticket.objects.filter(team=support_desk["spare"]).values_list(
                "reference", flat=True
            )
        ) == {"SD-1", "SD-2"}
        assert Ticket.objects.get(reference="SD-3").priority == "low"

    def test_tags_are_added_to_each_records_own(
        self, admin_client, support_desk
    ):
        answer(
            send(
                admin_client,
                {
                    "tags": {
                        "mode": "add",
                        "value": [support_desk["billing"].pk],
                    }
                },
                ids=everyone(support_desk),
            )
        )

        assert tags_of(support_desk["login"]) == {
            "regression",
            "release",
            "billing",
        }
        assert tags_of(support_desk["invoice"]) == {"billing"}
        assert tags_of(support_desk["export"]) == {"billing"}

    def test_tags_are_removed_from_each_records_own(
        self, admin_client, support_desk
    ):
        answer(
            send(
                admin_client,
                {
                    "tags": {
                        "mode": "remove",
                        "value": [
                            support_desk["regression"].pk,
                            support_desk["billing"].pk,
                        ],
                    }
                },
                ids=everyone(support_desk),
            )
        )

        assert tags_of(support_desk["login"]) == {"release"}
        assert tags_of(support_desk["invoice"]) == set()

    def test_tags_are_replaced(self, admin_client, support_desk):
        answer(
            send(
                admin_client,
                {
                    "tags": {
                        "mode": "set",
                        "value": [support_desk["release"].pk],
                    }
                },
                ids=[support_desk["login"].pk, support_desk["invoice"].pk],
            )
        )

        assert tags_of(support_desk["login"]) == {"release"}
        assert tags_of(support_desk["invoice"]) == {"release"}

    def test_a_field_is_cleared(self, admin_client, support_desk):
        answer(
            send(
                admin_client,
                {"assignee": {"mode": "clear"}, "tags": {"mode": "clear"}},
                ids=everyone(support_desk),
            )
        )

        assert not Ticket.objects.filter(assignee__isnull=False).exists()
        assert not Ticket.tags.through.objects.exists()

    def test_all_means_every_row_the_table_shows(
        self, admin_client, support_desk
    ):
        answer(
            send(
                admin_client,
                {"is_billable": {"mode": "set", "value": True}},
                query="?search%5Bvalue%5D=invoice",
                all=True,
            )
        )

        # The search finds SD-2 and SD-3, the invoices; SD-1 was
        # billable already.
        assert set(
            Ticket.objects.filter(is_billable=True).values_list(
                "reference", flat=True
            )
        ) == {"SD-1", "SD-2", "SD-3"}

    def test_a_record_the_reader_cannot_see_is_not_selected(
        self, admin_client, support_desk
    ):
        written = answer(
            send(
                admin_client,
                {"priority": {"mode": "set", "value": "urgent"}},
                ids=[support_desk["login"].pk, 999999],
            )
        )

        assert written["counts"]["selected"] == 1


class TestWhatIsLeftAsItWas:
    def test_a_per_record_rule_leaves_the_record_out_and_names_it(
        self, admin_client, support_desk
    ):
        # The example: a closed ticket stays with its team.
        written = answer(
            send(
                admin_client,
                {"team": {"mode": "set", "value": support_desk["spare"].pk}},
                ids=everyone(support_desk),
            )
        )

        assert written["counts"]["changed"] == 2
        assert written["counts"]["refused"] == 1
        assert written["level"] == "warning"
        [problem] = written["problems"]
        assert problem["label"].startswith("SD-3")
        assert problem["messages"] == [
            "Not to be changed on this record: team."
        ]
        assert (
            problem["url"] == f"/example/ticket/{support_desk['export'].pk}/"
        )
        assert (
            Ticket.objects.get(reference="SD-3").team == support_desk["front"]
        )

    def test_a_record_the_reader_may_not_change_is_left_out(
        self, admin_client, support_desk, monkeypatch
    ):
        from generic.sites import site

        resource = site.get_resource(Ticket)
        monkeypatch.setattr(
            type(resource),
            "has_change_permission",
            lambda self, request, obj=None: obj is None
            or obj.reference != "SD-2",
        )

        written = answer(
            send(
                admin_client,
                {"priority": {"mode": "set", "value": "urgent"}},
                ids=everyone(support_desk),
            )
        )

        assert written["counts"]["refused"] == 1
        assert written["problems"][0]["messages"] == [
            "You may not change this record."
        ]
        assert Ticket.objects.get(reference="SD-2").priority == "normal"

    def test_what_the_form_refuses_is_refused(
        self, admin_client, support_desk
    ):
        written = answer(
            send(
                admin_client,
                {"priority": {"mode": "set", "value": "whenever"}},
                ids=[support_desk["login"].pk],
            )
        )

        assert written["counts"]["invalid"] == 1
        assert written["problems"][0]["messages"][0].startswith("Priority: ")
        assert Ticket.objects.get(reference="SD-1").priority == "high"

    def test_save_bulk_edit_may_refuse_a_record(
        self, admin_client, support_desk, monkeypatch
    ):
        from generic.sites import site

        resource = site.get_resource(Ticket)
        original = type(resource).save_bulk_edit

        def save_bulk_edit(self, request, serializer, obj):
            if obj.reference == "SD-1":
                raise serializers.ValidationError("Frozen by the auditors.")

            return original(self, request, serializer, obj)

        monkeypatch.setattr(type(resource), "save_bulk_edit", save_bulk_edit)

        written = answer(
            send(
                admin_client,
                {"priority": {"mode": "set", "value": "urgent"}},
                ids=everyone(support_desk),
            )
        )

        assert written["counts"]["changed"] == 2
        assert written["counts"]["invalid"] == 1
        assert written["problems"][0]["messages"] == [
            "Frozen by the auditors."
        ]
        assert Ticket.objects.get(reference="SD-1").priority == "high"


class TestRefusals:
    @pytest.mark.parametrize(
        "changes",
        [
            {},
            None,
            {"status": {"mode": "set", "value": "closed"}},
            {"reference": "SD-9"},
            {"team": {"mode": "clear"}},
            {"priority": {"mode": "add", "value": "low"}},
            {"tags": {"mode": "add", "value": []}},
            {"tags": {"mode": "set", "value": "billing"}},
        ],
    )
    def test_a_change_outside_the_declaration_is_a_400(
        self, admin_client, support_desk, changes
    ):
        response = send(admin_client, changes, ids=everyone(support_desk))

        assert response.status_code == 400

    def test_nothing_selected_is_a_400(self, admin_client, support_desk):
        response = send(admin_client, {"priority": "low"}, ids=[999999])

        assert response.status_code == 400

    @override_settings(GENERIC={"BULK_EDIT_MAX_ROWS": 2})
    def test_too_large_a_selection_is_refused(
        self, admin_client, support_desk
    ):
        response = send(
            admin_client,
            {"priority": {"mode": "set", "value": "low"}},
            ids=everyone(support_desk),
        )

        assert response.status_code == 400
        assert "Narrow the selection" in response.json()["detail"]
        assert Ticket.objects.filter(priority="low").count() == 1

    def test_the_trash_is_not_edited(self, admin_client, support_desk):
        response = admin_client.get(f"{URL}?_trash=1")

        assert response.status_code == 404


class TestWhatItLeaves:
    def test_one_version_per_record_says_who_and_how(
        self, admin_client, admin_user, support_desk
    ):
        answer(
            send(
                admin_client,
                {"priority": {"mode": "set", "value": "urgent"}},
                ids=everyone(support_desk),
            )
        )

        entries = HistoryEntry.objects.filter(source="Bulk edit: priority")

        assert entries.count() == 3
        assert {entry.user for entry in entries} == {admin_user}

    def test_one_live_event_for_the_lot(
        self, admin_client, support_desk, monkeypatch
    ):
        from generic.sites import realtime

        sent = []
        monkeypatch.setattr(
            realtime,
            "announce",
            lambda resource, change, pk=None: sent.append(
                (resource.label_lower, change)
            ),
        )

        answer(
            send(
                admin_client,
                {"priority": {"mode": "set", "value": "urgent"}},
                ids=everyone(support_desk),
            )
        )

        # The history's own entries are news of their own resource.
        assert [
            change for label, change in sent if label == "example.ticket"
        ] == ["bulk"]

    def test_the_answer_is_a_report_naming_what_was_left(
        self, admin_client, support_desk
    ):
        written = answer(
            send(
                admin_client,
                {"team": {"mode": "set", "value": support_desk["spare"].pk}},
                ids=everyone(support_desk),
            )
        )
        report = written["operation"]["report"]

        assert [node["title"] for node in report] == ["1 left as it was."]
        assert report[0]["children"][0]["title"].startswith("SD-3")


class TestDeclarations:
    def declare(self, *names, **attributes):
        from example.models import Ticket as Model

        resource = type(
            "TicketResource",
            (ModelResource,),
            {"bulk_edit_fields": names, **attributes},
        )

        return resource(Model, GenericSite(name="bulk-edit-test"))

    @pytest.mark.parametrize(
        "name, message",
        [
            ("nope", "not a field"),
            ("reference", "unique"),
            ("attachment", "file"),
            ("comments", "does not hold itself"),
        ],
    )
    def test_a_field_no_selection_can_share_is_refused(self, name, message):
        with pytest.raises(ImproperlyConfigured, match=message):
            self.declare(name).get_bulk_edit_fields()

    def test_a_state_field_is_refused(self):
        resource = self.declare("status", transitions=("status",))

        with pytest.raises(ImproperlyConfigured, match="transitions"):
            resource.get_bulk_edit_fields()

    def test_a_read_only_field_is_refused(self):
        resource = self.declare("priority", readonly_fields=("priority",))

        with pytest.raises(ImproperlyConfigured, match="read only"):
            resource.get_bulk_edit_fields()

    def test_a_field_off_the_form_is_refused(self):
        resource = self.declare("priority", fields=("title",))

        with pytest.raises(ImproperlyConfigured, match="not on its form"):
            resource.get_bulk_edit_fields()

    def test_it_is_checked_at_registration(self):
        from example.models import Ticket as Model

        resource = type(
            "TicketResource", (ModelResource,), {"bulk_edit_fields": ("x",)}
        )

        with pytest.raises(ImproperlyConfigured, match="'x'"):
            GenericSite(name="bulk-edit-test").register(Model, resource)


class TestWorkedOut:
    def test_what_sorts_a_record_is_offered_never_what_names_it(self):
        from example.models import Ticket as Model

        chosen = infer(
            Model,
            (
                "reference",
                "title",
                "description",
                "attachment",
                "team",
                "tags",
                "priority",
                "is_billable",
                "estimated_hours",
                "due_on",
            ),
        )

        assert chosen == ("team", "tags", "priority", "is_billable", "due_on")

    def test_auto_offers_it(self, admin_client, workshop):
        page = admin_client.get("/example/equipment/")
        options = page.context["table_config"]["options"]

        assert (
            options["bulkEdit"]["url"] == "/api/example/equipment/bulk-edit/"
        )

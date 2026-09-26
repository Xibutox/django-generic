"""Imports: a spreadsheet read back into records.

On the example's tickets (created and updated by reference) and
customers (by code). Files are built in the tests, so every cell a test
reads is written above it.
"""

from __future__ import annotations

import datetime
import io
import json
from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from openpyxl import Workbook, load_workbook

from example.models import Customer, Ticket
from generic.history.models import HistoryEntry
from generic.sites import Import, ModelResource
from generic.sites.imports import check_import, read_file
from generic.sites.site import GenericSite

pytestmark = pytest.mark.django_db

TICKETS = "/api/example/ticket/import/"
CUSTOMERS = "/api/example/customer/import/"


def csv_file(*lines: str, name: str = "tickets.csv") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, "\n".join(lines).encode("utf-8"))


def xlsx_file(rows, name: str = "tickets.xlsx") -> SimpleUploadedFile:
    workbook = Workbook()
    sheet = workbook.active

    for row in rows:
        sheet.append(row)

    stream = io.BytesIO()
    workbook.save(stream)

    return SimpleUploadedFile(name, stream.getvalue())


def send(
    client, upload, url=TICKETS, commit=False, mapping=None, language=None
):
    data = {"file": upload, "commit": "true" if commit else "false"}
    headers = {"HTTP_ACCEPT_LANGUAGE": language} if language else {}

    if mapping is not None:
        data["mapping"] = json.dumps(mapping)

    return client.post(url, data, **headers)


def answer(response) -> dict:
    assert response.status_code == 200, response.content

    return response.json()


class TestCreatingAndUpdating:
    def test_a_new_reference_creates_a_ticket(
        self, admin_client, support_desk
    ):
        result = answer(
            send(
                admin_client,
                csv_file(
                    "Reference;Title;Team;Priority;Status",
                    "SD-10;Printer on fire;Front office;High;Open",
                ),
                commit=True,
            )
        )

        assert result["committed"] is True
        assert result["counts"] == {
            "create": 1,
            "update": 0,
            "unchanged": 0,
            "error": 0,
        }
        ticket = Ticket.objects.get(reference="SD-10")
        assert ticket.title == "Printer on fire"
        assert ticket.team == support_desk["front"]
        assert ticket.priority == Ticket.Priority.HIGH

    def test_a_known_reference_updates_that_ticket(
        self, admin_client, support_desk
    ):
        answer(
            send(
                admin_client,
                csv_file("Reference;Title", "SD-1;Login fixed at last"),
                commit=True,
            )
        )

        support_desk["login"].refresh_from_db()
        assert support_desk["login"].title == "Login fixed at last"

    def test_an_empty_cell_keeps_the_stored_value(
        self, admin_client, support_desk
    ):
        answer(
            send(
                admin_client,
                csv_file("Reference;Title;Priority", "SD-1;;low"),
                commit=True,
            )
        )

        support_desk["login"].refresh_from_db()
        assert (
            support_desk["login"].title == "Login fails after password reset"
        )
        assert support_desk["login"].priority == Ticket.Priority.LOW

    def test_an_export_imports_back_unchanged(
        self, admin_client, support_desk
    ):
        exported = admin_client.get("/api/example/ticket/export/")
        content = b"".join(exported.streaming_content)

        result = answer(
            send(admin_client, SimpleUploadedFile("tickets.xlsx", content))
        )

        assert result["counts"] == {
            "create": 0,
            "update": 0,
            "unchanged": 3,
            "error": 0,
        }
        # Columns the export has and a file cannot write: named, skipped.
        assert "Comments" in result["unmatched"]

    def test_a_csv_export_imports_back_unchanged(
        self, admin_client, support_desk
    ):
        exported = admin_client.get("/api/example/ticket/export-csv/")
        content = b"".join(exported.streaming_content)

        result = answer(
            send(admin_client, SimpleUploadedFile("tickets.csv", content))
        )

        assert result["counts"]["unchanged"] == 3, result["errors"]

    def test_update_only_refuses_an_unknown_key(
        self, admin_client, support_desk, monkeypatch
    ):
        from generic.sites import site

        resource = site.get_resource(Ticket)
        monkeypatch.setattr(
            resource,
            "imports",
            Import(
                fields=("reference", "title"), key="reference", mode="update"
            ),
        )

        result = answer(
            send(admin_client, csv_file("Reference;Title", "SD-99;Nope"))
        )

        assert result["errors"][0]["column"] == "reference"


class TestReadingCells:
    def test_choices_by_label_in_another_language(
        self, admin_client, support_desk
    ):
        """A French file, read by an English session."""
        result = answer(
            send(
                admin_client,
                csv_file("Reference;Priority", "SD-1;Urgente"),
                commit=True,
            )
        )

        assert result["committed"], result["errors"]
        support_desk["login"].refresh_from_db()
        assert support_desk["login"].priority == Ticket.Priority.URGENT

    @pytest.mark.parametrize(
        "cell, expected",
        [
            ("oui", True),
            ("Yes", True),
            ("x", True),
            ("non", False),
            ("0", False),
        ],
    )
    def test_booleans(self, admin_client, support_desk, cell, expected):
        answer(
            send(
                admin_client,
                csv_file("Reference;Billable", f"SD-2;{cell}"),
                commit=True,
            )
        )

        support_desk["invoice"].refresh_from_db()
        assert support_desk["invoice"].is_billable is expected

    def test_a_french_date_and_decimal(self, admin_client, support_desk):
        result = answer(
            send(
                admin_client,
                csv_file(
                    "Référence;Due on;Estimated hours",
                    "SD-2;31/12/2026;3,5",
                ),
                commit=True,
                language="fr",
            )
        )

        assert result["committed"], result["errors"]
        support_desk["invoice"].refresh_from_db()
        assert support_desk["invoice"].due_on == datetime.date(2026, 12, 31)
        assert support_desk["invoice"].estimated_hours == Decimal("3.50")

    def test_excel_values_keep_their_type(self, admin_client, support_desk):
        result = answer(
            send(
                admin_client,
                xlsx_file(
                    [
                        ["Reference", "Due on", "Estimated hours"],
                        ["SD-2", datetime.date(2027, 1, 15), 4.25],
                    ]
                ),
                commit=True,
            )
        )

        assert result["committed"], result["errors"]
        support_desk["invoice"].refresh_from_db()
        assert support_desk["invoice"].due_on == datetime.date(2027, 1, 15)
        assert support_desk["invoice"].estimated_hours == Decimal("4.25")

    def test_a_formula_imports_its_value(self, admin_client, support_desk):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Reference", "Title"])
        sheet.append(["SD-2", '=CONCATENATE("Invoice", " PDF")'])
        stream = io.BytesIO()
        workbook.save(stream)
        # openpyxl writes no cached values: the file is re-read the way
        # Excel would have saved it, with the formula's result cached.
        workbook = load_workbook(io.BytesIO(stream.getvalue()))
        workbook.active["B2"].value = "Invoice PDF"
        stream = io.BytesIO()
        workbook.save(stream)

        result = answer(
            send(
                admin_client,
                SimpleUploadedFile("t.xlsx", stream.getvalue()),
                commit=True,
            )
        )

        assert result["committed"], result["errors"]
        support_desk["invoice"].refresh_from_db()
        assert support_desk["invoice"].title == "Invoice PDF"

    def test_relations_and_tags_by_label(self, admin_client, support_desk):
        result = answer(
            send(
                admin_client,
                csv_file(
                    "Reference;Team;Assignee;Tags",
                    'SD-3;infrastructure;YANIS BERTRAND;"billing, release"',
                ),
                commit=True,
            )
        )

        assert result["committed"], result["errors"]
        ticket = support_desk["export"]
        ticket.refresh_from_db()
        assert ticket.team == support_desk["infra"]
        assert ticket.assignee == support_desk["yanis"]
        assert {tag.name for tag in ticket.tags.all()} == {
            "billing",
            "release",
        }

    def test_an_unknown_label_names_the_value(
        self, admin_client, support_desk
    ):
        result = answer(
            send(admin_client, csv_file("Reference;Team", "SD-1;Nowhere"))
        )

        assert result["errors"] == [
            {
                "row": 2,
                "column": "team",
                "message": "No team is called Nowhere.",
            }
        ]

    def test_an_ambiguous_label_is_refused(self, admin_client, support_desk):
        from example.models import Agent

        Agent.objects.create(
            name="Yanis Bertrand",
            email="other@example.test",
            team=support_desk["front"],
        )

        result = answer(
            send(
                admin_client,
                csv_file("Reference;Assignee", "SD-1;Yanis Bertrand"),
            )
        )

        assert "Several" in result["errors"][0]["message"]

    def test_a_record_the_importer_may_not_see_is_not_found(
        self, worker_client, support_desk
    ):
        """The worker may not view customers: naming one finds nothing."""
        Customer.objects.create(name="Hidden SA", code="HID")

        result = answer(
            send(
                worker_client, csv_file("Reference;Customer", "SD-1;Hidden SA")
            )
        )

        assert result["errors"][0]["column"] == "customer"


class TestAllOrNothing:
    def test_one_bad_row_keeps_every_row_out(self, admin_client, support_desk):
        result = answer(
            send(
                admin_client,
                csv_file(
                    "Reference;Title;Team",
                    "SD-20;Good;Front office",
                    "SD-21;Bad;Nowhere",
                ),
                commit=True,
            )
        )

        assert result["committed"] is False
        assert result["counts"]["create"] == 1
        assert not Ticket.objects.filter(reference="SD-20").exists()

    def test_the_preview_writes_nothing(self, admin_client, support_desk):
        result = answer(
            send(
                admin_client,
                csv_file("Reference;Title;Team", "SD-30;Only a look;Spare"),
            )
        )

        assert result["counts"]["create"] == 1
        assert not Ticket.objects.filter(reference="SD-30").exists()

    def test_a_unique_value_twice_in_one_file_is_caught(
        self, admin_client, support_desk
    ):
        result = answer(
            send(
                admin_client,
                csv_file(
                    "Code;Name",
                    "AA;Same name",
                    "BB;Same name",
                ),
                url=CUSTOMERS,
            )
        )

        assert result["counts"]["error"] == 1
        assert result["errors"][0]["row"] == 3

    def test_a_required_field_missing_is_named(
        self, admin_client, support_desk
    ):
        result = answer(send(admin_client, csv_file("Reference", "SD-40")))

        assert set(result["missing"]) == {"title", "team"}
        assert result["counts"]["error"] == 1


class TestTheMapping:
    def test_headers_are_matched_ignoring_accents_and_case(
        self, admin_client, support_desk
    ):
        result = answer(
            send(
                admin_client,
                csv_file("RÉFÉRENCE;titre;Priorité", "SD-1;x;low"),
            )
        )

        # English names, a French title, a French field name.
        assert result["mapping"] == ["reference", None, None]

    def test_french_headers_under_a_french_session(
        self, admin_client, support_desk
    ):
        result = answer(
            send(
                admin_client,
                csv_file("Référence;Titre;Priorité", "SD-1;x;low"),
                language="fr",
            )
        )

        assert result["mapping"] == ["reference", "title", "priority"]

    def test_a_confirmed_mapping_wins(self, admin_client, support_desk):
        result = answer(
            send(
                admin_client,
                csv_file("Ref;Label", "SD-1;Renamed"),
                mapping=["reference", "title"],
                commit=True,
            )
        )

        assert result["committed"]
        support_desk["login"].refresh_from_db()
        assert support_desk["login"].title == "Renamed"

    def test_a_mapping_naming_another_field_is_refused(
        self, admin_client, support_desk
    ):
        response = send(
            admin_client,
            csv_file("Ref;Label", "SD-1;x"),
            mapping=["reference", "opened_at"],
        )

        assert response.status_code == 400

    def test_two_columns_to_one_field_are_refused(
        self, admin_client, support_desk
    ):
        response = send(
            admin_client,
            csv_file("Ref;Label", "SD-1;x"),
            mapping=["title", "title"],
        )

        assert response.status_code == 400


class TestRefusals:
    def test_a_user_without_add_or_change_is_refused(
        self, client, support_desk
    ):
        from tests.factories import UserFactory

        client.force_login(UserFactory())

        assert send(client, csv_file("Reference", "SD-1")).status_code == 403

    def test_a_resource_without_imports_answers_404(
        self, admin_client, support_desk
    ):
        response = send(
            admin_client,
            csv_file("Name", "x"),
            url="/api/example/team/import/",
        )

        assert response.status_code in (403, 404)

    def test_an_unknown_format_is_refused(self, admin_client, support_desk):
        response = send(
            admin_client, SimpleUploadedFile("tickets.pdf", b"%PDF-1.4")
        )

        assert response.status_code == 400

    def test_no_file_is_refused(self, admin_client, support_desk):
        assert admin_client.post(TICKETS, {}).status_code == 400

    @override_settings(GENERIC={"IMPORT_MAX_FILE_SIZE": 10})
    def test_a_file_too_large_is_refused(self, admin_client, support_desk):
        response = send(admin_client, csv_file("Reference;Title", "SD-1;x"))

        assert response.status_code == 400
        assert "larger" in response.json()["detail"]

    @override_settings(GENERIC={"IMPORT_MAX_ROWS": 1})
    def test_too_many_rows_are_refused(self, admin_client, support_desk):
        response = send(admin_client, csv_file("Reference", "SD-1", "SD-2"))

        assert response.status_code == 400

    def test_a_broken_workbook_is_refused(self, admin_client, support_desk):
        response = send(
            admin_client, SimpleUploadedFile("tickets.xlsx", b"not a zip")
        )

        assert response.status_code == 400


class TestWhatAnImportLeaves:
    def test_history_says_where_the_change_came_from(
        self, admin_client, support_desk
    ):
        answer(
            send(
                admin_client,
                csv_file(
                    "Reference;Title", "SD-1;From a file", name="march.csv"
                ),
                commit=True,
            )
        )

        entry = HistoryEntry.objects.filter(
            object_id=str(support_desk["login"].pk)
        ).first()
        assert entry.source == "Import march.csv"

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
                csv_file(
                    "Reference;Title;Team",
                    "SD-50;One;Spare",
                    "SD-51;Two;Spare",
                    "SD-52;Three;Spare",
                ),
                commit=True,
            )
        )

        # The history's own entries are news of their own resource.
        assert [
            change for label, change in sent if label == "example.ticket"
        ] == ["bulk"]


class TestThePage:
    def test_the_list_offers_the_button(self, admin_client, support_desk):
        response = admin_client.get("/example/ticket/")

        assert b"/example/ticket/import/" in response.content

    def test_a_reader_without_rights_sees_no_button(
        self, client, support_desk
    ):
        from django.contrib.auth.models import Permission

        from tests.factories import UserFactory

        viewer = UserFactory()
        viewer.user_permissions.add(
            Permission.objects.get(codename="view_ticket")
        )
        client.force_login(viewer)

        response = client.get("/example/ticket/")

        assert b"/example/ticket/import/" not in response.content
        assert client.get("/example/ticket/import/").status_code == 403

    def test_the_page_carries_its_schema(self, admin_client, support_desk):
        response = admin_client.get("/example/ticket/import/")
        config = response.context["import_config"]

        assert config["schema"]["key"] == "reference"
        assert config["urls"]["run"] == TICKETS

    def test_the_schema_endpoint(self, admin_client, support_desk):
        schema = admin_client.get(f"{TICKETS}schema/").json()
        priority = next(
            c for c in schema["columns"] if c["name"] == "priority"
        )

        assert schema["mode"] == "create_update"
        assert {"value": "urgent", "label": "Urgent"} in priority["choices"]
        # A state field moves through its transitions: never imported.
        assert "status" not in [c["name"] for c in schema["columns"]]

    def test_the_template_has_the_headers(self, admin_client, support_desk):
        response = admin_client.get(f"{TICKETS}template/")
        workbook = load_workbook(io.BytesIO(response.content))
        headers = [cell.value for cell in workbook.worksheets[0][1]]

        assert headers[:2] == ["Reference", "Title"]
        assert workbook.worksheets[1].title == "Allowed values"


class TestDeclarations:
    def declare(self, **options):
        from example.models import Tag

        site = GenericSite(name="imports-test")
        resource = type(
            "TagResource", (ModelResource,), {"imports": Import(**options)}
        )

        return resource(Tag, site)

    def test_an_unknown_field(self):
        with pytest.raises(ImproperlyConfigured, match="nope"):
            check_import(self.declare(fields=("nope",)))

    def test_a_key_that_is_not_unique(self):
        from example.models import Agent

        site = GenericSite(name="imports-test")
        resource = type(
            "AgentResource",
            (ModelResource,),
            {"imports": Import(key="team")},
        )(Agent, site)

        with pytest.raises(ImproperlyConfigured, match="unique"):
            check_import(resource)

    def test_updating_without_a_key(self):
        with pytest.raises(ImproperlyConfigured, match="key"):
            check_import(self.declare(mode="update"))

    def test_an_unknown_mode(self):
        with pytest.raises(ImproperlyConfigured, match="mode"):
            check_import(self.declare(mode="merge"))

    def test_a_lookup_on_a_field_that_is_not_a_relation(self):
        with pytest.raises(ImproperlyConfigured, match="relation"):
            check_import(self.declare(lookups={"name": "x"}))

    def test_imports_must_be_an_import(self):
        from example.models import Tag

        resource = type("X", (ModelResource,), {"imports": "yes"})(
            Tag, GenericSite(name="imports-test")
        )

        with pytest.raises(ImproperlyConfigured, match="Import"):
            check_import(resource)


def test_an_empty_file_is_refused():
    from generic.sites.imports import ImportRefused

    with pytest.raises(ImportRefused):
        read_file(csv_file(""), max_rows=10)

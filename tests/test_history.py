"""Every record keeps its versions, and says who wrote them.

An entry is a snapshot, so most of what is asserted here is what comes
back out: the difference between two versions is worked out when the
history is read, and that is the part a reader sees.
"""

from __future__ import annotations

import datetime
import decimal

import pytest
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.utils import timezone

from example.models import Tag, Ticket
from generic.history import HistoryEntry, acting_as, history_of, prune
from generic.sites import site

pytestmark = pytest.mark.django_db


def entries(obj):
    return list(history_of(obj).order_by("version"))


def history_url(ticket: Ticket) -> str:
    return f"/api/example/ticket/{ticket.pk}/history/"


def changed(entry: dict) -> dict:
    """One entry's changes, as ``{field: (from, to)}``."""
    return {
        change["name"]: (change["from"], change["to"])
        for change in entry["changes"]
    }


@pytest.fixture
def reader(django_user_model):
    """A user who may read tickets, and so may read their history."""
    reader = django_user_model.objects.create_user(
        username="reader",
        email="reader@example.test",
        password="x",
    )
    reader.user_permissions.add(
        Permission.objects.get(
            codename="view_ticket",
            content_type__app_label="example",
        )
    )

    return reader


@pytest.fixture
def reader_client(client, reader):
    client.force_login(reader)

    return client


class TestRecording:
    def test_creating_a_record_writes_its_first_version(self, support_desk):
        [entry] = entries(support_desk["export"])

        assert entry.version == 1
        assert entry.action == HistoryEntry.Action.CREATED
        assert entry.values["reference"] == "SD-3"
        assert entry.label == str(support_desk["export"])

    def test_a_change_writes_the_next_version(self, support_desk):
        ticket = support_desk["export"]

        ticket.status = Ticket.Status.OPEN
        ticket.save()

        first, second = entries(ticket)

        assert (first.version, second.version) == (1, 2)
        assert second.action == HistoryEntry.Action.UPDATED
        assert first.values["status"] == Ticket.Status.CLOSED
        assert second.values["status"] == Ticket.Status.OPEN

    def test_saving_without_changing_anything_writes_nothing(
        self,
        support_desk,
    ):
        ticket = support_desk["export"]

        ticket.save()
        ticket.save()

        assert len(entries(ticket)) == 1

    def test_a_decimal_is_recorded_as_the_database_holds_it(
        self,
        support_desk,
    ):
        # Found by the browser tests: `Decimal(2)` written by code was
        # kept as "2", the database gave "2.00" back, and the next save
        # of the title listed "Estimated hours 2.00 -> 2.00" as well.
        ticket = support_desk["export"]
        ticket.estimated_hours = decimal.Decimal(2)
        ticket.save()
        ticket.refresh_from_db()

        ticket.title = "Invoice export is slow on Mondays"
        ticket.save()

        *_, set_hours, retitled = entries(ticket)
        assert set_hours.values["estimated_hours"] == "2.00"
        assert {
            name
            for name, value in retitled.values.items()
            if set_hours.values.get(name) != value
        } == {"title"}

    def test_a_deletion_is_the_last_thing_recorded(self, support_desk):
        ticket = support_desk["export"]
        identity = str(ticket.pk)

        ticket.delete()

        kept = list(
            HistoryEntry.objects.filter(
                object_id=identity,
                content_type__model="ticket",
            ).order_by("version")
        )

        assert kept[-1].action == HistoryEntry.Action.DELETED
        # The record is gone; the entry still says what it was called.
        assert kept[-1].label == "SD-3 - Invoice export is slow"

    def test_changing_a_relation_records_what_it_points_at_now(
        self,
        support_desk,
    ):
        ticket = support_desk["export"]

        ticket.assignee = support_desk["yanis"]
        ticket.save()

        assert entries(ticket)[-1].values["assignee"] == (
            support_desk["yanis"].pk
        )

    def test_a_many_to_many_change_is_recorded(self, support_desk):
        ticket = support_desk["export"]

        ticket.tags.add(support_desk["billing"])

        assert entries(ticket)[-1].values["tags"] == [
            support_desk["billing"].pk
        ]

    def test_a_field_left_out_is_never_recorded(self, support_desk):
        resource = site.get_resource(Ticket)
        ticket = support_desk["export"]

        with override(resource, history_exclude=("title",)):
            ticket.title = "Something else entirely"
            ticket.save()

            latest = entries(ticket)[-1]

        assert "title" not in latest.values
        assert "reference" in latest.values

    def test_a_model_that_keeps_none_keeps_none(self, support_desk):
        resource = site.get_resource(Ticket)
        ticket = support_desk["export"]
        before = len(entries(ticket))

        with override(resource, history=False):
            ticket.title = "Quietly"
            ticket.save()

        assert len(entries(ticket)) == before

    @override_settings(GENERIC={"HISTORY": False})
    def test_the_setting_switches_the_whole_thing_off(self, support_desk):
        ticket = support_desk["export"]
        before = len(entries(ticket))

        ticket.title = "Quietly"
        ticket.save()

        assert len(entries(ticket)) == before


class TestWho:
    def test_a_request_names_the_person_who_made_the_change(
        self,
        worker_client,
        worker,
        support_desk,
    ):
        ticket = support_desk["export"]

        response = worker_client.patch(
            f"/api/example/ticket/{ticket.pk}/",
            {"title": "Export is slow, still"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content[:400]

        latest = entries(ticket)[-1]

        assert latest.user == worker
        assert latest.user_label == str(worker)

    def test_code_says_who_and_what_was_doing_it(self, support_desk, worker):
        ticket = support_desk["export"]

        with acting_as(worker, source="Nightly import"):
            ticket.title = "Imported"
            ticket.save()

        latest = entries(ticket)[-1]

        assert latest.user == worker
        assert latest.source == "Nightly import"

    def test_nobody_in_particular_is_recorded_as_nobody(self, support_desk):
        ticket = support_desk["export"]

        ticket.title = "By the shell"
        ticket.save()

        latest = entries(ticket)[-1]

        assert latest.user is None
        assert latest.user_label == ""

    def test_one_unit_of_work_is_one_version(self, support_desk, worker):
        """A form that saves a record and then its tags made one change."""
        ticket = support_desk["export"]
        before = len(entries(ticket))

        with acting_as(worker):
            ticket.title = "Renamed"
            ticket.save()
            ticket.tags.add(support_desk["billing"])
            ticket.priority = Ticket.Priority.HIGH
            ticket.save()

        after = entries(ticket)

        assert len(after) == before + 1
        assert after[-1].values["title"] == "Renamed"
        assert after[-1].values["priority"] == Ticket.Priority.HIGH
        assert after[-1].values["tags"] == [support_desk["billing"].pk]

    def test_separate_saves_outside_a_block_are_separate_versions(
        self,
        support_desk,
    ):
        ticket = support_desk["export"]

        ticket.title = "First"
        ticket.save()
        ticket.title = "Second"
        ticket.save()

        assert [entry.values["title"] for entry in entries(ticket)] == [
            "Invoice export is slow",
            "First",
            "Second",
        ]


class TestReadingItBack:
    def test_the_endpoint_says_what_changed(
        self,
        reader_client,
        support_desk,
    ):
        ticket = support_desk["export"]

        ticket.status = Ticket.Status.OPEN
        ticket.assignee = support_desk["camille"]
        ticket.save()

        body = reader_client.get(history_url(ticket)).json()
        newest = body["results"][0]

        assert body["count"] == 2
        assert newest["version"] == 2
        assert changed(newest)["status"] == ("Closed", "Open")
        # A key on the way in, a name on the way out.
        assert changed(newest)["assignee"] == ("", "Camille Rousseau")

    def test_the_first_version_changed_nothing_and_holds_everything(
        self,
        reader_client,
        support_desk,
    ):
        ticket = support_desk["export"]
        body = reader_client.get(history_url(ticket)).json()
        [entry] = body["results"]
        values = {field["name"]: field for field in entry["values"]}

        assert entry["action"] == "created"
        assert entry["changes"] == []
        assert values["title"]["display"] == "Invoice export is slow"
        assert values["assignee"]["empty"] is True

    def test_a_value_is_written_out_the_way_a_reader_expects_it(
        self,
        reader_client,
        support_desk,
    ):
        ticket = support_desk["login"]
        body = reader_client.get(history_url(ticket)).json()
        values = {
            field["name"]: field["display"]
            for field in body["results"][0]["values"]
        }

        assert values["priority"] == "High"
        assert values["is_billable"] == "Yes"
        assert values["estimated_hours"] == "2.00"
        assert sorted(values["tags"].split(", ")) == ["regression", "release"]

    def test_a_deleted_relation_is_still_named_by_its_key(
        self,
        reader_client,
        support_desk,
    ):
        """The record it pointed at is gone; the entry is not a lie."""
        ticket = support_desk["export"]
        spare = Tag.objects.create(name="temporary")

        ticket.tags.add(spare)
        key = spare.pk
        spare.delete()

        body = reader_client.get(history_url(ticket)).json()
        values = {
            field["name"]: field["display"]
            for field in body["results"][0]["values"]
        }

        assert values["tags"] == f"#{key}"

    def test_older_versions_are_asked_for_by_the_page(
        self,
        reader_client,
        support_desk,
    ):
        ticket = support_desk["export"]

        for number in range(3):
            ticket.title = f"Title {number}"
            ticket.save()

        first = reader_client.get(history_url(ticket), {"limit": 2}).json()
        second = reader_client.get(
            history_url(ticket),
            {"limit": 2, "offset": 2},
        ).json()

        assert first["count"] == 4
        assert first["hasMore"] is True
        assert [entry["version"] for entry in first["results"]] == [4, 3]
        assert [entry["version"] for entry in second["results"]] == [2, 1]
        assert second["hasMore"] is False
        # The oldest one on a page still knows what it changed, because
        # the page asks for one entry more than it shows.
        assert changed(first["results"][1])["title"] == (
            "Title 0",
            "Title 1",
        )

    def test_a_stranger_to_the_model_is_refused(
        self,
        auth_client,
        support_desk,
    ):
        response = auth_client.get(history_url(support_desk["export"]))

        assert response.status_code == 403

    def test_a_model_that_keeps_no_history_has_no_endpoint(
        self,
        admin_client,
        support_desk,
    ):
        from generic.tasks.models import TaskRun

        run = TaskRun.objects.create(task="tests.history", label="A run")
        response = admin_client.get(f"/api/generic/taskrun/{run.pk}/history/")

        assert response.status_code == 404

    def test_the_summary_says_who_touched_it_last(
        self,
        reader_client,
        support_desk,
        worker,
    ):
        ticket = support_desk["export"]

        with acting_as(worker):
            ticket.title = "Touched"
            ticket.save()

        body = reader_client.get(
            f"/api/example/ticket/{ticket.pk}/summary/"
        ).json()

        assert body["history"]["last"]["who"] == str(worker)
        assert body["history"]["last"]["action"] == "updated"
        assert body["history"]["url"] == history_url(ticket)


class TestTheHistoryPage:
    def test_it_is_not_offered_without_the_permission(
        self,
        worker_client,
        support_desk,
    ):
        response = worker_client.get("/generic/historyentry/")

        assert response.status_code == 403

    def test_an_administrator_sees_every_change(
        self,
        admin_client,
        support_desk,
    ):
        response = admin_client.get(
            "/api/generic/historyentry/",
            {"draw": 1, "start": 0, "length": 10},
        )

        assert response.status_code == 200
        assert response.json()["recordsTotal"] >= 1


class TestReachingTheEntries:
    def test_a_model_s_whole_history_is_one_query(self, support_desk):
        """``of`` takes a model as readily as a record."""
        support_desk["export"].title = "Renamed"
        support_desk["export"].save()

        every = HistoryEntry.objects.of(Ticket)
        one = HistoryEntry.objects.of(support_desk["export"])

        # Three tickets created, tags set on two of them, and the
        # rename above.
        assert every.count() == 6
        assert one.count() == 2

    def test_a_failure_to_record_does_not_break_the_save(
        self,
        support_desk,
        monkeypatch,
    ):
        """The change has happened; recording it is not allowed to undo
        it, and the savepoint means the failure took nothing with it."""
        from generic.history import recording

        def explode(*args, **kwargs):
            raise RuntimeError("no room left")

        monkeypatch.setattr(recording, "_version", explode)

        ticket = support_desk["export"]
        ticket.title = "Saved anyway"
        ticket.save()
        ticket.refresh_from_db()

        assert ticket.title == "Saved anyway"
        assert len(entries(ticket)) == 1

    def test_an_entry_with_no_person_says_what_was_doing_it(
        self,
        support_desk,
    ):
        ticket = support_desk["export"]

        with acting_as(source="Nightly import"):
            ticket.title = "Imported"
            ticket.save()

        assert entries(ticket)[-1].who == "Nightly import"


class TestPruning:
    def test_nothing_is_deleted_without_a_retention(self, support_desk):
        assert prune() == 0
        assert HistoryEntry.objects.exists()

    def test_old_entries_go_and_recent_ones_stay(self, support_desk):
        old = HistoryEntry.objects.first()
        old.at = timezone.now() - datetime.timedelta(days=90)
        old.save(update_fields=["at"])
        before = HistoryEntry.objects.count()

        deleted = prune(days=30)

        assert deleted == 1
        assert HistoryEntry.objects.count() == before - 1


class override:
    """Set attributes on a resource for the length of a block.

    A resource is built once per process, so a test that changes one
    puts it back - this is what does the putting back.
    """

    def __init__(self, resource, **attributes):
        self.resource = resource
        self.attributes = attributes
        self.before = {}

    def __enter__(self):
        for name, value in self.attributes.items():
            self.before[name] = getattr(self.resource, name)
            setattr(self.resource, name, value)

        return self.resource

    def __exit__(self, *error):
        for name, value in self.before.items():
            setattr(self.resource, name, value)

        return False

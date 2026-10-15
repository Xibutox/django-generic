"""PostgreSQL triggers: rows written outside the ORM keep a history.

``psql``, another application on the same database, raw SQL in a
project's code: none goes through the recorder. On PostgreSQL a
trigger on every recorded table writes the version instead, naming the
database role - and leaves the ORM's own writes, tagged, to the
application, so nothing is recorded twice.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import override_settings

from example.models import Ticket
from generic.history import history_of, triggers

pytestmark = pytest.mark.django_db

postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="PostgreSQL's triggers"
)


@pytest.fixture
def ticket(support_desk):
    return Ticket.objects.order_by("pk").first()


def raw(sql: str, params=()) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


@postgres_only
class TestOnPostgres:
    def test_raw_sql_is_recorded_with_the_database_role(self, ticket):
        before = history_of(ticket).count()

        raw(
            "UPDATE example_ticket SET title = %s WHERE id = %s",
            ["Changed in SQL", ticket.pk],
        )

        entry = history_of(ticket).first()
        assert history_of(ticket).count() == before + 1
        assert entry.action == "updated"
        assert entry.values["title"] == "Changed in SQL"
        assert entry.source == triggers.SOURCE
        assert entry.user is None
        # Who: the database role.
        assert entry.user_label == connection.settings_dict["USER"]
        # Its other values are written as the application writes them:
        # only the title differs from the version before.
        previous = history_of(ticket)[1]
        assert {
            name
            for name, value in entry.values.items()
            if previous.values.get(name) != value
        } == {"title"}

    def test_the_orm_is_recorded_once_by_the_application(self, ticket, worker):
        from generic.history import acting_as

        before = history_of(ticket).count()

        with acting_as(worker):
            ticket.title = "Saved"
            ticket.save()
            Ticket.objects.filter(pk=ticket.pk).update(title="Updated")

        # One unit of work, one version - the application's, with the
        # person; the triggers left both statements to it.
        assert history_of(ticket).count() == before + 1
        entry = history_of(ticket).first()
        assert (entry.user, entry.source) == (worker, "")
        assert entry.values["title"] == "Updated"

    def test_a_raw_update_changing_nothing_writes_nothing(self, ticket):
        before = history_of(ticket).count()

        raw("UPDATE example_ticket SET id = id WHERE id = %s", [ticket.pk])

        assert history_of(ticket).count() == before

    def test_a_raw_delete_is_the_last_version(self, ticket):
        pk = ticket.pk
        raw("DELETE FROM example_ticketcomment WHERE ticket_id = %s", [pk])
        raw("DELETE FROM example_ticket_tags WHERE ticket_id = %s", [pk])
        raw("DELETE FROM example_timeentry WHERE ticket_id = %s", [pk])
        raw("DELETE FROM example_ticket WHERE id = %s", [pk])

        entry = history_of(Ticket(pk=pk)).first()
        assert (entry.action, entry.source) == ("deleted", triggers.SOURCE)

    def test_the_command_prints_the_sql(self):
        out = io.StringIO()

        call_command("history_triggers", "--sql", stdout=out)

        assert "CREATE TRIGGER generic_history" in out.getvalue()
        assert "example_ticket" in out.getvalue()

    def test_turned_off_they_are_removed(self):
        assert any(
            table == "example_ticket"
            for table, _ in triggers.existing(connection)
        )

        with override_settings(GENERIC={"HISTORY_TRIGGERS": False}):
            assert triggers.install(connection, verbosity=0) == 0
            assert triggers.existing(connection) == []

        triggers.install(connection, verbosity=0)
        assert triggers.existing(connection)


@pytest.mark.skipif(
    connection.vendor == "postgresql", reason="the other databases"
)
def test_elsewhere_the_command_says_why():
    with pytest.raises(CommandError, match="PostgreSQL"):
        call_command("history_triggers")

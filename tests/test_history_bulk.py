"""Writes that bypass ``save()`` keep a history too.

``update()``, ``bulk_update()`` and ``bulk_create()`` send no signal;
before, they left no trace, and neither did the framework's own uses
of them - a right granted, a folder's team moved. A history that misses
some changes cannot be relied on.
"""

from __future__ import annotations

import pytest
from django.db.models import F, Value
from django.db.models.functions import Concat

from example.models import Ticket
from generic.history import HistoryEntry, acting_as, history_of, unrecorded

pytestmark = pytest.mark.django_db


def versions(ticket) -> list[HistoryEntry]:
    return list(history_of(ticket).order_by("version"))


@pytest.fixture
def ticket(support_desk):
    return Ticket.objects.order_by("pk").first()


def test_an_update_records_each_row_as_the_database_holds_it(ticket, worker):
    before = len(versions(ticket))

    with acting_as(worker, source="Nightly fix"):
        changed = Ticket.objects.filter(pk=ticket.pk).update(
            title=Concat(Value("Re: "), F("title"))
        )

    assert changed == 1
    entries = versions(ticket)
    assert len(entries) == before + 1
    last = entries[-1]
    assert last.action == HistoryEntry.Action.UPDATED
    assert last.values["title"] == "Re: " + ticket.title
    assert (last.user, last.source) == (worker, "Nightly fix")


def test_an_update_that_moves_rows_out_of_its_filter(support_desk):
    # Read before: after the update, the filter matches nothing.
    open_ones = list(
        Ticket.objects.filter(status="open").values_list("pk", flat=True)
    )
    assert open_ones

    Ticket.objects.filter(status="open").update(status="closed")

    for pk in open_ones:
        assert history_of(Ticket(pk=pk)).first().values["status"] == "closed"


def test_an_update_that_changes_nothing_writes_nothing(ticket):
    before = len(versions(ticket))

    Ticket.objects.filter(pk=ticket.pk).update(title=ticket.title)

    assert len(versions(ticket)) == before


def test_a_bulk_update_is_recorded_once_per_row(ticket):
    before = len(versions(ticket))
    ticket.title = "Bulk"

    Ticket.objects.bulk_update([ticket], ["title"])

    entries = versions(ticket)
    # Once: bulk_update's own update() is not recorded a second time.
    assert len(entries) == before + 1
    assert entries[-1].values["title"] == "Bulk"


def test_a_bulk_create_records_each_creation(ticket):
    fields = {
        field.attname: getattr(ticket, field.attname)
        for field in Ticket._meta.concrete_fields
        if not field.primary_key and not field.unique
    }

    created = Ticket.objects.bulk_create([Ticket(**fields)])

    assert created[0].pk is not None
    entries = versions(created[0])
    assert [entry.action for entry in entries] == ["created"]


def test_a_model_nobody_records_is_untouched(support_desk):
    count = HistoryEntry.objects.count()

    HistoryEntry.objects.filter(pk=-1).update(label="x")

    assert HistoryEntry.objects.count() == count


def test_unrecorded_says_so_in_code(ticket):
    before = len(versions(ticket))

    with unrecorded():
        Ticket.objects.filter(pk=ticket.pk).update(title="Quiet")

    assert len(versions(ticket)) == before


def test_a_rolled_back_update_leaves_no_version(ticket):
    from django.db import transaction

    before = len(versions(ticket))

    with pytest.raises(RuntimeError):
        with transaction.atomic():
            Ticket.objects.filter(pk=ticket.pk).update(title="Gone")
            raise RuntimeError

    assert len(versions(ticket)) == before

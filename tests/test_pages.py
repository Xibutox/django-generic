"""Every page of the URLconf, and every generated endpoint behind them.

The framework's own suite runs the sweep it ships to projects,
:class:`generic.testing.PageSweep`, over the test URLconf: the pages of
``tests/testapp``, the example's, and the framework's own screens. See
``generic/testing/pages.py`` for what each test proves, and
docs/testing.md.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import reverse

from generic.testing import PageSweep

pytestmark = pytest.mark.django_db


class TestEveryPage(PageSweep):
    expected = {
        # Opens the first page of the menu, when there is one.
        "generic_wiki:index": (200, 302),
    }

    @pytest.fixture
    def records(self, db, support_desk, library, workshop) -> dict[str, Any]:
        """A record of every model of the example and the test app.

        The framework's own screens get theirs from the base class, as
        they would in any project. Built from the fixtures the rest of
        the suite uses.
        """
        from django.utils import timezone

        from example.models import Customer, TimeEntry
        from generic.teams.models import Team
        from tests.testapp.models import (
            Binder,
            BinderSheet,
            Contract,
            Document,
            Manuscript,
            SharedNote,
        )

        customer = Customer.objects.create(
            name="Northwind Traders",
            code="NWT",
            account_manager=support_desk["camille"],
        )
        entry = TimeEntry.objects.create(
            ticket=support_desk["login"],
            agent=support_desk["camille"],
            hours="1.50",
            spent_on=timezone.localdate(),
        )

        binder = Binder.objects.create(
            team=Team.objects.create(name="Pooled"), title="Pooled"
        )

        return {
            "example.ticket": support_desk["login"],
            "example.ticketcomment": support_desk["comment"],
            "example.team": support_desk["front"],
            "example.agent": support_desk["camille"],
            "example.tag": support_desk["regression"],
            "example.customer": customer,
            "example.timeentry": entry,
            # Pages nobody wrote: auto() works them out from the models.
            "example.supplier": workshop["supplier"],
            "example.equipment": workshop["laptop"],
            "example.maintenance": workshop["visit"],
            "testapp.manuscript": Manuscript.objects.create(title="Pooled"),
            "testapp.contract": Contract.objects.create(title="Pooled"),
            # Its file is named, not written: the storage has none.
            "testapp.document": Document.objects.create(
                title="Pooled", file="documents/pooled.txt"
            ),
            # Team-scoped: a superuser reaches them all.
            "testapp.binder": binder,
            "testapp.bindersheet": BinderSheet.objects.create(
                binder=binder, title="Pooled"
            ),
            "testapp.sharednote": SharedNote.objects.create(title="Pooled"),
            # The hand-written pages of tests/testapp and the example.
            "book": library["emma"],
            "publisher": library["publisher"],
            "author": library["austen"],
            "ticket": support_desk["login"],
            "team": support_desk["front"],
            "agent": support_desk["camille"],
        }

    def test_logging_out_works(self, opener):
        """The page left out of the sweep, because it ends the session."""
        response = opener.post(reverse("site:logout"))

        assert response.status_code in (200, 302)

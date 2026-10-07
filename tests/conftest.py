"""Shared fixtures."""

from __future__ import annotations

import datetime
import importlib.util
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from generic.events.registry import registry
from tests.factories import (
    AuthorFactory,
    BookFactory,
    ChapterFactory,
    NotificationFactory,
    PublisherFactory,
    UserFactory,
)
from tests.testapp.models import Book

# The browser tests need the `browser` extra (Playwright and its pytest
# plugin), which the everyday install leaves out: without it, their
# folder is not even collected, rather than failing on an import - nor
# its files, when the folder is named on the command line.
if not (
    importlib.util.find_spec("playwright")
    and importlib.util.find_spec("pytest_playwright")
):
    collect_ignore = ["browser"]
    collect_ignore_glob = ["browser/*"]


@pytest.fixture(autouse=True)
def fresh_cache():
    """Each test starts with an empty cache: the failed sign-ins one
    test counts never lock another out."""
    from django.core.cache import cache

    cache.clear()

    yield

    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def staff_user(db):
    return UserFactory(username="staff", is_staff=True)


@pytest.fixture
def authenticated_client(api_client: APIClient, user) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def auth_client(client, user):
    """Django test client, signed in.

    The generic pages require authentication even when they require no
    particular permission, so this is the normal case for a UI test.
    """
    client.force_login(user)
    return client


@pytest.fixture
def clean_topic_registry():
    """Isolate topic registrations from one test to the next."""
    snapshot = dict(registry._topics)
    registry.clear()

    yield registry

    registry.clear()
    registry._topics.update(snapshot)


@pytest.fixture
def library(db) -> dict:
    """A small, fully known dataset.

    Values are explicit so filtering and ordering assertions can name
    exactly which rows they expect back.
    """
    publisher = PublisherFactory(name="Gallimard")

    austen = AuthorFactory(name="Jane Austen", email="jane@test")
    orwell = AuthorFactory(name="George Orwell", email="george@test")
    inactive = AuthorFactory(name="Inactive Author", is_active=False)

    emma = BookFactory(
        title="Emma",
        author=austen,
        publisher=publisher,
        genre=Book.Genre.FICTION,
        pages=474,
        price=Decimal("12.50"),
        rating=4.2,
        published_on=datetime.date(1815, 12, 23),
        released_at=datetime.datetime(
            2020,
            3,
            15,
            8,
            30,
            tzinfo=datetime.timezone.utc,
        ),
        is_available=True,
    )
    persuasion = BookFactory(
        title="Persuasion",
        author=austen,
        genre=Book.Genre.FICTION,
        pages=249,
        price=Decimal("9.90"),
        rating=3.9,
        published_on=datetime.date(1817, 12, 20),
        released_at=datetime.datetime(
            2021,
            6,
            1,
            18,
            45,
            tzinfo=datetime.timezone.utc,
        ),
        is_available=False,
    )
    essays = BookFactory(
        title="Essays",
        author=orwell,
        genre=Book.Genre.ESSAY,
        pages=1369,
        price=Decimal("24.00"),
        rating=None,
        published_on=None,
        released_at=None,
        is_available=True,
    )

    ChapterFactory(book=emma, title="Volume I", position=1)
    ChapterFactory(book=emma, title="Volume II", position=2)

    return {
        "publisher": publisher,
        "austen": austen,
        "orwell": orwell,
        "inactive": inactive,
        "emma": emma,
        "persuasion": persuasion,
        "essays": essays,
    }


@pytest.fixture
def notification(user):
    return NotificationFactory(user=user)


#: What a desk agent may do: work tickets and their comments, and look
#: up the teams, agents and tags a ticket points at.
WORKER_PERMISSIONS = (
    "view_ticket",
    "add_ticket",
    "change_ticket",
    "delete_ticket",
    "view_ticketcomment",
    "add_ticketcomment",
    "change_ticketcomment",
    "delete_ticketcomment",
    "view_team",
    "view_agent",
    "view_tag",
)


@pytest.fixture
def worker(db):
    """A user holding the example's everyday permissions."""
    from django.contrib.auth.models import Permission

    worker = UserFactory(username="worker")
    worker.user_permissions.set(
        Permission.objects.filter(
            content_type__app_label="example",
            codename__in=WORKER_PERMISSIONS,
        )
    )

    return worker


@pytest.fixture
def worker_client(client, worker):
    client.force_login(worker)
    return client


@pytest.fixture
def support_desk(db) -> dict:
    """The example's models, with values tests can name.

    The login ticket carries two tags on purpose: a filter or a search
    through the tags must still list it once.
    """
    from example.models import Agent, Tag, Team, Ticket, TicketComment

    front = Team.objects.create(name="Front office", code="FO")
    infra = Team.objects.create(name="Infrastructure", code="INFRA")
    spare = Team.objects.create(name="Spare", code="SP")

    camille = Agent.objects.create(
        name="Camille Rousseau",
        email="camille@example.test",
        team=front,
    )
    yanis = Agent.objects.create(
        name="Yanis Bertrand",
        email="yanis@example.test",
        team=infra,
    )

    regression = Tag.objects.create(name="regression")
    release = Tag.objects.create(name="release")
    billing = Tag.objects.create(name="billing")

    login = Ticket.objects.create(
        reference="SD-1",
        title="Login fails after password reset",
        team=front,
        assignee=camille,
        priority=Ticket.Priority.HIGH,
        status=Ticket.Status.OPEN,
        is_billable=True,
        estimated_hours=Decimal("2.00"),
    )
    login.tags.set([regression, release])

    invoice = Ticket.objects.create(
        reference="SD-2",
        title="Invoice PDF is blank",
        team=infra,
        assignee=yanis,
        priority=Ticket.Priority.NORMAL,
        status=Ticket.Status.PENDING,
    )
    invoice.tags.set([billing])

    export = Ticket.objects.create(
        reference="SD-3",
        title="Invoice export is slow",
        team=front,
        assignee=None,
        priority=Ticket.Priority.LOW,
        status=Ticket.Status.CLOSED,
    )

    first = TicketComment.objects.create(
        ticket=login,
        author="Camille",
        body="Reproduced on staging.",
        position=1,
    )
    TicketComment.objects.create(
        ticket=login,
        author="Yanis",
        body="Fixed in the next release.",
        position=2,
    )

    return {
        "front": front,
        "infra": infra,
        "spare": spare,
        "camille": camille,
        "yanis": yanis,
        "regression": regression,
        "release": release,
        "billing": billing,
        "login": login,
        "invoice": invoice,
        "export": export,
        "comment": first,
    }


@pytest.fixture
def workshop(support_desk) -> dict:
    """The example's equipment, whose pages are worked out by auto()."""
    from example.models import Equipment, Maintenance, Supplier

    supplier = Supplier.objects.create(
        name="Nordic Devices",
        email="sales@nordic.example",
        country="Sweden",
    )
    laptop = Equipment.objects.create(
        name="Latitude 5440",
        serial_number="EQ-LA-1",
        kind=Equipment.Kind.LAPTOP,
        state=Equipment.State.IN_USE,
        supplier=supplier,
        assigned_to=support_desk["camille"],
        price=Decimal("1200.00"),
    )
    headset = Equipment.objects.create(
        name="Evolve2 55",
        serial_number="EQ-HE-2",
        kind=Equipment.Kind.HEADSET,
        supplier=supplier,
    )
    visit = Maintenance.objects.create(
        equipment=laptop,
        description="Battery replaced",
        cost=Decimal("60.00"),
        is_done=True,
    )

    return {
        "supplier": supplier,
        "laptop": laptop,
        "headset": headset,
        "visit": visit,
    }


@pytest.fixture
def bom(db) -> dict:
    """A bill of materials, three levels deep, sharing a screw, in the
    example's article families."""
    from example.models import Article, ArticleFamily, BomLine

    bikes = ArticleFamily.objects.create(name="Bicycles")
    wheels = ArticleFamily.objects.create(name="Wheels", parent=bikes)
    hubs = ArticleFamily.objects.create(name="Hubs", parent=wheels)
    articles = {
        reference: Article.objects.create(
            reference=reference, name=name, kind=kind, family=family
        )
        for reference, name, kind, family in (
            ("BK-1", "City bicycle", "product", bikes),
            ("WH-1", "Wheel", "assembly", wheels),
            ("HB-1", "Hub", "assembly", hubs),
            ("SP-1", "Spoke", "part", wheels),
            ("SC-1", "Screw", "part", None),
            ("LO-1", "Loose part", "part", None),
        )
    }
    lines = {}

    for parent, child, position, quantity in (
        ("BK-1", "WH-1", 10, "2"),
        ("BK-1", "SC-1", 20, "12"),
        ("WH-1", "HB-1", 10, "1"),
        ("WH-1", "SP-1", 20, "32"),
        ("HB-1", "SC-1", 10, "4"),
    ):
        lines[(parent, child)] = BomLine.objects.create(
            parent=articles[parent],
            child=articles[child],
            position=position,
            quantity=Decimal(quantity),
        )

    return {
        **articles,
        "lines": lines,
        "bikes": bikes,
        "wheels": wheels,
        "hubs": hubs,
    }

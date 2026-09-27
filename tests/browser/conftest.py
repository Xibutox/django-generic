"""The browser tests: the example application, driven through Chromium.

Everything else in the suite talks to the server; these tests open the
pages as a person does, so the JavaScript - tables, forms, summary
pages, dialogs, the palette, grids, imports - runs for real. They use
pytest-playwright's ``page`` against pytest-django's ``live_server``.

They are opt-in (the ``browser`` extra and a browser download):

    pip install -e ".[export,import,events,tasks,wiki,fsm,api,dev,browser]"
    python -m playwright install chromium
    pytest tests/browser -m browser --no-cov

Every test in this folder is marked ``browser`` below, and a plain
``pytest`` deselects that marker (pyproject.toml).
"""

from __future__ import annotations

import asyncio
import datetime
import os
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from django.conf import settings as django_settings
from django.test import Client, override_settings
from django.utils import timezone

HERE = Path(__file__).resolve().parent


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Mark every test of this folder, before ``-m`` selects.

    The hook sees the whole session's items, not only this folder's:
    the path decides.
    """
    for item in items:
        if HERE in Path(str(item.path)).resolve().parents:
            item.add_marker(pytest.mark.browser)


@pytest.fixture(scope="session", autouse=True)
def orm_beside_playwright():
    """Let the tests use the ORM while Playwright's loop runs.

    Playwright's sync API runs an event loop in the main thread, and
    Django refuses a database call from a thread with a running loop
    (SynchronousOnlyOperation) - the fixtures and the assertions below
    make many. Only for the browser tests' session.
    """
    previous = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

    yield

    if previous is None:
        del os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"]
    else:
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = previous


@pytest.fixture(scope="session")
def django_db_modify_db_settings(
    django_db_modify_db_settings,
    tmp_path_factory,
):
    """SQLite in a file rather than in memory, for the live server.

    In memory, the server's threads would all share the tests' one
    connection, and a page asking for its table and two charts at once
    runs three queries on it together - which can hang for good. In a
    file, each thread has a connection of its own. PostgreSQL, when
    ``DATABASE_URL`` names it, is left alone.
    """
    database = django_settings.DATABASES["default"]

    if database["ENGINE"] == "django.db.backends.sqlite3":
        folder = tmp_path_factory.mktemp("browser-db")
        database.setdefault("TEST", {})["NAME"] = str(folder / "db.sqlite3")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """A Chromium of one's own, when Playwright's download is not it.

    ``PLAYWRIGHT_CHROMIUM_EXECUTABLE`` names the executable, for a
    machine whose browsers were installed for another Playwright.
    """
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")

    if not executable:
        return browser_type_launch_args

    return {**browser_type_launch_args, "executable_path": executable}


@pytest.fixture(scope="session")
def csrf_protection():
    """The example project's CSRF middleware, which the test settings lack.

    Without it no page is given the CSRF cookie, and every change the
    browser sends through the API is refused - which a project never
    sees. In the example's place: after Common, before the auth.
    """
    middleware = list(django_settings.MIDDLEWARE)
    middleware.insert(
        middleware.index(
            "django.contrib.auth.middleware.AuthenticationMiddleware"
        ),
        "django.middleware.csrf.CsrfViewMiddleware",
    )

    with override_settings(MIDDLEWARE=middleware):
        yield


@pytest.fixture(scope="session")
def live_server(csrf_protection, live_server):
    """pytest-django's server, started once the middleware is in place.

    The server builds its handler - and its middleware - when it starts.
    """
    return live_server


@pytest.fixture(scope="session")
def base_url(django_db_setup, live_server):
    """Pages are opened by path: ``page.goto("/example/ticket/")``."""
    return live_server.url


@pytest.fixture(autouse=True)
def no_websocket(settings):
    """No socket: the live server speaks WSGI.

    The pages would try ``/ws/events/`` and fill the console with
    failed attempts. The live events are the channels tests' subject.
    """
    settings.GENERIC = {**settings.GENERIC, "EVENTS_WEBSOCKET_URL": None}


@pytest.fixture(autouse=True)
def events_from_the_tests_dropped(monkeypatch):
    """The tests' own writes publish nothing; the server's still do.

    A record saved by a fixture announces itself, and handing that to
    the channel layer from the thread where Playwright's loop runs is
    refused (``async_to_sync`` beside a running loop). With no socket
    open, nobody would hear it anyway. The live server's threads have
    no loop, and publish as they always do.
    """
    from generic.events import bus

    send_to_groups = bus.send_to_groups

    def send(groups, event):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            send_to_groups(groups, event)

    monkeypatch.setattr(bus, "send_to_groups", send)


class ConsoleGuard:
    """What the pages said went wrong: uncaught errors and console errors.

    A test expecting the server to refuse something - a form sent with
    a field missing, a page the reader may not open - says so with
    :meth:`allow`; anything else fails the test.
    """

    def __init__(self):
        self.errors: list[str] = []
        self.allowed: list[tuple[int, str]] = []

    def allow(self, status: int, path: str) -> None:
        """Expect a failed request: ``status`` from a path starting so."""
        self.allowed.append((status, path))

    def watch(self, page) -> None:
        page.on("pageerror", lambda error: self.record(page, error))
        page.on("console", lambda message: self.console(page, message))

    def record(self, page, error) -> None:
        self.errors.append(f"{page.url}: uncaught {error}")

    def console(self, page, message) -> None:
        if message.type != "error" or self.is_allowed(message):
            return

        where = message.location.get("url") or page.url
        self.errors.append(f"{where}: {message.text}")

    def is_allowed(self, message) -> bool:
        failed = re.search(r"status of (\d{3})", message.text)

        if not failed:
            return False

        status = int(failed.group(1))
        path = urlsplit(message.location.get("url") or "").path

        return any(
            status == allowed and path.startswith(prefix)
            for allowed, prefix in self.allowed
        )


@pytest.fixture(autouse=True)
def console(context):
    """Fail a test whose pages logged an error or raised one."""
    guard = ConsoleGuard()
    context.on("page", guard.watch)

    yield guard

    if guard.errors:
        pytest.fail(
            "The browser reported errors:\n" + "\n".join(guard.errors),
            pytrace=False,
        )


# -- people ---------------------------------------------------------------

#: The sign-in form's password, for every account below.
PASSWORD = "demo"


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def admin(transactional_db, django_user_model):
    return django_user_model.objects.create_superuser(
        username="admin",
        email="admin@example.test",
        password=PASSWORD,
    )


@pytest.fixture
def viewer(transactional_db, django_user_model):
    """May look at every record of the example, and change nothing."""
    from django.contrib.auth.models import Permission

    viewer = django_user_model.objects.create_user(
        username="viewer",
        email="viewer@example.test",
        password=PASSWORD,
    )
    viewer.user_permissions.set(
        Permission.objects.filter(
            content_type__app_label="example",
            codename__startswith="view_",
        )
    )

    return viewer


@pytest.fixture
def sign_in(context, live_server):
    """Sign a user in without the form: the session, as a cookie.

    ``force_login`` writes the session to the database the live server
    reads; the browser only needs its key.
    """

    def sign_in(user):
        client = Client()
        client.force_login(user)
        name = django_settings.SESSION_COOKIE_NAME
        context.add_cookies(
            [
                {
                    "name": name,
                    "value": client.cookies[name].value,
                    "url": live_server.url,
                }
            ]
        )

        return user

    return sign_in


# -- the support desk -----------------------------------------------------

#: One ticket per line, by reference number: a title, then the index of
#: its team, assignee (None: nobody) and customer.
TICKETS = (
    ("Login fails after password reset", 0, 0, 0),
    ("Invoice PDF is blank", 1, 1, 1),
    ("Invoice export is slow", 0, None, 0),
    ("Printer offline on the second floor", 1, 1, None),
    ("VPN drops every hour", 1, 1, 1),
    ("New laptop for the accountant", 0, 2, 0),
    ("Mailbox full", 0, 0, None),
    ("Password expiry warning", 1, None, 1),
    ("Calendar invites arrive twice", 0, 2, 0),
    ("Dashboard shows stale figures", 1, 1, 1),
    ("Scanner saves to the wrong folder", 0, 0, None),
    ("Meeting room screen stays black", 0, 2, 0),
    ("Headset crackles during calls", 1, None, 1),
    ("Shared drive out of space", 1, 1, 0),
    ("Two-factor codes rejected", 0, 0, 1),
    ("Invoice numbers skip a value", 1, 1, 1),
    ("Timesheet cannot be submitted", 0, 2, None),
    ("Certificate warning on the intranet", 1, None, 0),
    ("Webcam not detected", 0, 0, 1),
    ("Backup job failed overnight", 1, 1, None),
    ("Spam filter too strict", 0, 2, 0),
    ("Screen flickers after update", 1, 1, 1),
    ("Keyboard layout keeps switching", 0, 0, 0),
    ("Licence renewal reminder", 1, None, 1),
    ("Guest network password", 0, 2, None),
)


@pytest.fixture
def desk(transactional_db) -> dict:
    """A small support desk: two teams, three agents, two customers.

    Twenty-five tickets, SD-1001 to SD-1025, SD-1001 opened last so it
    comes first; states and priorities go round their choices, and
    every other one, SD-1001 first, was reported by phone. SD-1001
    has two comments and three time entries, so its page has rows in
    both related tables, and two tags; the three invoice tickets carry
    the billing tag.
    """
    from example.models import (
        Agent,
        Customer,
        Tag,
        Team,
        Ticket,
        TicketComment,
        TimeEntry,
    )

    teams = [
        Team.objects.create(name="Front office", code="FO"),
        Team.objects.create(name="Infrastructure", code="INFRA"),
    ]
    agents = [
        Agent.objects.create(
            name="Camille Rousseau",
            email="camille@example.test",
            team=teams[0],
        ),
        Agent.objects.create(
            name="Yanis Bertrand",
            email="yanis@example.test",
            team=teams[1],
        ),
        Agent.objects.create(
            name="Lea Martin",
            email="lea@example.test",
            team=teams[0],
        ),
    ]
    customers = [
        Customer.objects.create(
            name="Acme Corporation",
            code="ACME",
            segment=Customer.Segment.ENTERPRISE,
            city="Lyon",
        ),
        Customer.objects.create(
            name="Globex",
            code="GLOBEX",
            segment=Customer.Segment.SMALL,
            city="Grenoble",
        ),
    ]
    tags = {
        name: Tag.objects.create(name=name, color=color)
        for name, color in (
            ("regression", "#dc2626"),
            ("release", "#2563eb"),
            ("billing", "#16a34a"),
        )
    }

    statuses = list(Ticket.Status)
    priorities = [
        Ticket.Priority.HIGH,
        Ticket.Priority.NORMAL,
        Ticket.Priority.LOW,
        Ticket.Priority.URGENT,
    ]
    now = timezone.now()
    tickets = {}

    for index, (title, team, assignee, customer) in enumerate(TICKETS):
        reference = f"SD-{1001 + index}"
        tickets[reference] = Ticket.objects.create(
            reference=reference,
            title=title,
            description=(
                "Reported by phone." if index % 2 == 0 else "Reported by mail."
            ),
            team=teams[team],
            assignee=None if assignee is None else agents[assignee],
            customer=None if customer is None else customers[customer],
            status=statuses[index % len(statuses)],
            priority=priorities[index % len(priorities)],
            estimated_hours=Decimal(index % 5 + 1),
            opened_at=now - datetime.timedelta(days=index, hours=1),
        )

    login = tickets["SD-1001"]
    login.tags.set([tags["regression"], tags["release"]])

    for ticket in tickets.values():
        if "Invoice" in ticket.title:
            ticket.tags.add(tags["billing"])

    comments = [
        TicketComment.objects.create(
            ticket=login,
            author="Camille Rousseau",
            body="Reproduced on staging.",
            position=1,
        ),
        TicketComment.objects.create(
            ticket=login,
            author="Yanis Bertrand",
            body="Fixed in the next release.",
            position=2,
        ),
    ]
    today = timezone.localdate()
    entries = [
        TimeEntry.objects.create(
            ticket=login,
            agent=agent,
            spent_on=today - datetime.timedelta(days=days),
            hours=Decimal(hours),
            note=note,
        )
        for agent, days, hours, note in (
            (agents[0], 0, "1.50", "Reproduced the failure"),
            (agents[1], 1, "2.00", "Patched the reset flow"),
            (agents[0], 2, "0.75", "Called the customer"),
        )
    ]

    return {
        "teams": teams,
        "agents": agents,
        "customers": customers,
        "tags": tags,
        "tickets": tickets,
        "login": login,
        "comments": comments,
        "entries": entries,
    }

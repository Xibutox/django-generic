"""Every page of the project, loaded.

The pages multiply on their own: each registered resource brings five,
and nobody writes a test for each. So this walks the URLconf instead of
listing them - a page added tomorrow is covered tomorrow, and a page
that starts raising is named by a failing test rather than by a user.

Each pass is cheap, and together they are the whole surface:

* signed in with every permission, every page must answer 200;
* signed in with none, and signed out, no page may raise - it
  redirects or refuses, which is a decision, where a 500 is a defect;
* every resource's generated endpoints answer too - rows, the form
  schema, a summary, each column's values, both exports, every chart -
  because those are generated per resource exactly as the pages are,
  and a page is only as good as what fills it.

A page whose address needs a value this module cannot supply fails
loudly in ``test_every_page_is_covered`` rather than quietly going
untested. Give it a record in ``Pool``, or a line in ``SKIPPED`` with
a reason.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from generic.history.recording import is_recorded
from generic.sites import site

#: ``<int:pk>``, ``<path:pk>``, ``<str:slug>`` - the name is what matters.
ARGUMENT = re.compile(r"<(?:[^:>]+:)?([^>]+)>")

#: Pages left out, each for a reason a reader can check.
SKIPPED = {
    # Signs the client out: covered on its own, below.
    "site:logout": "logging out is what it does",
    # Written to, never read: it takes a language and a destination.
    "site:set_language": "POST only",
}

#: What a page answers when a superuser opens it, where not 200.
EXPECTED: dict[str, tuple[int, ...]] = {
    # Already signed in, so it sends you where you were going.
    "site:login": (200, 302),
    # Opens the first page of the menu, when there is one.
    "generic_wiki:index": (200, 302),
    # A run is a record of something that happened: the resource
    # refuses to add one, and this is that refusal.
    "site:generic_taskrun_add": (403,),
    # So is a history entry, for the same reason.
    "site:generic_historyentry_add": (403,),
    # A permission is declared by a model, never written by hand: the
    # resource refuses to add or remove one.
    "site:auth_permission_add": (403,),
    "site:auth_permission_delete": (403,),
}


def walk(resolver: Any, prefix: str = "", namespace: str = "") -> Any:
    """Every named pattern of the URLconf, with its full path."""
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            own = entry.namespace or ""
            yield from walk(
                entry,
                prefix + str(entry.pattern),
                f"{namespace}{own}:" if own else namespace,
            )
        elif isinstance(entry, URLPattern) and entry.name:
            yield namespace + entry.name, prefix + str(entry.pattern)


def is_api(path: str) -> bool:
    """Endpoints answer with JSON; they have their own tests below.

    Router patterns arrive as regular expressions, so the anchors go
    before the path is read as a path.
    """
    plain = path.replace("^", "").replace("$", "")

    return any(segment == "api" for segment in plain.split("/"))


def discover() -> list[tuple[str, list[str]]]:
    """Every page, as ``(url name, argument names)``."""
    seen: dict[str, list[str]] = {}

    for name, path in walk(get_resolver()):
        if is_api(path) or name in seen:
            continue

        seen[name] = ARGUMENT.findall(path)

    return sorted(seen.items())


#: Collected once, at import: the parametrisation is the URLconf.
PAGES = discover()
PAGE_NAMES = [name for name, _arguments in PAGES]


class Pool:
    """One record of everything a page's address might name."""

    def __init__(self, records: dict[str, Any]) -> None:
        self.records = records

    def value(self, url_name: str, argument: str) -> Any:
        """What to put in the address, for this page and this argument."""
        if argument == "slug":
            return self.records["wiki"].slug

        # A row that is no model's: the first its resource lists.
        if argument == "key":
            for resource in site.get_data_resources():
                if url_name.split(":")[-1].startswith(resource.url_prefix):
                    row = next(iter(resource.get_rows(None)))

                    return resource.read(row, resource.key)

        record = self.record_for(url_name)

        if record is None:
            raise LookupError(
                f"{url_name} takes {argument!r} and this module has "
                f"nothing to put in it."
            )

        return record.pk

    def record_for(self, url_name: str) -> Any:
        """The record a page is about, from its own name."""
        name = url_name.split(":")[-1]

        # A generated page: site:<app>_<model>_<action>.
        for resource in site.get_resources():
            if name.startswith(f"{resource.url_prefix}_"):
                return self.records.get(resource.label_lower)

        # A hand-written page: <thing>-detail, <thing>-update...
        return self.records.get(name.split("-")[0])


@pytest.fixture
def pool(db, support_desk, library, workshop) -> Pool:
    """A record of every model any page can be asked to show.

    Built from the fixtures the rest of the suite uses, plus one row
    for everything else that is registered - the framework's own
    screens included, since they are pages like any other.
    """
    from django.contrib.auth.models import Group, Permission
    from django.utils import timezone

    from example.models import Customer, TimeEntry
    from generic.events.models import Message
    from generic.history.models import HistoryEntry
    from generic.tasks.models import TaskRun
    from generic.wiki.models import WikiPage
    from tests.factories import UserFactory

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
    run = TaskRun.objects.create(
        task="tests.page",
        label="A run",
        status=TaskRun.Status.SUCCESS,
        summary="Nothing much",
        results=[{"label": "Rows", "value": 1}],
        log=[{"at": "2026-01-01T00:00:00", "message": "Started"}],
    )
    page = WikiPage.objects.create(
        title="Welcome",
        slug="welcome",
        content="<p>Hello.</p>",
        show_on_dashboard=True,
    )

    records = {
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
        "generic.taskrun": run,
        # Written by the fixtures above, since saving anything records
        # a version of it.
        "generic.historyentry": HistoryEntry.objects.first(),
        # The people screens: an account that is not the one opening
        # the page, so the pages that refuse to manage yourself are
        # still exercised.
        "auth.user": UserFactory(username="pooled"),
        "auth.group": Group.objects.create(name="Pooled"),
        "auth.permission": Permission.objects.first(),
        "generic.message": Message.objects.create(
            title="Pooled", everyone=True
        ),
        # The hand-written pages of tests/testapp and the example.
        "book": library["emma"],
        "publisher": library["publisher"],
        "author": library["austen"],
        "ticket": support_desk["login"],
        "team": support_desk["front"],
        "agent": support_desk["camille"],
        "wiki": page,
    }
    records.update(schedules())

    return Pool(records)


def schedules() -> dict[str, Any]:
    """One row of each of the scheduler's models, where it is installed."""
    if not apps.is_installed("django_celery_beat"):
        return {}

    interval = apps.get_model("django_celery_beat", "IntervalSchedule")
    crontab = apps.get_model("django_celery_beat", "CrontabSchedule")
    clocked = apps.get_model("django_celery_beat", "ClockedSchedule")
    periodic = apps.get_model("django_celery_beat", "PeriodicTask")

    from django.utils import timezone

    every = interval.objects.create(every=1, period="hours")
    nightly = crontab.objects.create(minute="0", hour="3")
    once = clocked.objects.create(clocked_time=timezone.now())

    return {
        "django_celery_beat.intervalschedule": every,
        "django_celery_beat.crontabschedule": nightly,
        "django_celery_beat.clockedschedule": once,
        "django_celery_beat.periodictask": periodic.objects.create(
            name="Nightly",
            task="tests.page",
            crontab=nightly,
        ),
        "django_celery_beat.solarschedule": None,
    }


@pytest.fixture
def every_permission(db):
    """A user who may open everything, so nothing is skipped as 403."""
    return get_user_model()._default_manager.create_superuser(
        username="pages",
        email="pages@example.test",
        password="not-used-here",
    )


@pytest.fixture
def opener(client, every_permission):
    client.force_login(every_permission)

    return client


def address(name: str, arguments: list[str], pool: Pool) -> str:
    values = [pool.value(name, argument) for argument in arguments]

    return reverse(name, args=values)


pytestmark = pytest.mark.django_db


def test_every_page_is_covered():
    """Nothing escapes the sweep by having an address nobody can build.

    Written as its own test because the sweep below would otherwise
    report an unbuildable address as a failure of the page rather than
    as a gap here.
    """
    unreachable = sorted(
        name
        for name, arguments in PAGES
        if name not in SKIPPED
        and any(
            # "argument" is a GridView's: the record its page's name
            # starts with, as for a pk - team-triage takes a team. "key"
            # is a data resource's row.
            argument not in ("pk", "slug", "object_id", "argument", "key")
            for argument in arguments
        )
    )

    assert unreachable == [], (
        "These pages take an argument this module cannot fill. Add it "
        "to Pool.value, or to SKIPPED with a reason."
    )


@pytest.mark.parametrize("name", PAGE_NAMES)
def test_every_page_loads(name, opener, pool):
    """Open it with every permission: it must render."""
    if name in SKIPPED:
        pytest.skip(SKIPPED[name])

    arguments = dict(PAGES)[name]
    url = address(name, arguments, pool)
    response = opener.get(url)

    assert response.status_code in EXPECTED.get(
        name, (200,)
    ), f"{name} ({url}) answered {response.status_code}"


@pytest.mark.parametrize("name", PAGE_NAMES)
def test_no_page_raises_for_a_stranger(name, client, pool):
    """Signed out, a page redirects or refuses - it never breaks.

    A crash here is a page that touches the user before deciding
    whether there is one.
    """
    if name in SKIPPED:
        pytest.skip(SKIPPED[name])

    url = address(name, dict(PAGES)[name], pool)
    response = client.get(url)

    assert (
        response.status_code < 500
    ), f"{name} ({url}) answered {response.status_code} to a stranger"


@pytest.mark.parametrize("name", PAGE_NAMES)
def test_no_page_raises_for_a_user_without_permissions(
    name,
    auth_client,
    pool,
):
    """Signed in but allowed nothing: refused, never broken.

    The middle case, and the one that breaks: a page that reads the
    record before asking whether this user may see it.
    """
    if name in SKIPPED:
        pytest.skip(SKIPPED[name])

    url = address(name, dict(PAGES)[name], pool)
    response = auth_client.get(url)

    assert (
        response.status_code < 500
    ), f"{name} ({url}) answered {response.status_code}"


def test_logging_out_works(opener):
    """The page left out of the sweep, because it ends the session."""
    response = opener.post(reverse("site:logout"))

    assert response.status_code in (200, 302)


#: Every generated endpoint of every resource, which multiply the same
#: way the pages do.
RESOURCES = [resource.label_lower for resource in site.get_resources()]


def resource_named(label: str) -> Any:
    return next(
        entry for entry in site.get_resources() if entry.label_lower == label
    )


@pytest.mark.parametrize("label", RESOURCES)
def test_every_resource_endpoint_answers(label, opener, pool):
    """Rows, the form schema, and one record's summary."""
    resource = resource_named(label)
    prefix = f"/api/{resource.app_label}/{resource.model_name}/"

    rows = opener.get(prefix, {"draw": 1, "start": 0, "length": 10})
    schema = opener.get(f"{prefix}form-schema/")

    assert rows.status_code == 200, f"{label} rows: {rows.content[:200]}"
    assert schema.status_code == 200, f"{label} schema: {schema.content[:200]}"
    assert "data" in rows.json()

    record = pool.records.get(label)

    if record is None:
        return

    summary = opener.get(f"{prefix}{record.pk}/summary/")

    assert summary.status_code == 200, f"{label} summary"

    # The History tab reads the same way the summary does, and is
    # generated per resource exactly as everything else here is.
    history = opener.get(f"{prefix}{record.pk}/history/")
    expected = (200,) if is_recorded(resource) else (404,)

    assert history.status_code in expected, f"{label} history"


@pytest.mark.parametrize("label", RESOURCES)
def test_every_column_can_be_asked_for_its_values(label, opener, pool):
    """The filter editor asks every column for its values.

    One column of one resource that cannot answer takes the editor
    down, and the columns are generated - nobody writes them out.
    """
    resource = resource_named(label)
    prefix = f"/api/{resource.app_label}/{resource.model_name}/"
    columns = resource.get_table_config(request_for(opener))["columns"]
    refused = []

    for column in columns:
        response = opener.get(f"{prefix}facets/", {"column": column["name"]})

        # 400 is a column that does not offer its values, which is a
        # decision; 500 is a column that tried and broke.
        if response.status_code not in (200, 400):
            refused.append(f"{column['name']} -> {response.status_code}")

    assert refused == [], f"{label}: {refused}"


@pytest.mark.parametrize("label", RESOURCES)
def test_every_resource_exports(label, opener, pool):
    """Both exports, over the real columns of the real rows."""
    resource = resource_named(label)
    prefix = f"/api/{resource.app_label}/{resource.model_name}/"

    excel = opener.get(f"{prefix}export/")
    csv = opener.get(f"{prefix}export-csv/")

    assert excel.status_code == 200, f"{label} Excel export"
    assert csv.status_code == 200, f"{label} CSV export"

    # Streamed: reading it is what runs the generator.
    assert b"".join(excel.streaming_content) or True
    assert b"".join(csv.streaming_content) or True


@pytest.mark.parametrize("label", RESOURCES)
def test_every_chart_draws(label, opener, pool):
    """Each declared chart, computed by the database."""
    resource = resource_named(label)
    prefix = f"/api/{resource.app_label}/{resource.model_name}/"

    for chart in resource.get_charts():
        response = opener.get(f"{prefix}charts/{chart.name}/")

        assert response.status_code == 200, f"{label}: {chart.name}"
        assert "series" in response.json()


def request_for(client: Any) -> Any:
    """A request object a resource can be asked to describe itself to."""
    from django.test import RequestFactory

    request = RequestFactory().get("/")
    request.user = client.session and get_user_model()._default_manager.get(
        pk=client.session["_auth_user_id"]
    )

    return request

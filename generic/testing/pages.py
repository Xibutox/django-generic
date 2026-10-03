"""Every page of a project, loaded; every generated endpoint, answered.

The pages multiply on their own: each registered resource brings five,
and nobody writes a test for each. :class:`PageSweep` walks the URLconf
instead of listing them - a page added tomorrow is covered tomorrow,
and a page that starts raising is named by a failing test rather than
by a user.

Each pass is cheap, and together they are the whole surface:

* signed in with every permission, every page answers 200 (or what
  ``expected`` says), in every language of ``languages``;
* signed in with none, and signed out, no page may raise - it redirects
  or refuses, which is a decision, where a 500 is a defect;
* every resource's generated endpoints answer too - rows, the form
  schema, a summary and its history, each column's values, both
  exports, every chart, and where declared the import's schema and
  template and a record's transitions - because those are generated
  per resource exactly as the pages are.

A page whose address takes an argument nothing can fill fails
``test_every_page_is_covered`` loudly, rather than going untested: give
it a record in ``records``, a value in ``value_for``, or a line in
``skipped`` with a reason.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

#: ``<int:pk>``, ``<path:pk>``, ``<str:slug>`` - the name is what matters.
ARGUMENT = re.compile(r"<(?:[^:>]+:)?([^>]+)>")

#: Pages no sweep can open by a GET, whatever the project.
ALWAYS_SKIPPED = {
    # Signs the client out: tested on its own.
    "site:logout": "logging out is what it does",
    # Written to, never read: it takes a language and a destination.
    "site:set_language": "POST only",
}

#: What the framework's own pages answer a superuser, where not 200.
ALWAYS_EXPECTED: dict[str, tuple[int, ...]] = {
    # Already signed in, so it sends you where you were going.
    "site:login": (200, 302),
    # A run and a history entry are records of something that happened,
    # a permission is declared by a model: nobody adds one by hand.
    "site:generic_taskrun_add": (403,),
    "site:generic_historyentry_add": (403,),
    # An access is recorded when it happens, and kept as it was.
    "site:generic_accessentry_add": (403,),
    "site:generic_accessentry_delete": (403,),
    "site:auth_permission_add": (403,),
    "site:auth_permission_delete": (403,),
    # A token is made by its owner on the account page, shown once.
    "site:generic_tokens_apitoken_add": (403,),
    # The sweep's wiki image and file name files it never writes -
    # nothing is put in a project's MEDIA_ROOT: the storage's 404 is the
    # answer.
    "generic_wiki:image": (200, 404),
    "generic_wiki:file": (200, 404),
    # A wiki opens on its first page.
    "generic_wiki:wiki": (302,),
}


def walk(resolver: Any, prefix: str = "", namespace: str = "") -> Iterator:
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
    """Endpoints answer with JSON; they are swept per resource instead.

    Router patterns arrive as regular expressions, so the anchors go
    before the path is read as a path.
    """
    plain = path.replace("^", "").replace("$", "")

    return any(segment == "api" for segment in plain.split("/"))


#: Namespaces other applications test themselves: Django's admin, the
#: Debug Toolbar's panels.
FOREIGN_NAMESPACES = ("admin", "djdt")


def discover(
    urlconf: Any = None,
    excluded: tuple[str, ...] = FOREIGN_NAMESPACES,
) -> list[tuple[str, list[str]]]:
    """Every page, as ``(url name, argument names)``."""
    seen: dict[str, list[str]] = {}

    for name, path in walk(get_resolver(urlconf)):
        if is_api(path) or name in seen:
            continue

        if name.split(":")[0] in excluded and ":" in name:
            continue

        seen[name] = ARGUMENT.findall(path)

    return sorted(seen.items())


class PageSweep:
    """Subclass it in a test module; the tests write themselves.

    ``records``
        A fixture: one record per model label (``"library.book"``) any
        page's address may name, and per first word of a hand-written
        page's name (``"book"`` for ``book-detail``).
    ``skipped``
        ``{url name: reason}`` - pages left out, each for a reason a
        reader can check.
    ``expected``
        ``{url name: (status, ...)}`` - what a superuser gets, where
        not 200.
    ``languages``
        Language codes each page is opened in, as ``Accept-Language``;
        empty (the default) opens them once, in the project's own.
    ``arguments``
        The address arguments ``value_for`` knows how to fill.
    ``urlconf``, ``site``
        Another URLconf, another site: the project's by default.
    ``excluded_namespaces``
        Pages other applications test themselves: Django's admin and
        the Debug Toolbar, by default.

    The framework's own screens - people, groups, changes, messages,
    runs, mailings, tokens, the wiki, the schedules - get a record each
    from ``framework_records``; ``records`` is only the project's.
    """

    skipped: dict[str, str] = {}
    expected: dict[str, tuple[int, ...]] = {}
    languages: tuple[str, ...] = ()
    arguments: tuple[str, ...] = (
        "pk",
        "slug",
        "object_id",
        "argument",
        "key",
        "wiki",
    )
    urlconf: Any = None
    site: Any = None
    excluded_namespaces: tuple[str, ...] = FOREIGN_NAMESPACES

    # -- what to open ------------------------------------------------------

    def get_skipped(self) -> dict[str, str]:
        return {**ALWAYS_SKIPPED, **self.skipped}

    def get_expected(self, name: str) -> tuple[int, ...]:
        if name in self.expected:
            return self.expected[name]

        # A project that declares no task is not offered the task pages:
        # their address refuses rather than shows an empty catalogue.
        if name == "site:tasks":
            from generic.tasks.resources import tasks_are_offered

            if not tasks_are_offered():
                return (403,)

        return ALWAYS_EXPECTED.get(name, (200,))

    def get_site(self) -> Any:
        if self.site is not None:
            return self.site

        from generic.sites import site

        return site

    def pages(self) -> list[tuple[str, list[str]]]:
        return discover(self.urlconf, self.excluded_namespaces)

    def resource_labels(self) -> list[str]:
        resources = self.get_site().get_resources()

        return [resource.label_lower for resource in resources]

    def pytest_generate_tests(self, metafunc: Any) -> None:
        """The parametrisation is the URLconf and the registry.

        Called by pytest for each test of the class, so a subclass's
        ``skipped``, ``urlconf`` and ``site`` are read when the tests are
        collected, and nothing runs when this module is imported.
        """
        if "page" in metafunc.fixturenames:
            pages = [name for name, _arguments in self.pages()]
            metafunc.parametrize("page", pages, ids=pages)

        if "resource" in metafunc.fixturenames:
            labels = self.resource_labels()
            metafunc.parametrize("resource", labels, ids=labels)

        if "language" in metafunc.fixturenames:
            languages = list(self.languages) or [None]
            metafunc.parametrize(
                "language",
                languages,
                ids=[code or "default" for code in languages],
            )

    # -- who opens it ------------------------------------------------------

    @pytest.fixture
    def records(self, db: Any) -> dict[str, Any]:
        """Override: the records the addresses name."""
        return {}

    @pytest.fixture
    def framework_records(self, db: Any, django_user_model: Any) -> dict:
        """One record of each of the framework's own models.

        The project did not write these screens and should not have to
        feed them: an account that is not the one opening the pages - so
        the pages refusing to manage yourself are exercised too - a
        group, a permission, a message, a run, a mailing, a token, a wiki
        page, a team, the schedules, and a version of something.
        """
        return framework_records(django_user_model, self.get_site())

    @pytest.fixture
    def pooled(self, records: dict, framework_records: dict) -> dict:
        """What the addresses are filled from: the project's first."""
        return {**framework_records, **records}

    @pytest.fixture
    def superuser(self, db: Any, django_user_model: Any) -> Any:
        """Someone who may open everything, so nothing is a 403."""
        return django_user_model._default_manager.create_superuser(
            username="page-sweep",
            email="page-sweep@example.test",
            password="not-used-here",
        )

    @pytest.fixture
    def nobody(self, db: Any, django_user_model: Any) -> Any:
        """Signed in, allowed nothing."""
        return django_user_model._default_manager.create_user(
            username="page-sweep-nobody", password="not-used-here"
        )

    @pytest.fixture
    def opener(self, client: Any, superuser: Any) -> Any:
        client.force_login(superuser)

        return client

    # -- where it is -------------------------------------------------------

    def record_for(self, url_name: str, records: dict[str, Any]) -> Any:
        """The record a page is about, from its own name."""
        name = url_name.split(":")[-1]

        # A generated page: site:<app>_<model>_<action>.
        for resource in self.get_site().get_resources():
            if name.startswith(f"{resource.url_prefix}_"):
                return records.get(resource.label_lower)

        # A hand-written page: <thing>-detail, <thing>-update...
        return records.get(name.split("-")[0])

    def value_for(
        self,
        url_name: str,
        argument: str,
        records: dict[str, Any],
    ) -> Any:
        """What to put in the address, for this page and this argument.

        Override for the addresses of a project's own pages; call
        ``super()`` for the rest.
        """
        # The wiki finds a wiki, and its pages, by their slug.
        if argument == "wiki" and url_name.startswith("generic_wiki:"):
            page = records.get("generic_wiki.wikipage")

            if page is not None:
                return page.wiki.slug

        if argument == "slug" and url_name.startswith("generic_wiki:"):
            page = records.get("generic_wiki.wikipage")

            if page is not None:
                return page.slug

        # ... and its images and files by their key.
        if url_name in ("generic_wiki:image", "generic_wiki:file"):
            upload = records.get(
                "generic_wiki.wiki" + url_name.rpartition(":")[2]
            )

            if upload is not None:
                return upload.pk

        # A row that is no model's: the first its resource lists.
        if argument == "key":
            for resource in self.get_site().get_data_resources():
                if url_name.split(":")[-1].startswith(resource.url_prefix):
                    row = next(iter(resource.get_rows(None)))

                    return resource.read(row, resource.key)

        record = self.record_for(url_name, records)

        if record is None:
            raise LookupError(
                f"{url_name} takes {argument!r} and the sweep has nothing "
                f"to put in it: give it a record in records(), a value in "
                f"value_for(), or skip it."
            )

        if argument not in ("pk", "object_id", "argument") and hasattr(
            record, argument
        ):
            return getattr(record, argument)

        return record.pk

    def address(self, page: str, records: dict[str, Any]) -> str:
        arguments = dict(self.pages())[page]

        return reverse(
            page,
            urlconf=self.urlconf,
            args=[self.value_for(page, name, records) for name in arguments],
        )

    def skip_if_skipped(self, page: str) -> None:
        skipped = self.get_skipped()

        if page in skipped:
            pytest.skip(skipped[page])

    @staticmethod
    def headers(language: Any) -> dict[str, str]:
        return {"HTTP_ACCEPT_LANGUAGE": language} if language else {}

    def resource_named(self, label: str) -> Any:
        return next(
            entry
            for entry in self.get_site().get_resources()
            if entry.label_lower == label
        )

    @staticmethod
    def prefix_of(resource: Any) -> str:
        return resource.get_api_url()

    # -- the pages ---------------------------------------------------------

    def test_every_page_is_covered(self) -> None:
        """Nothing escapes the sweep by having an address nobody fills.

        A test of its own, so an unbuildable address is reported as a
        gap here rather than as a failure of the page.
        """
        skipped = self.get_skipped()
        unreachable = sorted(
            name
            for name, arguments in self.pages()
            if name not in skipped
            and any(argument not in self.arguments for argument in arguments)
        )

        assert unreachable == [], (
            f"These pages take an argument the sweep cannot fill: "
            f"{', '.join(unreachable)}. Teach value_for() about it, or "
            f"skip them with a reason."
        )

    def test_page_loads(
        self,
        page: str,
        language: Any,
        opener: Any,
        pooled: dict[str, Any],
    ) -> None:
        """Opened with every permission: it renders."""
        self.skip_if_skipped(page)
        url = self.address(page, pooled)
        response = opener.get(url, **self.headers(language))

        assert response.status_code in self.get_expected(
            page
        ), f"{page} ({url}) answered {response.status_code}"

    def test_page_never_breaks_for_a_stranger(
        self,
        page: str,
        client: Any,
        pooled: dict[str, Any],
    ) -> None:
        """Signed out, a page redirects or refuses - it never breaks.

        A crash here is a page touching the user before deciding
        whether there is one.
        """
        self.skip_if_skipped(page)
        url = self.address(page, pooled)
        response = client.get(url)

        assert (
            response.status_code < 500
        ), f"{page} ({url}) answered {response.status_code} to a stranger"

    def test_page_never_breaks_without_permissions(
        self,
        page: str,
        client: Any,
        nobody: Any,
        pooled: dict[str, Any],
    ) -> None:
        """Signed in but allowed nothing: refused, never broken.

        The case that breaks: a page reading the record before asking
        whether this user may see it.
        """
        self.skip_if_skipped(page)
        client.force_login(nobody)
        url = self.address(page, pooled)
        response = client.get(url)

        assert (
            response.status_code < 500
        ), f"{page} ({url}) answered {response.status_code}"

    # -- what fills them ---------------------------------------------------

    def test_resource_endpoints(
        self,
        resource: str,
        opener: Any,
        pooled: dict[str, Any],
    ) -> None:
        """Rows, the form schema; a record's summary and history."""
        from generic.history.recording import is_recorded

        entry = self.resource_named(resource)
        prefix = self.prefix_of(entry)

        rows = opener.get(prefix, {"draw": 1, "start": 0, "length": 10})
        schema = opener.get(f"{prefix}form-schema/")

        assert rows.status_code == 200, f"{resource} rows: {rows.content!r}"
        assert schema.status_code == 200, f"{resource} form schema"
        assert "data" in rows.json()

        record = pooled.get(resource)

        if record is None:
            return

        summary = opener.get(f"{prefix}{record.pk}/summary/")

        assert summary.status_code == 200, f"{resource} summary"

        history = opener.get(f"{prefix}{record.pk}/history/")
        expected = (200,) if is_recorded(entry) else (404,)

        assert history.status_code in expected, f"{resource} history"

    def test_every_column_lists_its_values(
        self,
        resource: str,
        opener: Any,
        superuser: Any,
        pooled: dict[str, Any],
    ) -> None:
        """The filter editor asks every column for its values.

        One column that cannot answer takes the editor down: 400 is a
        column that does not offer its values, a decision; 500 is one
        that tried and broke.
        """
        from django.test import RequestFactory

        entry = self.resource_named(resource)
        prefix = self.prefix_of(entry)
        request = RequestFactory().get("/")
        request.user = superuser
        refused = []

        for column in entry.get_table_config(request)["columns"]:
            response = opener.get(
                f"{prefix}facets/", {"column": column["name"]}
            )

            if response.status_code not in (200, 400):
                refused.append(f"{column['name']} -> {response.status_code}")

        assert refused == [], f"{resource}: {refused}"

    def test_resource_exports(
        self,
        resource: str,
        opener: Any,
        pooled: dict[str, Any],
    ) -> None:
        """Both exports, over the real columns of the real rows."""
        prefix = self.prefix_of(self.resource_named(resource))

        for kind in ("export", "export-csv"):
            response = opener.get(f"{prefix}{kind}/")

            assert response.status_code == 200, f"{resource} {kind}"
            # Streamed: reading it is what runs the generator.
            b"".join(response.streaming_content)

    def test_every_chart_draws(
        self,
        resource: str,
        opener: Any,
        pooled: dict[str, Any],
    ) -> None:
        """Each declared chart, computed by the database."""
        entry = self.resource_named(resource)
        prefix = self.prefix_of(entry)

        for chart in entry.get_charts():
            response = opener.get(f"{prefix}charts/{chart.name}/")

            assert response.status_code == 200, f"{resource}: {chart.name}"
            assert "series" in response.json()

    def test_feature_endpoints(
        self,
        resource: str,
        opener: Any,
        pooled: dict[str, Any],
    ) -> None:
        """What a resource declares on top: an import, transitions."""
        from generic.sites.imports import declaration_of

        entry = self.resource_named(resource)
        prefix = self.prefix_of(entry)

        if declaration_of(entry) is not None:
            schema = opener.get(f"{prefix}import/schema/")
            template = opener.get(f"{prefix}import/template/")

            assert schema.status_code == 200, f"{resource} import schema"
            assert template.status_code in (
                200,
                400,
            ), f"{resource} import template"

        record = pooled.get(resource)

        if entry.get_transitions() and record is not None:
            response = opener.get(f"{prefix}{record.pk}/transitions/")

            assert response.status_code == 200, f"{resource} transitions"

    def test_the_api_description(self, opener: Any) -> None:
        """The OpenAPI description, where the project mounts it."""
        from django.urls import NoReverseMatch

        try:
            url = reverse("generic_openapi:schema", urlconf=self.urlconf)
        except NoReverseMatch:
            pytest.skip("generic.openapi is not mounted")

        response = opener.get(url, {"format": "json"})

        assert response.status_code == 200, response.content[:300]
        assert response.json()["paths"]


def framework_records(user_model: Any, site: Any) -> dict[str, Any]:
    """A record of every framework model installed, by model label."""
    from django.apps import apps
    from django.contrib.auth.models import Group, Permission
    from django.utils import timezone

    from generic.events.models import Message
    from generic.history.models import HistoryEntry
    from generic.mailings.models import ScheduledMailing
    from generic.tasks.models import TaskRun

    resources = site.get_resources()
    table = resources[0].state_key if resources else "site.none"
    records: dict[str, Any] = {
        user_model._meta.label_lower: user_model._default_manager.create_user(
            username="page-sweep-pooled", password="not-used-here"
        ),
        "auth.group": Group.objects.create(name="Page sweep"),
        "auth.permission": Permission.objects.first(),
        "generic.message": Message.objects.create(title="Page sweep"),
        "generic.taskrun": TaskRun.objects.create(
            task="page.sweep",
            label="A run",
            status=TaskRun.Status.SUCCESS,
            summary="Nothing much",
            results=[{"label": "Rows", "value": 1}],
            log=[{"at": "2026-01-01T00:00:00", "message": "Started"}],
        ),
        "generic.scheduledmailing": ScheduledMailing.objects.create(
            name="Page sweep", table=table
        ),
    }

    if apps.is_installed("generic.wiki"):
        from generic.wiki.models import WikiFile, WikiImage, WikiPage

        records["generic_wiki.wikipage"] = WikiPage.objects.create(
            title="Page sweep", slug="page-sweep", content="<p>Hello.</p>"
        )
        # Named, not written: a sweep puts nothing in MEDIA_ROOT.
        records["generic_wiki.wikiimage"] = WikiImage.objects.create(
            file="wiki/images/page-sweep.png", original_name="page-sweep.png"
        )
        records["generic_wiki.wikifile"] = WikiFile.objects.create(
            file="wiki/files/page-sweep.pdf", original_name="page-sweep.pdf"
        )

    if apps.is_installed("generic.teams"):
        from generic.teams.models import Team

        records["generic_teams.team"] = Team.objects.create(name="Page sweep")

    if apps.is_installed("generic.tokens"):
        from generic.tokens.models import ApiToken

        records["generic_tokens.apitoken"] = ApiToken.objects.create(
            user=records[user_model._meta.label_lower], name="Page sweep"
        )[0]

    if apps.is_installed("django_celery_beat"):
        interval = apps.get_model("django_celery_beat", "IntervalSchedule")
        crontab = apps.get_model("django_celery_beat", "CrontabSchedule")
        clocked = apps.get_model("django_celery_beat", "ClockedSchedule")
        periodic = apps.get_model("django_celery_beat", "PeriodicTask")
        nightly = crontab.objects.create(minute="0", hour="3")
        records.update(
            {
                "django_celery_beat.intervalschedule": (
                    interval.objects.create(every=1, period="hours")
                ),
                "django_celery_beat.crontabschedule": nightly,
                "django_celery_beat.clockedschedule": clocked.objects.create(
                    clocked_time=timezone.now()
                ),
                "django_celery_beat.periodictask": periodic.objects.create(
                    name="Page sweep", task="page.sweep", crontab=nightly
                ),
            }
        )

    # Written by the saves above, since saving anything records a
    # version of it.
    records["generic.historyentry"] = HistoryEntry.objects.first()

    from django.contrib.contenttypes.models import ContentType

    from generic.access.models import AccessEntry

    message = records["generic.message"]
    records["generic.accessentry"] = AccessEntry.objects.create(
        content_type=ContentType.objects.get_for_model(message),
        object_id=str(message.pk),
        record_key=f"generic.message:{message.pk}",
        label="Page sweep",
    )

    return records

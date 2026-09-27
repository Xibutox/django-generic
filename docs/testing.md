# Testing

```bash
pytest                       # everything, with coverage
pytest tests/api             # one area
pytest -k inlines            # one topic
pytest --no-cov -q           # fastest feedback
```

The suite is self-contained: SQLite and an in-memory channel layer, no
services to start. About 1700 tests, a minute or two with coverage,
from a checkout with the `dev` extra:

```bash
pip install -e ".[export,events,tasks,wiki,dev]"
```

Against Postgres and Redis:

```bash
docker compose -f docker/docker-compose.dev.yml run --rm web pytest
```

The same tests run either way — `tests/settings.py` switches backends on
`DATABASE_URL` and `REDIS_URL`.

Under a debugger, add `--no-cov`: coverage's tracer and the debugger's
cannot share the process, and the breakpoints would be skipped. VS
Code's *Pytest: this file* and *Pytest: tests matching...*
configurations, and its test explorer, already do
([Debugging](deployment.md#debugging)).

## The package as a user installs it

The suite runs against the checkout; `scripts/smoke_install.py` runs
against the package. Built, installed alone in an environment where
nothing of the repository is on the path, it writes a brand-new project
- one app, one model, the framework wired in as
[Installation](installation.md) says - then migrates, collects the
static files with hashed names as production does, runs the system
checks, and opens every kind of page and endpoint signed in and signed
out, in English and in French:

```bash
python -m build
python -m venv /tmp/try
/tmp/try/bin/pip install dist/*.whl                    # the core alone
/tmp/try/bin/python scripts/smoke_install.py
/tmp/try/bin/python scripts/smoke_install.py --prefix app/   # under a prefix
```

It is what catches a wheel missing its templates, static files or
translations, a dependency the core imports without declaring it, or a
guide that no longer matches the package. Both pipelines run it on
every change, the core alone and with every extra on the oldest Django
accepted.

## Versions tested

| | Oldest | Newest |
| --- | --- | --- |
| Python | 3.10 | 3.13 |
| Django | 5.2 | latest |
| Django REST framework | 3.16 | latest |

The matrix of both pipelines covers the two ends; the suite also runs
against PostgreSQL and Redis.

## Layout

```
tests/
├── settings.py         Two modes: in-process, or Postgres + Redis
├── urls.py             Routes for everything under test
├── asgi.py             Reference ASGI wiring
├── celery.py           Reference Celery wiring
├── conftest.py         Fixtures
├── factories.py        factory-boy factories
├── test_fieldsets.py   Form layout, without a view
├── test_templatetags.py
├── test_compat.py      The old import paths still work
├── testapp/            Models, serializers, viewsets and views
├── api/                Tables, filters, search, forms, inlines, exports,
│                       tag columns; test_rows.py: tables over rows that
│                       are not in the database
├── events/             Registry, bus, consumers, notifications
├── sites/              Registry, navigation, search, generated endpoint
│                       and pages, exports, summary pages, tag fields,
│                       charts - on the example's resources; test_auto.py:
│                       what auto() works out, and what a declaration keeps;
│                       test_data.py: data resources; test_resource_pages.py:
│                       pages of a resource's own; test_files.py: files in
│                       forms - sent, read, downloaded, refused
├── test_checks.py      The system checks: what `manage.py check` says about
│                       how a project plugged the framework in
├── test_i18n.py        Catalogs, the language menu, switching, the preference
├── test_project_settings.py  The example project's dev and prod modes: what
│                       production refuses to start without, what never
│                       reaches it, `check --deploy` and `collectstatic` run
├── test_maintenance.py Announced restarts: the warnings, the restart, the page
├── test_help.py        The changelog parser, the licence, the help pages
├── test_tasks.py       Declared tasks: the four steps, the audiences, the
│                       channels, the catalogue, the schedules
├── test_pages.py       Every page of the URLconf, opened three ways, and
│                       every generated endpoint behind them
├── test_watch.py       Watching a record or a model: who is told, when,
│                       through which channel, and who is not
├── test_history.py     What a version holds, what folds into one, who is
│                       recorded, and what the tab reads back
├── test_people.py      Accounts, groups and permissions: passwords, and
│                       every way the screens refuse to widen somebody
├── test_shortcuts.py   The dashboard's hub: who sees a card, where it
│                       may point, and the figure it carries
├── test_sso.py         The sign-in page: which ways in are offered,
│                       what they carry, and what is never taken away
├── test_editable.py    Cells edited in the table: what resolves, whose
│                       permission decides, and what the hook replaces
├── test_grids.py       Rows added in a grid, and grids over any set:
│                       what a new row writes and gets, scopes, arguments
├── accounts/           Preferences, profile, saved views
├── wiki/               HTML cleaning, API rules, pages, dashboard, search,
│                       images uploaded and served
└── views/              List, detail, edit, delete, datatable, toolbar
```

`tests/testapp` is also the worked example: `Publisher`, `Author`,
`Book` and `Chapter` cover every column type, a `PROTECT` relation for
the deletion preview, and a unique constraint spanning the parent for
the inline ordering rules.

## Every page, without writing a test per page

`tests/test_pages.py` walks the URLconf and turns it into tests. Nobody
lists the pages: each registered resource brings five, and a page added
tomorrow is covered tomorrow. It is the framework's own use of the
helper every project gets, `generic.testing.PageSweep` - see [Your
project's pages](#your-projects-pages) below.

Each page is opened three ways, and each answer means something
different:

| Opened by | Must answer |
| --- | --- |
| a superuser | `200` — it renders |
| a user with no permissions | anything below `500` — refusing is a decision |
| nobody, signed out | anything below `500` — it redirects to the login page |

Behind the pages, the same sweep covers what fills them, per resource:
the rows endpoint, the form schema, a record's summary, **each column's
values** (the filter editor asks every column, and one that cannot
answer takes the editor down), both exports, and every declared chart.

Addresses that need a value come from `Pool`, built on the same
fixtures as the rest of the suite. A page whose address the pool cannot
fill is not silently skipped: `test_every_page_is_covered` fails and
names it, so the choice is to give it a record or to write down why it
is exempt.

What it is not: these are smoke tests. They prove a page renders, not
that it renders the right thing — that is what the focused tests beside
them are for. They are worth their run time because the failure they
catch is the one a user sees first, and because three real defects came
out of writing them: a third-party field whose choices were not JSON,
the same field's form schema, and the Excel export refusing a cell type
it had never met.

## Your project's pages

The same sweep, for a project built on the framework, from a subclass:

```python
# tests/test_pages.py
import pytest

from generic.testing import PageSweep
from myapp.models import Project


class TestEveryPage(PageSweep):
    @pytest.fixture
    def records(self, db):
        """One record per model a page's address may name."""
        return {"myapp.project": Project.objects.create(name="Apollo")}
```

It needs pytest and pytest-django (`pip install pytest pytest-django`)
and nothing else from the project. The tests write themselves, one per
page or per resource:

| Test | Checks |
| --- | --- |
| `test_every_page_is_covered` | no page escapes because its address takes an argument nothing fills; the gap is named |
| `test_page_loads` | each page, as a superuser, answers 200 - or its `expected` status - in each of `languages` |
| `test_page_never_breaks_for_a_stranger` | signed out: below 500 |
| `test_page_never_breaks_without_permissions` | signed in, allowed nothing: below 500 |
| `test_resource_endpoints` | rows, form schema, a record's summary and history |
| `test_every_column_lists_its_values` | each column's `facets/`: 200 or 400, never 500 |
| `test_resource_exports` | both exports stream |
| `test_every_chart_draws` | each declared chart |
| `test_feature_endpoints` | where declared: the import's schema and template, a record's transitions |
| `test_the_api_description` | the OpenAPI description, where `generic.openapi` is mounted |

What a subclass may set:

| Attribute | |
| --- | --- |
| `records` (fixture) | the project's records, by model label (`"myapp.project"`), and by the first word of a hand-written page's name (`"project"` for `project-detail`) |
| `skipped` | `{url name: reason}` |
| `expected` | `{url name: (status, ...)}`, where a superuser does not get 200 |
| `languages` | `("en", "fr")` opens every page in each; empty, once |
| `value_for(url_name, argument, records)` | the value of an address argument the default cannot work out; call `super()` for the rest |
| `urlconf`, `site`, `excluded_namespaces` | another URLconf or site; the namespaces left to their own tests (`admin`, `djdt`) |

The framework's own screens - people, groups, permissions, changes,
messages, runs, mailings, tokens, the wiki, the schedules - get a
record each from the base class (`framework_records`): a project feeds
only its own models. The wiki's image names a file the sweep never
writes - nothing lands in a project's `MEDIA_ROOT` - so its page is
expected to answer 200 or 404. `scripts/smoke_install.py --sweep` runs such a
subclass against the installed wheel in CI, so the helper is tested as
a project uses it.

## Fixtures

| Fixture | Gives you |
| --- | --- |
| `api_client` | Unauthenticated `APIClient` |
| `authenticated_client` | `APIClient` signed in as `user` |
| `auth_client` | Django test client, signed in |
| `user`, `staff_user` | Users |
| `notification` | One unread notification for `user` |
| `library` | A small, fully known dataset |
| `support_desk` | The example's models, with values tests can name |
| `worker`, `worker_client` | A desk agent: works tickets, only views teams |
| `clean_topic_registry` | An isolated topic registry |

Use `auth_client` for any page test: the generic views require
authentication even when they require no particular permission, so an
anonymous `client` only ever proves that the redirect works.

`library` is explicit rather than random — three books with known titles,
page counts, dates and availability — so a filtering test can name
exactly which rows it expects back. The factories fill in only what a
test does not care about.

## Writing tests

### Tables

`fetch()` in `tests/api/test_filters.py` calls the endpoint and returns
row titles, which keeps assertions readable:

```python
def test_text_contains(self, api_client, library):
    titles = fetch(
        api_client,
        filters={"title": {"operator": "contains", "value": "ss"}},
    )

    assert titles == ["Essays"]
```

Every new filter engine deserves both halves: that a legitimate filter
narrows the queryset, and that anything outside the declaration is
refused. `TestFilteringIsWhitelisted` is where the second half lives.

### Events

Events are released on commit, so a test that expects one must commit:

```python
def test_it_publishes(self, sent, user,
                      django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        NotificationFactory(user=user)

    assert groups_of(sent) == [user_group(user.pk)]
```

The `sent` fixture patches `bus.send_to_groups`, so nothing needs a
channel layer.

### Consumers

Consumer tests use Channels' `WebsocketCommunicator` and need
`django_db(transaction=True)` plus `asyncio`. Both are set once via
`pytestmark`. Use `asend_to_groups` — the sync wrapper would deadlock on
the running loop:

```python
async def test_delivery(self, user):
    communicator = await connect(user)

    await asend_to_groups([user_group(user.pk)], Event(type="ping"))

    assert (await communicator.receive_json_from())["type"] == "ping"

    await communicator.disconnect()
```

`connect()` drains the `connection.ready` handshake frame for you.

Consumer tests need `daphne` installed — `channels.testing` imports it.

### Pages

Assert on the context rather than on scraped HTML: the markup is meant
to be overridden, the context vocabulary is the contract.

```python
def test_search_narrows_the_rows(self, auth_client, library):
    response = auth_client.get("/books/", {"q": "Emma"})

    assert [row.instance.title for row in
            response.context["table"]] == ["Emma"]
```

Rendered HTML is worth asserting on when the rendering *is* the
behaviour — that a protected object offers no confirm button, or that
the table configuration travels as `json_script`.

## Quality gates

```bash
black --check .            # line length 79
isort --check-only .
flake8 generic tests example example_project scripts debug.py
bandit -r generic -ll --skip B101
python scripts/compile_messages.py --check   # the .mo match the .po
mypy generic               # reported, not blocking: see below
```

CI runs the linters once, the suite on Python 3.10 to 3.13 - the oldest
Django and DRF accepted included - against SQLite, once more against
Postgres and Redis, and the package job above. Coverage must stay at or
above 80%; it sits at 93%. mypy reports without failing the build:
django-stubs trails the Django versions the framework runs on, and most
of what it says is that.

Two pipelines describe the same thing, for whichever host a project
uses: `.github/workflows/ci.yml` and `.gitlab-ci.yml`. The GitLab one
runs everything in containers on a Docker executor — the linters and the
catalogs check, the suite over the four Python versions, the suite
again against `postgres:16` and `redis:7` as services, the wheel built
and tried by `scripts/smoke_install.py`, then
`docker/Dockerfile` built, run (`pytest`, `manage.py check`) and pushed
to the project's registry on the default branch and on tags. The
`package` stage needs a privileged runner for docker-in-docker; the
stages before it need only the Docker executor.

The JavaScript — tables, forms, charts — has no automated tests yet. It
is checked by hand in a browser against the example; `node --check`
catches syntax errors, and every file must stay ASCII (non-ASCII
characters written as `\uXXXX`).

## Conventions

- One behaviour per test, named as a sentence about that behaviour.
- Assert on outcomes, not on internals: what the endpoint returned and
  what the database holds, not which method was called.
- Where a test exists because something once broke, say so in a comment.
  `test_deletions_run_before_creations` and
  `test_a_row_belonging_to_another_parent_is_refused` both guard real
  defects and are easy to "simplify" into uselessness otherwise.

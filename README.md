# django-generic

A reusable Django foundation for internal applications: an admin-like
interface built on a REST API, rich server-side data tables with
coloured tag columns, summary pages with tables of related records,
charts computed by the database, schema-driven forms with inline
editing, per-user colour personalisation, a small wiki, and real-time
events over WebSocket.

![A list page: charts computed by the database above a filterable table](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/list.png)

*The example support desk that ships with the repository - every
screenshot below is a page it generates, or a page of its own.*
[More screenshots](#screenshots)

The guiding idea is **declare once**. Declare how a model should appear
and you get its list page, its summary page, its forms, its delete
page, its REST endpoint and its place in the navigation:

```python
from generic.sites import (
    Chart, ModelResource, RelatedTable, TabularInline, TagStyle, register,
)


class CommentInline(TabularInline):
    model = TicketComment
    fields = ("author", "body", "position")


@register(Ticket)
class TicketResource(ModelResource):
    icon = "confirmation_number"
    list_display = ("reference", "title", "customer", "tags", "status")
    search_fields = ("reference", "title")
    tag_fields = {"tags": TagStyle(color="color", background="background")}
    fieldsets = (
        (None, {"fields": ("reference", ("title", "customer"), "tags")}),
        ("Billing", {"fields": ("is_billable",), "classes": ("collapse",)}),
    )
    inlines = (CommentInline,)
    related_tables = (RelatedTable("time_entries"),)
    charts = (Chart("by_status", type="donut", group_by="status"),)
    list_charts = ("by_status",)
```

It reads like a `ModelAdmin`, and the difference is underneath: every
page talks to the server through DRF, in JSON. The table is DataTables
with filters as chips — any column, any operator, relative dates, groups
of *all* and *any*, values offered with their counts, typed as
`status:open hours:>2` in the search box or in a row of fields under
the headers, kept in the address — a
multi-word search, saved views, exports to Excel and CSV, bulk actions
and live refresh; relations are Select2
fields fed by autocomplete endpoints, with popups to edit or create the
related record. A record opens on its summary page — figures, values
linking to the related records, and a tab per related table, each one
the related model's full table narrowed to that record. Charts are
declared the same way, computed by the database, served by the same
endpoint under the same filters, and drawn with Apache ECharts in the
page's own colours.

One layer down, the same machinery is available à la carte. A column
declared on a serializer field drives the table configuration, the
filtering whitelist, the ordering whitelist and the export:

```python
class BookSerializer(DataTableModelSerializer):
    title = CharColumn(title="Title")
    author = CharColumn(source="author.name", title="Author",
                        filter_field="author__name",
                        order_field="author__name", read_only=True)

    class Meta:
        model = Book
        fields = ("id", "title", "author")


class BookViewSet(DataTableViewSet):
    serializer_class = BookSerializer
    queryset = Book.objects.select_related("author")
```

## Screenshots

Taken from the example application in this repository
([Seeing it run](#seeing-it-run)); click one for the full size.

| | |
| --- | --- |
| [![Filters as chips](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/filters.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/filters.png) **Filters as chips** - typed as `status:open priority:urgent,high`, kept in the address | [![A record's summary page](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/record.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/record.png) **A summary page** - figures, typed values, actions, related tables |
| [![A form](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/form.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/form.png) **Forms** - drawn from the serializer: tabs, Select2 relations with edit and add popups | [![Dark theme with charts](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/dark.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/dark.png) **Charts and the dark theme** - computed by the database, drawn in the page's colours |
| [![An editable grid](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/grid.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/grid.png) **Grids** - every writable cell a control, saved as it is left | [![The command palette](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/palette.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/palette.png) **Ctrl+K** - every page and record, searched from anywhere |
| [![A page of the project's own: a map](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/map.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/map.png) **Pages of your own** - a map, declared on the resource with `@page` | [![A page of the project's own: a timeline](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/timeline.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/timeline.png) **...or a timeline** - the record found, the permissions checked, the frame drawn |
| [![The dashboard](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/dashboard.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/dashboard.png) **The dashboard** - a pinned wiki page, shortcuts with live counts, charts | [![On a phone](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/mobile.png)](https://raw.githubusercontent.com/Xibutox/django-generic/main/docs/screenshots/mobile.png) **On a phone** - the same pages, the navigation as an overlay |

## Installation

Python 3.10 or later, Django 5.2 or later, Django REST framework 3.16 or
later.

```bash
pip install django-generic
```

The core needs nothing else. Extras add the optional parts:

```bash
pip install "django-generic[export,events,tasks,wiki,postgres]"
```

`export` adds the Excel export (openpyxl), `import` Excel imports
(openpyxl, defusedxml), `api` API tokens and the OpenAPI description
(django-rest-knox, drf-spectacular), `fsm` state machines
(django-fsm-2), `events` live updates over
WebSocket (Channels, Daphne), `tasks` background tasks (Celery, Redis),
`beat` schedules managed from the pages, `wiki` the wiki (nh3),
`postgres` psycopg.

Then, in the project's settings and URLs - the full version, with what
each line is for, is in [Installation](docs/installation.md):

```python
INSTALLED_APPS = [..., "rest_framework", "generic", "myapp"]

MIDDLEWARE = [
    ...,
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "generic.middleware.UserLanguageMiddleware",
    "generic.middleware.CurrentUserMiddleware",
    ...,
]
# TEMPLATES: the "django.template.context_processors.request" processor.

LOGIN_URL = "site:login"
```

```python
from django.views.i18n import JavaScriptCatalog
from generic.sites import site

urlpatterns = [
    path("jsi18n/", JavaScriptCatalog.as_view(packages=["generic"]),
         name="javascript-catalog"),
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("", site.urls),          # or "app/" when the root is taken
]
```

```bash
python manage.py migrate
python manage.py check          # names anything missing from the wiring
python manage.py runserver
```

## Declaring screens

Resources go in a `resources.py` module of any installed app, imported
at start-up the way `admin.py` is: a `ModelResource` like the one above
([Sites and resources](docs/sites.md)), or nothing but the related rows,
letting the model say the rest — the columns, the search, the tags, the
form, the tables of related rows and the rows edited on the form:

```python
from generic.sites import auto

auto(Supplier, related=("equipment",))
auto(Equipment, related=("maintenances",))
```

Each line is a model's five pages, endpoint and navigation entry, worked
out from the model. See [Pages from the model](docs/auto.md).

Rows that are not in the database — an external API's answer, a list of
dicts — get a list page and a page per row the same way, read only:

```python
@register_data
class ServiceResource(DataResource):
    columns = {"name": CharColumn(title=_("Service")), "uptime": float}

    def get_rows(self, request):
        return statuspage.services()
```

See [Rows from elsewhere](docs/data.md).

And when the generated pages are not enough, a resource declares pages
of its own — any content, at its address, behind its permission, in the
frame:

```python
@page(title=_("Customer map"), icon="map", template="myapp/map.html")
def map(self, request):
    return {"customers": self.get_list_queryset(request)}
```

See [Pages of a resource's own](docs/pages.md).

## Documentation

- [Installation](docs/installation.md) — requirements, extras, plugging it into a new or existing project, the checks, the optional parts
- [The example project](docs/example.md) — click through every feature
- [Pages from the model](docs/auto.md) — `auto()`: the five pages of a model from one line, and what is worked out
- [Rows from elsewhere](docs/data.md) — `DataResource`: a list and a page per row for data that is not a model's, an external API's answer
- [Pages of a resource's own](docs/pages.md) — `@page` / `ResourcePage`: a map, a timeline, a gallery, a report, JSON… declared on the resource, any content
- [Sites and resources](docs/sites.md) — resources, tags, summary pages, related tables, inlines, actions, navigation, accounts, appearance
- [Charts](docs/charts.md) — declaring charts, where they are drawn, computed charts, the payload
- [The wiki](docs/wiki.md) — pages, editor, history, the HTML it keeps
- [Search without accents](docs/search.md) — `generic.search`: `societe` finds *Société* everywhere, trigram indexes, best match first
- [Testing](docs/testing.md) — the suite, and `generic.testing.PageSweep`: every page and endpoint of a project swept from ten lines
- [Building with an AI assistant](ai/README.md) — prompts that teach an assistant this framework, per use case
- [Architecture](docs/architecture.md) — how the modules fit together, and why the UI is DRF-first
- [Data tables](docs/tables.md) — columns, filters, ordering, exports
- [The API for scripts](docs/api.md) — personal tokens made on the account page, and the OpenAPI description and Swagger page of every endpoint
- [Scheduled mailings](docs/mailings.md) — a list, as each reader may see it, e-mailed as Excel or CSV every day, weekday, week or month
- [State machines](docs/transitions.md) — a model's django-fsm-2 transitions as buttons, bulk actions and an endpoint, the state read only elsewhere
- [Imports](docs/imports.md) — `Import(...)`: a spreadsheet read back into records, matched, previewed, all or nothing
- [Forms and inlines](docs/forms.md) — schema, sections, related rows
- [Editing in the table](docs/editable.md) — editable cells, fields of another model, the write
- [UI layer](docs/ui.md) — the classic generic views, templates, CSS and JS
- [Events, notifications and messages](docs/events.md) — who hears what, messages from an administrator, publishing, topics, the client protocol
- [Watching](docs/watch.md) — being told when a record, or a model, changes
- [History](docs/history.md) — the versions every record keeps, who changed what, when
- [People](docs/people.md) — users, groups and permissions, passwords, and what the screens refuse
- [Single sign-on](docs/sso.md) — declaring a provider, the sign-in page, forbidding local passwords
- [Tasks](docs/tasks.md) — declaring one, the four steps, the runs, Celery Beat schedules
- [Planned restarts](docs/maintenance.md) — announcing one, the three warnings, restarting the server
- [Translation](docs/i18n.md) — the French catalog, the language menu, the workflow
- [Settings](docs/settings.md) — every knob and its default
- [Development and production](docs/deployment.md) — the two settings modules, the two Docker stacks, debugging in VS Code, the variables, starting a new project
- [Testing](docs/testing.md) — running and extending the suite

## Seeing it run

The repository holds an example application built on the framework -
it is not part of the package. From a checkout:

```bash
pip install -e ".[export,events,tasks,wiki,dev]"
python manage.py migrate
python manage.py seed_example
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in as `admin` / `demo`. The
dashboard opens on a pinned wiki page and says what each part
demonstrates and what to try.

Under a debugger, `python debug.py` in place of `runserver` - or F5 in
VS Code, whose configurations the repository carries. See
[Debugging](docs/deployment.md#debugging).

The bundled example is a small support desk chosen for coverage: every
column type in one table, fieldsets with a collapsed section and a tab,
tabular and stacked inlines, customers with close to a hundred tickets
and hundreds of time entries each, a cascade delete and a protected
one, exports, autocomplete, permissions and live events. See
[the example](docs/example.md).

## Running the tests

The suite is self-contained: SQLite and an in-memory channel layer, no
services to start. From a checkout, with the `dev` extra installed as
above:

```bash
pytest
```

Against the real backends, through Docker:

```bash
docker compose -f docker/docker-compose.dev.yml run --rm web pytest
```

And the package as a user receives it - built, installed alone in a
clean environment, plugged into a brand-new project and opened page by
page:

```bash
python -m build
python -m venv /tmp/try && /tmp/try/bin/pip install dist/*.whl
/tmp/try/bin/python scripts/smoke_install.py
```

See [Testing](docs/testing.md).

## Development and production

Two modes, each with its settings module and its Docker stack — what a
new project copies. See [Development and production](docs/deployment.md).

```bash
docker compose -f docker/docker-compose.dev.yml up --build
```

**Development**: `example_project.settings.dev`, DEBUG, the Debug
Toolbar, runserver reloading on the mounted source, Postgres and Redis
in containers.

```bash
cp docker/prod.env.example docker/prod.env    # then fill it in
docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env up -d --build
```

**Production**: `example_project.settings.prod`, every secret from the
environment or no start, Daphne behind Caddy (HTTPS, hashed static
files), migrations run once per start, Celery worker and scheduler.

Either way the web server is **ASGI**, not WSGI: the events module
needs it. A WSGI server serves the REST API perfectly well and drops
every WebSocket.

## Versions and changes

The versions follow [semantic versioning](https://semver.org): from
1.0.0 on, a declaration that works keeps working until the next major
version. What changed, release by release, is in
[generic/CHANGELOG.md](generic/CHANGELOG.md) - shipped inside the
package, and shown on the *Help › What changed* page of every
application built on it, after the application's own
[CHANGELOG.md](CHANGELOG.md).

## Licence

BSD 3-Clause, as Django's own - see [LICENSE](LICENSE). The libraries
shipped under `generic/static/generic/vendor/` keep their own licences,
each beside its files.

## Roadmap

1. **Browser tests.** The JavaScript is checked by hand; a Playwright
   suite driving the example would keep it honest.
2. **`drf-spectacular` schema** and the generated API reference.
3. **File fields in generated forms.** The schema describes them, but
   the JSON submit does not carry uploads yet — and the wiki inserts
   images by address only, for the same reason.
4. **Sharing saved views** between users, beside the per-user ones.

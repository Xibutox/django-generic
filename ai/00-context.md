# django-generic — reference context for an AI assistant

> Paste this file first, before any use-case prompt of this folder. It is
> the contract: what the framework is, which file does what, and how
> everything is declared. When the code and this file disagree, the code
> wins — read it, then say what differed.

You are building Django applications on **django-generic**, a reusable
framework giving an admin-like, DRF-driven interface. The framework is
already written, tested and documented. **Your job is to declare, not to
re-implement**: models, `resources.py`, a few methods, sometimes a custom
page. You never copy or rewrite the framework's tables, forms, summary
pages, charts, filters, exports or permissions.

---

## 1. Non-negotiable rules

1. **Declare once.** A model is described once, in a `ModelResource`.
   That declaration produces the list page, summary page, forms, delete
   page, REST endpoint, charts, sidebar entry and command-palette results.
   Never hand-write a page, serializer or viewset the resource can
   generate. When "a list and a form will do", declare even less:
   `auto(Model, related=(...))` works the resource out from the model
   (§5.11).
2. **DRF-first.** Pages are frames; data travels as JSON through DRF
   endpoints. Never add endpoints returning HTML fragments. No HTMX.
3. **DataTables stays** for every table. Never replace it.
4. **Alpine.js** for interactive bits of custom pages; **no Tailwind, no
   Node build step, no CDN** — static files are vendored.
5. **Security lives in the resource.** Permissions are model permissions
   checked by `has_*_permission` methods, enforced by the endpoint; hiding
   a button is never the protection. Clients send public column names,
   never ORM paths.
6. **Real-time is Django Channels over WebSocket**; Postgres + Redis +
   Celery in Docker for production. No SSE, no polling loops.
7. **Look before inventing.** If a need seems uncovered, search the
   framework (`generic/sites/resources.py`, `docs/`) first. If it is truly
   missing, say so and propose an extension of the framework rather than a
   one-off workaround in the project.

## 2. Stack

| Layer | Choice |
| --- | --- |
| Backend | Python ≥ 3.10, Django ≥ 5.2 (LTS), Django REST framework ≥ 3.16 |
| Real time | Channels 4 + Daphne (ASGI), channels-redis in production |
| Tasks | Celery + Redis |
| Database | PostgreSQL in production, SQLite for tests and dev |
| Tables | jQuery DataTables 3 (server-side), Select2 4.1 |
| Charts | Apache ECharts 6.1 (lazy-loaded) |
| UI state | Alpine.js 3 |
| Wiki editor | Quill 2, HTML cleaned by nh3; PDF export by fpdf2 (pure Python) |
| Icons | Material Symbols Outlined (font) — any glyph name works |
| Colours | CSS custom properties in OKLCH, computed from 5 parameters |
| Tests | pytest, pytest-django, factory-boy; Playwright for the opt-in browser tests |
| Style | black + isort (line length **79**), flake8 |

Not on PyPI - and `django-generic` there is an unrelated package: never `pip install django-generic` by name. Install in a project from its wheel, built from a checkout (`python -m pip wheel --no-deps --wheel-dir dist .`), kept in the project's `vendor/` and named by path in `requirements.txt`: `./vendor/django_generic-1.3.0-py3-none-any.whl[export,events,tasks,postgres,wiki]` (the core needs only Django and DRF); a project with `pyproject.toml` lists `django-generic[...]>=1.3,<2` there and keeps the wheel line plus `-e .` in `requirements.txt`. From a checkout of the framework: `pip install -e ".[export,events,tasks,postgres,wiki,dev]"`. New project, existing project, Docker, updating: `docs/installation.md`.

---

## 3. File map

### The framework package `generic/`

```
generic/
├── apps.py                 ready(): autodiscovers every app's resources.py
├── checks.py               system checks: the wiring a project needs (generic.E001-I001)
├── CHANGELOG.md            the framework's changelog, shipped in the package (Help page)
├── conf.py                 generic_settings: settings with defaults (GENERIC = {...})
├── urls.py                 api/generic/: preferences, profile, watches, saved views, notifications
├── models.py               re-exports accounts + events models
│
├── api/                    the DRF layer, usable on its own
│   ├── columns.py          Column classes (CharColumn, TagsColumn...), ColumnOptions, FilterSpec
│   ├── tags.py             TagStyle, clean_color: values drawn as coloured tags
│   ├── serializers.py      DataTableSerializer / DataTableModelSerializer: fields -> table config, whitelists
│   ├── filters.py          filter engines, filter trees (all/any), AdvancedFilterBackend,
│   │                       search, ordering backends; apply_search()
│   ├── facets.py           FacetMixin: a column's values + counts for the filter editor
│   ├── rows.py             RowsDataTableViewSet, RowList: tables over rows not in the
│   │                       database (filters as Q read in Python, search, order, facets)
│   ├── pagination.py       DataTables envelope {draw, recordsTotal, recordsFiltered, data}
│   ├── renderers.py        ?format=datatables and DataTables-shaped errors
│   ├── exports.py          ExportMixin: streaming Excel and CSV of the filtered rows
│   ├── autocomplete.py     AutocompleteView (Select2)
│   ├── forms.py            FormModelSerializer: serializer -> JSON form schema
│   ├── files.py            FormFileField, FileValueMixin: a stored file as {name, url, size}
│   ├── parsers.py          MultiPartJSONParser: _payload (JSON) + one part per file
│   ├── inlines.py          InlineProcessor: nested rows in one transaction
│   ├── relations.py        relation labels, Select2 wiring in forms
│   └── viewsets.py         DataTableViewSet, AggregatedDataTableViewSet, ModelFormViewSet
│
├── sites/                  the admin-like layer (ModelAdmin counterpart)
│   ├── __init__.py         public API: ModelResource, AutoResource, auto, register, site,
│   │                       DataResource, RelatedRows, RowLink, register_data,
│   │                       page, ResourcePage, ResourcePageView,
│   │                       RelatedTable, Grid, Chart, TagStyle, TabularInline,
│   │                       StackedInline, action, display, chart_payload
│   ├── site.py             GenericSite: registry, URLs, navigation, search, chrome, add_link,
│   │                       auto, complete_auto
│   ├── resources.py        ModelResource: every attribute and hook (READ THIS FIRST)
│   ├── auto.py             AutoResource, auto(): a resource worked out from the model
│   ├── pages.py            @page, ResourcePage, ResourcePageView, PagesMixin: pages of a
│   │                       resource's own (any content) at its address, guarded, framed
│   ├── data.py             DataResource, register_data: a list and a page per row for
│   │                       rows that are not a model's (an external API's answer)
│   ├── serializers.py      list_display/fields -> generated table and form serializers
│   ├── viewsets.py         ResourceViewSet: one endpoint per resource (rows, CRUD, schema,
│   │                       summary, exports, actions, autocomplete, charts, _related,
│   │                       _grid, cells, rows)
│   ├── views.py            generated pages: list, add/change, detail (summary), delete,
│   │                       dashboard; GridView (a declared grid's page)
│   ├── related.py          RelatedTable: tables of related records on a summary page
│   ├── editable.py         editable columns, as_grid, cell writes, new rows (add_options, create)
│   ├── grids.py            Grid, BoundGrid, RowContext: grids over any set of rows (_grid)
│   ├── summary.py          build_summary(): a record as typed JSON for its summary page
│   ├── files.py            a record's files: download URL, which are shown, the answer
│   ├── charts.py           Chart: declared aggregates -> chart payload; chart_payload()
│   ├── transitions.py      a model's django-fsm-2 transitions: read, offered, taken
│   ├── imports.py          Import, Importer: a spreadsheet read, mapped, converted,
│   │                       validated by the form serializer, written all or nothing
│   ├── inlines.py          TabularInline, StackedInline
│   ├── decorators.py       @action, @display
│   └── realtime.py         post_save/post_delete -> "resource.changed"; announce()
│
├── accounts/               UserPreferences (theme, language, appearance,
│                           page size...),
│                           profile, SavedView; login/account/notifications
│                           pages, set-language; resources.py: the People
│                           screens (users, groups, permissions) and
│                           guard.py, which refuses privilege escalation;
│                           throttle.py: failed sign-ins lock an account
│                           for a while (§13ter)
├── i18n.py                 offered_languages(), language_menu(), is_offered()
├── middleware.py           UserLanguageMiddleware: a user's saved language wins
│                           CurrentUserMiddleware: who the history records
├── locale/fr/LC_MESSAGES/  django.po/.mo (pages) and djangojs.po/.mo (browser)
├── maintenance/            announced restarts: RestartAnnouncement, the three
│                           warnings and the restart (scheduler.py), api, page
├── numbering/              Pattern, allocate, peek, next_value: numbers from a pattern
│                           ({team}-{year}-{seq:04}), one locked Sequence row per series (§13i)
├── mailings/               ScheduledMailing: a list's state e-mailed on a schedule; sending.py
│                           (as each recipient, through the resource's own export),
│                           dispatch.py (the generic.send_scheduled_mailings task)
├── tasks/                  declared tasks: registry, runner (announce, run,
│                           collect, report; in the request, a worker or a
│                           thread), TaskRun, the catalogue page and the
│                           django-celery-beat screens; operations.py:
│                           @operation, work a page starts (§13g)
├── reports.py              Report: a tree of levelled lines and sections that
│                           fold, isolated sections (savepoint) (§13g)
├── history/                HistoryEntry: a version of every record of every
│                           registered model; actor (who), recording (signals
│                           -> versions), reading (versions -> changes), and
│                           the Changes page
├── trash.py                Trashable (deleted_at, deleted_by), move_to_trash,
│                           restore, empty: a resource's trash (§13j)
├── access/                 AccessEntry: who opened which record, who
│                           downloaded which file; record(), the Access log
│                           page (§13j)
├── watch/                  Watch: a user follows a record or a model; the
│                           messages, the endpoints and the Watching page
├── delivery.py             one message, some people, the channels they chose
├── logs.py                 logging_config(), admins(), SharedRotatingFileHandler, ErrorMailHandler
│                           (notification / mail / event); shared by both
├── help/                   help page and changelog, read from the project's
│                           own LICENSE and CHANGELOG.md files
├── events/                 Channels consumer, topic registry, publish helpers, Notification, Message (messages.py sends, resources.py the screen)
├── wiki/                   optional app generic.wiki: Wiki (several), pages, revisions, Quill editor,
│                           nh3 cleaning, WikiImage, WikiFile (uploads from the editor), pdf.py (fpdf2)
├── teams/                  optional app generic.teams: Team (members, leaders, colour),
│                           the see_every_team permission, scoping.py (scope_to_teams,
│                           teams_of, in_teams_of, leaders_of), the People › Teams screen;
│                           a resource's team_field narrows everything (§13h)
├── tokens/                 optional app generic.tokens: ApiToken (knox's abstract token,
│                           its own table), TokenAuthentication (scope, last use),
│                           api/generic/tokens/, the account section, the People screen
├── openapi/                framework_schema(), ResourceAutoSchema (drf-spectacular),
│                           urls.py: api/schema/ and api/docs/ (sidecar files)
├── search/                 optional app generic.search: accents set aside in every text match
│                           (text_lookup, fold, normalize), lookups.py the unaccented transform,
│                           operations.py InstallUnaccent / CreateSearchIndex, ranking.py search_rank
├── forms/fieldsets.py      admin-style fieldsets for classic Django forms
├── testing/                PageSweep (pytest + pytest-django): a project's pages swept
├── views/                  classic server-rendered views: GenericListView, GenericDetailView,
│                           GenericCreateView, GenericUpdateView, GenericDeleteView, DataTableView;
│                           mixins.py (PageMixin...), toolbar.py (ToolbarItem, Breadcrumb)
├── templatetags/
│   ├── generic_ui.py       {% icon %}, {% generic_chrome %}, {% generic_chart %}
│   └── generic_tags.py     query-string and ordering helpers
├── templates/generic/
│   ├── base.html           THE frame: sidebar, top bar, palette, toasts; blocks below
│   ├── datatable.html      a page with one DataTable (vendor scripts included)
│   ├── resource/list.html, form.html, detail.html   generated pages (+ includes/)
│   ├── charts/chart.html, grid.html                 a chart card, a grid of cards
│   ├── site/index.html     the dashboard
│   ├── account/, auth/, chrome/, components/, wiki/
│   └── list.html, detail.html, form.html, delete_confirmation.html   classic views
└── static/generic/
    ├── css/tokens.css      every colour, computed (OKLCH + light-dark()); spacing, type,
    │                       radii; rem everywhere, so the browser's text size scales it all
    ├── css/base.css, components.css, forms.css, tables.css, datatables.css, select2.css,
    │   summary.css, charts.css, appearance.css, wiki.css, auth.css
    ├── js/core.js          window.Generic: config, t(), api, toast, theme, appearance, colors
    ├── js/events.js        Generic.events: the shared WebSocket
    ├── js/operations.js    Generic.operations: an answer's report tree as a
    │                       card, followed until the run ends (§13g)
    ├── js/dialogs.js       Generic.dialogs.confirm/alert
    ├── js/ui.js            Alpine: themeMenu, appearanceEditor, notificationBell,
    │                       commandPalette, watchControl, apiResource
    ├── js/charts.js        Alpine genericChart; Generic.charts (ECharts, lazy)
    ├── js/summary.js       Alpine recordSummary (summary page)
    ├── js/history.js       Alpine recordHistory (the History tab)
    ├── js/select2.js       Generic.select2 helpers
    ├── js/wiki.js          Alpine wikiPage
    ├── js/datatables/      core (operators), columns (renderers), query (filter
    │                       tree + typed syntax), toolbar, filterbar (chips,
    │                       editor, header funnels), filterrow (search fields
    │                       under the headers), selection, rowactions,
    │                       realtime, table (controller holding the filters), init
    ├── js/forms/           form.js (schema form), inlines.js, widgets.js
    └── vendor/             jquery, datatables, select2, alpine, quill, echarts, material-symbols
```

### A project using the framework

```
myproject/                  settings.py, urls.py, asgi.py, wsgi.py, celery.py
myapp/
├── models.py               your models (verbose names, choices, related_name, ordering)
├── resources.py            every screen: @register(Model) class XResource(ModelResource)
├── events.py               optional: register_topic(...) for custom real-time streams
├── api.py, urls.py         optional: custom DRF endpoints / pages not covered by resources
├── templates/myapp/        optional: dashboard.html, custom pages extending generic/base.html
├── management/commands/seed_<app>.py   demo data, users and groups
└── migrations/
tests/                      pytest; conftest.py fixtures; one file per area
```

The **reference implementation** is `example/` (a support desk) with
`example_project/`. `example/resources.py` shows every feature; mimic it.
`minimal/` is the smallest project the framework runs in - one
`settings.py` (no Channels, `EVENTS_WEBSOCKET_URL: None`), `urls.py`,
one model with `auto(Book)`, a `products` app declared by hand
(`Product`, its `Milestone`s - dated steps, edited as an inline - and
its `Document`s - a `FileField`, a related table; computed columns
*next step*, *progress*, *late* annotated in `get_list_queryset`,
presets, `detail_stats`, a computed horizontal timeline (time axis
through `options`, today marked) in `detail_charts`, two dashboard shortcuts; `seed_products`),
and `generic.wiki` (the `wiki` extra, `MEDIA_ROOT` for its images and
the documents) - run from its folder (`cd minimal &&
python manage.py runserver`) or in Docker (`minimal/Dockerfile`, one
service in `minimal/compose.yaml`, SQLite and the images in a volume
through `DJANGO_DB_PATH` and `DJANGO_MEDIA_ROOT`), kept working by
`tests/test_minimal.py` and CI's `minimal-docker` job. It also shows a
real SSO provider: with `MICROSOFT_CLIENT_ID` (and `_SECRET`,
`_TENANT_ID`) in the environment, its settings turn on django-allauth's
Microsoft provider, mount `allauth.urls` under `accounts/` and declare
the button in `GENERIC["SSO_PROVIDERS"]` (`route="microsoft_login"`);
unset, allauth is neither needed nor loaded.

`docmanager/` is a third, self-contained project (`docsite/settings.py`
like the minimal one, plus `generic.teams`, two languages, a 50 MB
`FILE_MAX_SIZE`): a document manager - `Folder` (a team's), `Tag`,
`Document` (its current `file` - optional: a document may be only a
number - `version`, `reference` DOC-00001, `code` the team's number,
`document_type`, `review_on`, `related`, an advisory check-out
`checked_out_by`),
`DocumentVersion` (number, file, original `file_name`, size, type,
SHA-256, change note, sender), each resource scoped by `team_field`;
`file_format` (`DOCX`, `PDF`: the extension, a field so lists search,
filter and preset on it - "Word files"); `documents/versions.py`
records, numbers (row lock) and restores versions; the document form's
change note is a `form_extra_fields` entry. The Word merge is the
example's own, not the framework's: `documents/merge.py` (`merge_docx`,
`docx_response`, on python-docx + docxcompose,
`docmanager/requirements.txt`), the page `DocumentResource.merge`
(`@page`, sidebar entry, GET/POST, `documents/merging.py`: items
`d<pk>`/`v<pk>` resolved through the resources' team-scoped querysets,
a template, downloaded or kept as a new document) and the *Merge into
Word* actions of documents and versions, which open it with
`{"redirect": ...}`. Team wikis: `TeamWiki` (wiki one-to-one; `team`
reads it, null = everyone; `editing_teams` write in it and read it,
none = its readers write) and `documents/wikis.py` as
`GENERIC["WIKI_ACCESS"]` and `["WIKI_EDIT_ACCESS"]`. Numbering:
`DocumentType` (`code` = `{type}`), `Codification` per team (`code` =
`{team}`, `pattern`, `on_create`), `documents/codification.py` over
`generic.numbering` (*Codify* action, form extra field `codify`).
Review circuits, all docmanager's: `Workflow` + `WorkflowStep`
(position, name, kind review/approval/acknowledgement, rule any/all,
users, groups as roles, `team_leaders`, `team_members`, days),
`Review` (document, workflow, message, status preparing/in
progress/approved/rejected/cancelled; steps copied, still editable),
`ReviewStep`, `ReviewTask` (assignee, status, comment, due, delegated);
`documents/workflows.py` is the engine (`start`, `advance` - a step
nobody can answer is skipped - `decide`, `skip_step`, `cancel`,
`delegate`, `refresh`, `remind`; review row locked), telling through
`generic.delivery.deliver` on commit (`DOCUMENT_REVIEW_CHANNELS`,
notification + mail): the asked person, and the starter + the team's
leaders at each step. Assignees read the documents they are asked
about outside their teams (`scope_to_teams` widened). A task is
answered on its change form (extra fields `decision`, `delegate_to`)
or by bulk actions; *My tasks* is a preset on an `is_mine`
annotation. Also: `Comment`, *Check out*/*Check in* (a notice, never
a lock), *Make obsolete*, *Send for review* (redirects to the review
add form). `seed_documents` makes three teams (each a leader and a
codification), seven accounts (password `demo`, `quentin` in no team,
role *Quality*), types, a document without a file, three workflows,
three reviews under way, and Word/PDF/text samples (`samples.py`; a
`.dotx` holds `{{ documents }}`). Kept working by
`tests/test_docmanager.py`, run in its own process.

**Two modes** (`docs/deployment.md`): `example_project/settings/` is
`base.py` (apps, middleware, templates, i18n, `GENERIC`, and the env
helpers `env`, `env_bool`, `env_int`, `env_list`, `env_required`,
`database_from_url`, `redis_backends`, `mail_settings`), `dev.py` and `prod.py`, each
starting `from .base import *`. `manage.py` and `celery.py` default to
`dev`; `asgi.py` and `wsgi.py` to `prod`; the package alone raises.
`example_project/__init__.py` imports the Celery app (`celery_app`), so
the web server and `manage.py` hand tasks to the broker, not only the
worker. `redis_backends` gives the channel layer's host a
`socket_timeout` of 15: redis-py 8's default, 5 seconds, races the 5
seconds channels-redis waits for the next event and closes every quiet
WebSocket.
`prod.py` reads every secret with `env_required` (no start without
`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`,
`REDIS_URL`), assumes HTTPS unless `DJANGO_HTTPS=0`, uses
`ManifestStaticFilesStorage`, logs to stdout, SMTP when `EMAIL_HOST`
(else the console, `mail.E001` silenced as decided).
Never give a production secret a default; in `dev.py` build new lists
(`[*INSTALLED_APPS, ...]`), never mutate base's.
**Mail settings switch on the Django version**: `MAILERS` from 6.1,
`EMAIL_BACKEND` + `EMAIL_*` before - 6.1 refuses the two together, 5.2
knows only the second. `globals().update(mail_settings(backend,
host=..., port=..., username=..., password=..., use_tls=...))` writes
whichever applies (MAILERS' option names; before 6.1 an option with no
`EMAIL_*` setting raises). Never define an `EMAIL_*` name at module
level in a settings module (not even to read `EMAIL_HOST` into):
on 6.1 it is a deprecated setting. `tests/settings.py` sets a locmem
`MAILERS` on 6.1, or every mail sent warns.

`dev.py` turns on **Django Debug Toolbar** when it is installed (the
`dev` extra), outside a test runner and unless `DEBUG_TOOLBAR=0`: the
`DEBUG_TOOLBAR` setting guards the app, the middleware (first) and
`debug_toolbar_urls()` (prepended in `urls.py`). Its History panel
lists the `/api/` calls, where most queries run. Neither `prod.py` nor
`tests/settings.py` ever loads it.

**Debugging** (`docs/deployment.md#debugging`): `debug.py` at the root
is `manage.py` for a debugger - no command means `runserver --noreload
127.0.0.1:8000` (one process, so breakpoints hit), anything else is
passed through; `--reload` keeps the reloader, `--listen [host:]port
[--wait]` opens a debugpy port (Docker attach; `debugpy` is in the
`dev` extra), refused with `--reload`. `.vscode/` is committed
(`launch.json`: server, into the libraries, with reload, a command,
pytest file / `-k`, Celery worker, compound, Docker attach mapping
`/app`; `settings.json`; `extensions.json`); the rest of `.vscode/`
is ignored. Pytest under the debugger needs `--no-cov`. Tests:
`tests/test_debug_script.py`.

**Docker** (`docker/`): one `Dockerfile`, targets `dev` (every extra,
runserver), `prod` (default; Daphne `--proxy-headers`, static files
collected at build, user `app`), `proxy` (Caddy + the static files,
`docker/Caddyfile`) and `nginx` (nginx + the same, `docker/nginx/`). `docker-compose.dev.yml`: db, redis, `migrate`
(the others wait for it: beat reads its tables on start), web
(runserver, source mounted, 5678 published for debugpy), worker, beat;
the `dev` image keeps coverage data in `/tmp` (`COVERAGE_FILE`), the
mounted checkout not always being uid 1000's.
`docker-compose.prod.yml` with `--env-file docker/prod.env` (from
`prod.env.example`, never committed): db, redis, `migrate` (the others
wait for it), web, worker, beat, proxy — only the proxy published.
Vendored static files must not reference missing files (source maps):
the Manifest storage fails the image build.
`docker-compose.prod-nginx.yml`: the same stack with the `nginx` target
(`nginx:stable-alpine`, `docker/nginx/`) in place of Caddy - identical
but for `proxy` (`tests/test_docker.py`). `NGINX_MODE=https` (default,
the server's certificate: `NGINX_CERTS_DIR`, `NGINX_CERT`,
`NGINX_CERT_KEY`; refuses to start without) or `http`; `SERVER_NAME`.
`docker/nginx/django-generic.conf` is what any nginx needs: `/ws/`
upgraded with `proxy_read_timeout 1h`, `X-Forwarded-Proto $scheme` and
`X-Forwarded-For $remote_addr` set (never appended), Host,
`client_max_body_size 20m`, `proxy_pass http://$generic_upstream` (each
server block sets its own upstream). Both prod files mount the
`app-media` volume on `/app/media` (MEDIA_ROOT; the Dockerfile makes it
`app`'s) beside `app-logs`; no proxy serves it - files go through
Django (§5.17). Backups: the database **and** `app-media`. `docker-compose.host-nginx.yml`
added to either prod file: proxy under a profile (not started), web on
`127.0.0.1:${WEB_PORT}`, a one-shot `static` service copying the files
to `STATIC_EXPORT_DIR`; the server's nginx gets
`docker/nginx/host-site.conf.example`. CI job `nginx` runs `nginx -t`
on all of it.

---

## 4. Wiring a project

The full wiring with every line explained is `docs/installation.md`;
`python manage.py check` names what is missing or misplaced
(`generic.E001` request context processor, `E002` middleware before
the auth, `E003` no session auth in DRF, `E004` `site.urls` not
mounted, `E005` wiki without nh3, `W001`-`W005`, `W006` Django ≥ 6.1
without `MAILERS`, `W007` `search_rank` without `generic.search`,
`E006`/`W008` `generic.tokens` without knox / its class not in DRF, `E008` OpenAPI pages without
drf-spectacular, `W010` a model with a file field - or the wiki - and
no `MEDIA_ROOT`, `I001`; with `--deploy`, `W009` `ADMINS` empty). `site.urls`
may be mounted under a prefix (`path("app/", site.urls)`) in a project
whose root is taken; keep the namespace `site`. Without the `events`
extra the pages open no WebSocket.

```python
# settings.py
INSTALLED_APPS = [
    "daphne",                       # first: runserver speaks ASGI
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "channels",
    "rest_framework",
    "generic",
    "generic.wiki",                 # optional
    "generic.search",               # optional: searches ignore accents (§5.14)
    "myapp",
]
TEMPLATES[0]["OPTIONS"]["context_processors"] must include
    "django.template.context_processors.request"
LOGIN_URL = "site:login"
LOGIN_REDIRECT_URL = "/"
ASGI_APPLICATION = "myproject.asgi.application"
USE_TZ = True
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer",
                              "CONFIG": {"hosts": [{"address": REDIS_URL,
                                                    "socket_timeout": 15}]}}}  # > 5: redis-py 8
                                                    # InMemoryChannelLayer in dev
GENERIC = {"SITE_TITLE": "My app", "SITE_ICON": "dataset", "TABLE_PAGE_SIZE": 15}
# Translation (§12). Narrow LANGUAGES: untouched it holds every language
# Django ships, and the frame then offers no menu.
USE_I18N = True
LANGUAGES = [("en", _("English")), ("fr", _("French"))]
MIDDLEWARE = [..., "django.middleware.locale.LocaleMiddleware",         # after the session
              ..., "generic.middleware.UserLanguageMiddleware",         # after the auth
              "generic.middleware.CurrentUserMiddleware", ...]          # who the history records
```

```python
# urls.py
from django.views.i18n import JavaScriptCatalog
from generic.sites import site

urlpatterns = [
    path("admin/", admin.site.urls),
    path("jsi18n/", JavaScriptCatalog.as_view(packages=["generic"]), name="javascript-catalog"),
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("wiki/", include("generic.wiki.urls")),        # optional
    path("", site.urls),                                  # LAST: owns "/"
]
```

`asgi.py`: copy `example_project/asgi.py` (ProtocolTypeRouter, websocket
through `AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(
generic.events.routing.websocket_urlpatterns)))`, `ASGIStaticFilesHandler`
when DEBUG, production settings by default). Settings: copy
`example_project/settings/` (base/dev/prod). Docker: copy `docker/` and
`.dockerignore` (dev and prod stacks, see §3).

---

## 5. Declaring a resource — the complete reference

```python
# myapp/resources.py
from decimal import Decimal
from django.db.models import Count, Q, Sum
from django.utils.translation import gettext_lazy as _
from generic.sites import (
    Chart, ModelResource, RelatedTable, StackedInline, TabularInline, TagStyle,
    action, display, register, site,
)
from generic.sites.realtime import announce
from myapp.models import Ticket, TicketComment, TimeEntry


class CommentInline(TabularInline):
    model = TicketComment
    fields = ("author", "body", "position")
    extra = 1
    form_overrides = {"body": {"rows": 2}}


@register(Ticket)
class TicketResource(ModelResource):
    # identity and navigation
    icon = "confirmation_number"            # Material Symbols name
    group = _("Support")                    # sidebar group (default: app verbose name)
    order = 0
    description = _("Every request the desk is working on.")

    # list page
    list_display = ("reference", "title", "customer", "team", "tags",
                    "priority", "status", "due_on", "comment_count")
    search_fields = ("reference", "title", "description")
    ordering = ("-opened_at", "-pk")
    tag_fields = {
        "tags": TagStyle(color="color", background="background"),
        "status": TagStyle(colors={"open": "#2563eb", "closed": "#64748b"}),
        "priority": TagStyle(colors={"urgent": {"background": "#dc2626", "color": "#ffffff"}}),
    }
    presets = {
        _("Open work"): {
            "columns": ["reference", "title", "team", "status", "due_on"],
            "filters": {"match": "all", "conditions": [
                {"column": "status", "operator": "any_of", "value": ["open", "pending"]},
                {"match": "any", "conditions": [
                    {"column": "priority", "operator": "any_of", "value": ["urgent"]},
                    {"column": "opened_at", "operator": "older_than_days", "value": 30},
                ]},
            ]},
            "order": [["due_on", "asc"]],
        },
    }
    actions = ("close", "delete_selected")

    # forms
    fieldsets = (
        (None, {"fields": ("reference", ("title", "team"), "customer", "description")}),
        (_("Assignment"), {"fields": (("assignee", "priority"), "tags"),
                           "description": _("Who is on it.")}),
        (_("Billing"), {"fields": ("is_billable",), "classes": ("collapse",)}),
        (_("History"), {"fields": ("opened_at", "age"), "classes": ("tab",)}),
    )
    readonly_fields = ("opened_at", "age")
    inlines = (CommentInline,)

    # summary page
    detail_stats = ("hours_logged", "age")
    detail_fieldsets = ((None, {"fields": ("customer", "team", "status", "tags")}),)
    related_tables = (
        RelatedTable("time_entries", charts=("hours_by_agent",)),
        RelatedTable("comments"),
    )

    # charts
    charts = (
        Chart("by_status", title=_("By status"), type="donut", group_by="status"),
        Chart("opened", title=_("Opened"), group_by="opened_at", split_by="priority",
              stacked=True, period="week", periods=("day", "week", "month")),
    )
    list_charts = ("by_status", "opened")

    def get_list_queryset(self, request):
        return super().get_list_queryset(request).annotate(comment_count=Count("comments"))

    @display(description=_("Comments"), ordering="comment_count")
    def comment_count(self, ticket):
        return getattr(ticket, "comment_count", 0)

    @display(description=_("Hours logged"))
    def hours_logged(self, ticket):
        total = ticket.time_entries.aggregate(total=Sum("hours"))["total"] or Decimal("0")
        return total.quantize(Decimal("0.01"))

    @display(description=_("Age"))
    def age(self, ticket):
        return f"{ticket.age_in_days} d"

    @action(description=_("Close"), icon="task_alt", confirm=_("Close the selected tickets?"))
    def close(self, request, queryset):
        count = queryset.update(status="closed")
        announce(self, "bulk")             # update() sends no signal
        return _("%(count)s closed.") % {"count": count}
```

Also valid: `site.register(Model, ResourceClass)` or
`site.register(Tag, search_fields=("name",))`.

### 5.1 ModelResource attributes

| Attribute | Default | Meaning |
| --- | --- | --- |
| `icon`, `label`, `label_plural`, `description` | model verbose names | naming |
| `group`, `order`, `show_in_navigation` | app name, 0, True | sidebar; set False for child models shown only in related tables |
| `list_display` | `("__str__",)` | columns: field names, `related__paths` (single-valued), many-to-many / reverse names, resource methods, model properties, `"__str__"` |
| `list_display_links` | first column | columns linking to the row's page |
| `list_display_hidden` | `()` | columns of `list_display` the table starts without; still in the column selector - keep the default list short, park the rest here |
| `list_select_related`, `list_prefetch_related` | auto | extra joins |
| `list_per_page` | settings | first page size |
| `search_rank` | False | palette and autocompletes list the closest match first (PostgreSQL + `generic.search`); tables keep their order |
| `search_fields` | `()` | table search, autocomplete, command palette. **Give every resource used as a relation elsewhere some `search_fields`** — its FK filters and form fields then use Select2 autocomplete |
| `ordering` | model Meta | default order |
| `presets` | `{}` | named table layouts: `columns`, `filters` (a filter tree, §6), `order`, `search`, `pageLength` |
| `editable_fields` | `()` | columns that *may* be edited in a table; a name may walk single-valued relations (`"customer__name"`), and then the **related** model's change permission decides. Must be in `list_display`; a computed column raises. Turns nothing on by itself. §5.10 |
| `list_editable` | `False` | whether the resource's own list page offers those cells |
| `grids` | `()` | `Grid(...)` declarations: sets of rows corrected at once, shown by `GridView` (§5.10) |
| `actions` | `("delete_selected",)` | bulk actions (method names or functions) |
| `show_export`, `show_full_result_count` | True, True | export menu; count all rows each draw |
| `transitions`, `transition_actions` | `()`, True | FSM state fields whose `@transition`s become buttons, bulk actions (`transition:<name>`) and `<pk>/transitions/<name>/` (§5.16); the field turns read only |
| `imports` | None | `Import(fields=, key=, mode=, lookups=, defaults=, permission=, max_rows=, description=)`: an *Import* button and page (§5.15); None offers nothing and 404s the endpoint |
| `filter_row` | `"open"` | search fields under the column headers: `"open"` from the start, `"toggle"` behind a toolbar button, `False` not offered; anything else raises `ImproperlyConfigured` (same attribute on `DataTableView`) |
| `table_serializer`, `table_options` | None, `{}` | hand-written table serializer; client options |
| `tag_fields` | `{}` | fields drawn as coloured tags (table + summary + chart colours) |
| `fields`, `exclude`, `fieldsets`, `readonly_fields` | all editable | form, admin style; a tuple in `fields` or a fieldset shares a row |
| `form_overrides` | `{}` | per field: `width` (1-12), `rows`, `placeholder`, `label`, `helpText`, `widget` (`textarea`, `select`, `json`, `color`, `password`) |
| `form_field_kwargs` | `{}` | per field, DRF `extra_kwargs`: `{"token": {"write_only": True, "required": False}}`. What the field does; `form_overrides` is how it is drawn |
| `form_extra_fields` | `{}` | questions the form asks that are not model fields (`{"note": serializers.CharField(required=False)}`): write only, placed by `fieldsets`, stripped before the save, read in `save_model` as `serializer.extra_values` |
| `form_serializer` | None | hand-written `FormModelSerializer` |
| `inlines` | `()` | `TabularInline` / `StackedInline` classes |
| `view_on_site` | True | link to `get_absolute_url()` |
| `object_page` | `"detail"` | where a record opens: summary page, or `"change"` |
| `detail_fieldsets` | form fieldsets | summary page sections (may include read-only methods) |
| `detail_stats` | `()` | figures as tiles: fields, resource methods, model attributes |
| `related_tables` | `()` | `RelatedTable(...)` tabs on the summary page |
| `charts` | `()` | `Chart(...)` declarations |
| `list_charts` | `()` | chart names drawn above the list, following its filters |
| `detail_charts` | `()` | `"<related table name>.<chart name of that related resource>"` on the summary page |
| `realtime` | True | publish changes; open tables, summaries and charts refresh |
| `mailing` | True | the list may be e-mailed on a schedule (§13d), offered to holders of `generic.add_scheduledmailing` |
| `watchable` | True | users may ask to be told when a record, or any record, changes (§13a) |
| `history` | True | keep a version of every record, read back by its History tab (§13c) |
| `history_exclude` | `()` | fields left out of that version, by name |
| `trash` | False | delete moves records to a trash (the model inherits `generic.trash.Trashable`): a *Trash* page lists them to who may delete, *Restore* puts them back, *Delete for good* deletes; `empty_trash` deletes what is older than `TRASH_DAYS` (§13j) |
| `access_log` | False | record who opens a record's summary page and who downloads its files; an *Access log* link on the summary page (§13j) |
| `team_field` | None | path to the record's `generic_teams.Team` (`"team"`, `"folder__team"`, `"teams"`): every screen and endpoint narrowed to the reader's teams (§13h) |
| `scope_relations` | None (= `team_field` set) | forms of other models offer and accept only this resource's `get_queryset(request)` rows |
| `viewset_class` | `ResourceViewSet` | base viewset for the endpoint |

### 5.2 Hooks to override

| Method | Use it to |
| --- | --- |
| `get_queryset(request)` | row-level restrictions (e.g. only the user's team) — applies to every endpoint action |
| `get_list_queryset(request)` | annotate for sortable/filterable computed columns (keep `super()`) |
| `get_search_fields(request)`, `get_ordering(request)` | dynamic search/ordering |
| `has_view_permission(request, obj=None)` | default: `view` or `change` model permission |
| `has_add_permission(request)`, `has_change_permission(request, obj=None)`, `has_delete_permission(request, obj=None)` | object-level rules; `has_change_permission` False makes a create-only record (a message, a log): its add form offers no *Save and continue editing*, and Ctrl+S saves like *Save* |
| `has_module_permission(request)` | whether it appears in navigation |
| `save_model(request, serializer, change)` | stamp author: `return serializer.save(created_by=request.user)` |
| `delete_model(request, obj)` | soft delete, audit |
| `get_object_label(obj)`, `get_object_description(obj)` | palette and autocomplete labels |
| `get_initial(request)` | values an add form opens with (the query string wins); default: the reader's only team when `team_field` is a plain field |
| `get_download_name(request, obj, field)` | the name a file downloads under (default `""`: the stored name) - the name it was sent with, kept on the record |
| `may_download(request, obj, field)` | whether the reader may download that file field (default True): refused, the download 404s and the summary and tables show no link |
| `get_relation_queryset(request)` | what forms pointing at this model may choose; None = all (default unless `scope_relations`) |
| `has_record_action(request, obj, name)` | whether the record's page offers the bulk action `name` for this record now (default True). Override so a record's page shows only what applies to its state - few buttons, none answering "already done"; the list keeps them all |
| `get_record_links(request, obj)` | `ToolbarItem`s to pages built around this record (e.g. a page for correcting its rows), first on its summary; leave out any the reader cannot open. Any number: the toolbar folds the overflow into its ⋯ menu |
| `can_edit_column(request, column, obj=None)`, `save_editable(request, obj, changes)` | freeze an editable column; replace the write of edited cells (§5.10) |
| `clean_import_row(request, values, row_number)`, `save_import_row(request, serializer, instance)` | adjust an imported row before validation; replace its write (default `save_model`) |
| `create_editable(request, values, fixed)` | create the record of a row added in a grid; `values` by column, `fixed` by field (§5.10) |
| `get_detail_fieldsets(request)`, `get_detail_stats(request)` | per-request summary sections and figures |
| `get_actions(request)`, `get_row_actions(request)`, `get_table_options(request)` | per-request table behaviour |
| `get_fieldsets`, `get_fields`, `get_readonly_fields`, `get_list_display`, `get_related_tables`, `get_charts` | **built once per process** into cached serializers / bindings: override for computed-but-static declarations, not per-user variations. Per user, restrict with permissions and `get_queryset`, or subclass the resource. |

### 5.3 Decorators

```python
@display(description=_("Label"), ordering="annotation_or_path",
         boolean=True, filter_field="orm__path", filter_type="integer",
         search_field="orm__path", tags=TagStyle(...) or True,
         icons=True)   # icons: return [{"icon", "url", "label", "target"?}] - clickable icons (§5.9)
def column(self, obj): ...

@action(description=_("Label"), permissions=("change",),   # view/add/change/delete or "app.codename"
        confirm=_("Sure?"), icon="bolt", variant="default", # or "danger"
        help=_("What it does, in a sentence."))             # the button's tip on the record's page - always give one
def run(self, request, queryset):
    return None | "message" | {"message": ..., "level": "success|info|warning|error"} | Response
           | Report | {"message": ..., "report": Report} | an operation's run   # §13g
           | {"redirect": "/a/path/of/the/site/?..."}   # opens it; another site is a ValueError
```

A computed column is **not sortable or filterable** unless `ordering` /
`filter_field` point at a real ORM path — usually an annotation added in
`get_list_queryset`. Actions receive a plain queryset (not the annotated
one); after `queryset.update()` call `announce(self, "bulk")`.

### 5.4 How model fields become columns (automatic)

| Model field | Column | Filter |
| --- | --- | --- |
| CharField/TextField | text (TextField and max_length ≥ 100 wrap) | text operators; in global search |
| choices | label | Select2 multiselect include/exclude |
| BooleanField | Yes/No icon | boolean |
| IntegerField / Decimal / Float | number | comparisons |
| DateField / DateTimeField | date | date popover: between/after/before (day boundaries, active TZ) |
| ForeignKey | related label, **links to its page** if user may view | Select2 autocomplete (related resource with `search_fields`) or text on its label |
| ManyToMany / reverse FK | comma-separated labels | Select2 multiselect, no duplicate rows |
| in `tag_fields` | coloured tags, links per tag | same filter as the field |

Row menu (right-click too): Open (summary), Edit, Delete. Double-click
opens. Exports (Excel, CSV `;`) contain **every filtered row**.

**Filters are generated too — never build filter UI.** The list shows
active filters as chips in a bar. Users add them from the *Filter*
button or `F`, a column header's funnel, the **search row** under the
headers (there by default; the button beside *Filter* hides it, and that
choice is remembered per table; `filter_row` on the resource),
`name:value` words in the
search box (`status:open,pending -tags:billing hours:>=2 opened:30d
due:2026-01-01..2026-03-31 assignee:empty`), or a right click on a cell.
The search row has one field per column: text/number/date fields take
the same syntax as after `name:` (`=exact`, `^start`, `>10`, `2..8`,
`30d`, `this-month`, `empty`, `!` to exclude), a boolean is a list, a
choice or relation is a button opening the values editor. Each field
edits its column's top-level condition, so row, chips and funnels stay
in step; a column filtered in a way one field cannot say shows it in
words. Operators per type include *any of / none of / has all of*,
*contains / is / starts with*, comparisons and *between*, relative dates
(this month, last 30 days, more than N days ago), *is empty*; conditions
combine with *all*/*any* and groups. The editor lists a column's values
with counts from `facets/`. The editor applies as it changes (ticks and
operators at once, typed values as typing pauses); *Done* closes,
*Cancel* restores. The URL carries the filters on list pages.
To make a column's values listable, keep it filterable (default for
choices, relations, booleans, numbers, dates; short non-unique
CharFields in generated resources); `facetable=False` on a column option
turns it off.

### 5.5 Tags

```python
tag_fields = {
    "tags": TagStyle(color="color", background="background"),   # attributes of the related record
    "status": TagStyle(colors={"open": "#2563eb"}),               # fixed, by value
    "priority": TagStyle(colors={"urgent": {"background": "#dc2626", "color": "#fff"}}),
}
@display(description=_("Flags"), tags=True)
def flags(self, obj):
    return [{"label": "Late", "color": "#b45309"} if obj.is_late else None]
```

`TagStyle(label=, color=, background=, title=, colors=, default=)` —
attribute names or callables. One colour = tinted tag adapting to theme;
background = exact. Colours must be CSS colours (hex, named, rgb(),
hsl(), oklch()...); anything else is dropped. Store tag colours on the
model as `CharField(max_length=30, blank=True, default="")` and use
`form_overrides = {"color": {"widget": "color"}}`.

Low-level (hand-written serializer): `TagsColumn(tag_style=TagStyle(...),
choices=..., reader=callable, tag_url="/x/{id}/", filter_type=...)`.

Row shortcuts as clickable icons - a download, a preview - are a method
column too: `@display(description=_("File"), icons=True)` returning
`[{"icon": "download", "label": _("Download"), "url":
self.get_file_url(obj.pk, "attachment")}]` (Material Symbols name;
`"target": "_blank"` optional; no `url` = left out). Not filtered,
ordered or exported. The method gets the row only: what depends on the
reader is annotated in `get_list_queryset(request)`.

### 5.10 Editing in the table

```python
class TimeEntryResource(ModelResource):
    list_display = ("spent_on", "hours", "note", "ticket__status")
    editable_fields = ("hours", "note", "ticket__status")   # what MAY be edited

    def can_edit_column(self, request, column, obj=None): ...   # per row
    def save_editable(self, request, obj, changes): ...         # the write

# A table asks for it - nothing is editable until one does:
bound = site.get_related_table("example.ticket.time_entries")
bound.get_table_config(request, ticket, editable=True)    # a page of its own
RelatedTable("time_entries", editable=True)               # a summary tab
list_editable = True                                      # the list page (off)
```

**Editing is the table's decision, not the resource's.** Most tables
are read; the usual home of this is a page about one record whose rows
are corrected there (`example.views.TicketWorkView`,
`/demo/tickets/<pk>/work/`: a `SiteViewMixin` view extending
`generic/datatable.html`, table from the parent's related declaration
with `editable=True`). Do not light up list pages to get it.

**An editable table is a grid** (`editable.as_grid`, server side):
writable cells are their controls from the start, no cell is a link,
`rowActions` is empty (no menu, no double-click open), a linked cell
keeps its underlying type; selection and bulk actions stay. Writes on
change/Enter/leaving the cell; a column of another record propagates
to rows sharing that record. The grid holds the live refresh while in
use and skips its own writes (hooks on the controller in
`realtime.js`).

A cell becomes the control the form would have used - the server sends
the same field schema the form renderer reads - and one commit is one
`PATCH api/<app>/<model>/<pk>/cells/` keyed by **public column name**.
`changes` may carry fields of several models; they are resolved, each
validated by the form's own serializer, and saved in one transaction.
`save_editable` is the whole of the write and replacing it replaces the
write; calling `super()` keeps the default and adds to it. Errors come
back keyed by column so they land on the cell. See `docs/editable.md`.

**Adding rows.** A grid offers *Add a row* (option `gridAdd`, built by
`editable.add_options`) to readers with the add permission: a draft on
top, sent whole to `POST api/<app>/<model>/rows/?_related=...|_grid=...`.
The context, read by the endpoint from that parameter (`RowContext`),
decides what a new row writes and what it gets: a related table fills
the field pointing at the record (no row when the relation has no such
field); a declared grid gives `add_fields` and `add_values`. Only the
row's **own** columns are written on creation, never `a__b`.
`create_editable(request, values, fixed)` is the reprogrammable step
(default: form serializer + `save_model`). Choice tags carry `value`
beside `label`, so tag columns are editable too.

**Declared grids - any set of rows** (`generic/sites/grids.py`):

```python
from generic.sites import Grid
from generic.sites.views import GridView

class TicketResource(ModelResource):
    editable_fields = ("team", "assignee", "priority", "status")
    grids = (Grid("triage", title=_("Triage"),
                  columns=(...),                  # shown at first; list_display names
                  editable=None,                  # subset of editable_fields, None = all
                  scope="triage_rows",            # (request, queryset, argument) -> qs
                  add_fields=("reference", "title"),
                  add_values="new_triage_ticket", # (request, argument) -> {field: value}
                  allow_add=True, page_length=25),)

# urls.py - the argument, when any, comes from the address:
path("triage/", GridView.as_view(site=site, grid="example.ticket.triage"))
path("teams/<str:argument>/triage/", GridView.as_view(site=site, grid="example.ticket.triage"))
```

The browser sends `_grid=<app>.<model>.<grid>[:<argument>]`, never a
path; every table action, `cells` and `rows` read it. A scope raising
one of `ARGUMENT_ERRORS` is a 404. The scope says which rows are shown,
not which may be written (no membership check on writes). Template
`generic/grid.html` (block `grid_intro`, wrap in `.grid-intro`), per
grid `generic/grid/<app>/<model>/<grid>.html`. Bad declarations raise
`ImproperlyConfigured` at first use. Example: `/demo/triage/`.

### 5.6 Summary pages and related tables

```python
related_tables = (
    RelatedTable("tickets"),                                  # reverse FK, by accessor name
    RelatedTable("tags"),                                     # M2M, either direction
    RelatedTable("time_spent", model=TimeEntry,               # any path back
                 lookup="ticket__customer", title=_("Time spent")),
    RelatedTable("agents", columns=("name", "email"), page_length=25,
                 allow_add=True, description=_("..."), icon="groups",
                 charts=("by_team",)),
)
detail_charts = ("time_spent.hours_by_month",)
```

The tab bar handles any number: it measures what fits and puts the rest
behind a `+N` menu (`summary.js`), so nothing is declared for a record
with twenty related tables. A path crossing a many-valued relation
returns each row once.

Each tab = the related resource's full table (filters, search, exports,
bulk actions, live) narrowed by `_related=<app>.<model>.<name>:<pk>`,
resolved server-side. **The related model must be registered** (use
`show_in_navigation = False` for child models). "Add" pre-fills the
parent and returns to the tab. Tables start lazily when their tab opens.

### 5.7 Charts

```python
Chart(
    "name",                          # URL: api/<app>/<model>/charts/<name>/
    title=_("..."), description="", icon="bar_chart",
    type="bar",                      # bar line area pie donut funnel heatmap
    group_by="field__path",          # relation, choice, boolean, date (bucketed), value
    split_by="other_path",           # series / heatmap rows (optional)
    value=Sum("hours"),              # default Count("pk", distinct=True)
    value_label=_("Hours"), unit="h", decimals=1, value_format=None,  # integer decimal percent
    period="month", periods=("week", "month", "quarter"),   # day week month quarter year
    stacked=False, horizontal=False, limit=None, order=None, # "value" "-value" "label"
    colors=None,                     # {key: colour} | "attr_on_related" | TagStyle; default tag_fields
    height="18rem", options={},      # ECharts JSON overrides
    permission=None,                 # extra perm string or callable(request)
    data=None,                       # callable(chart, request, queryset, period) -> payload dict
)
```

- The chart endpoint applies the table's `filters`, `search` and
  `_related`, and aggregates over `get_queryset(request)` selected by pk.
- Above a list (`list_charts`) charts follow the table; clicking a bar or
  slice filters the table.
- On a summary page: `RelatedTable(charts=...)` in the tab, and
  `detail_charts`.
- Anywhere: `{% load generic_ui %}{% generic_chart "app.model" "name" height="20rem" %}`
  inside `<div class="chart-grid">`.
- Two aggregates over different many-valued relations must be computed
  with `data=` (joins multiply). A `data` callable returns
  `{"categories": [...], "series": [{"name", "data": [...], "type"?, "color"?, "stack"?}],
  "value": {"label", "format", "unit", "decimals"}, "dimension"?, "keys"?}`.
- Any DRF view can return `chart_payload(categories=..., series=..., type=...)`
  and be drawn by including `generic/charts/chart.html` with
  `chart={"config_id": "...", "config": {"title", "url", "height", "periods": [], "extraParams": {}}}`.

### 5.8 Inlines

`TabularInline` (rows) / `StackedInline` (cards): `model`, `fk_name`,
`fields`, `exclude`, `readonly_fields`, `form_overrides`, `extra`,
`min_num`, `max_num`, `can_delete`, `verbose_name(_plural)`,
`description`, `classes` (`("tab",)`, `("collapse",)`),
`serializer_class`. Parent and rows are saved in one request
(`_inlines`) and one transaction. Inlines answer to their own model's
permissions. Use inlines for a handful of rows; use a `RelatedTable` for
many.

### 5.9 Navigation, dashboard, search

```python
site.add_link(_("Reports"), route="reports:index", icon="bar_chart",
              group=_("Analysis"), order=0, permission="reports.view_report")

# The dashboard's hub: cards above everything, pointing at what matters
# first - inside the application or outside it.
site.add_shortcut(_("Open tickets"), url="/example/ticket/?filters=...",
                  icon="confirmation_number", description=_("..."),
                  count=lambda request: Ticket.objects.open().count(),
                  group=_("Elsewhere"), order=0,
                  permission="example.view_ticket", external=None)
# Also GENERIC["SHORTCUTS"] = [{...}], and @site.shortcut_provider for
# a hub backed by a model of the project's own. A card the user may not
# open never appears; an address that is not a path, http(s), mailto or
# tel raises where it is declared; a count that raises is simply no
# badge. NEVER reverse() in a resources.py - the URLconf is still being
# built, which is why a shortcut resolves its route at render time.
site.index_template = "myapp/dashboard.html"      # extends "generic/site/index.html"

@site.index_context
def dashboard(request):
    return {"late": Ticket.objects.filter(due_on__lt=timezone.localdate()).count()}

@site.search_provider
def reports(request, term):
    return [{"label": _("Reports"), "icon": "bar_chart",
             "items": [{"label": ..., "url": ..., "icon": ..., "description": ...}]}]
```

Dashboard template blocks: `dashboard_pinned` (wiki pins),
`dashboard_shortcuts` (the hub), `dashboard_intro`, `dashboard_extra`.

### 5.11 Pages worked out from the model (`auto`)

```python
from generic.sites import AutoResource, auto, register

auto(Supplier, related=("equipment",))                       # one line = five pages
auto(Equipment, related=("maintenances",), group=_("Equipment"),
     exclude=("notes",), list_display=("name", "state"))     # declared wins
auto(Customer, related=("tickets", "invoices"),
     related_inlines=("invoices",))                          # tables for all, tabs for some

@register(Equipment)                                          # or a class, for methods
class EquipmentResource(AutoResource):
    related = ("maintenances",)
```

`AutoResource` works out, where nothing is declared: `list_display`
(naming field first - `label_field_for`, else the first plain
CharField - then model order, no long text/JSON/files/UUIDs/secrets,
non-editable dates kept, `max_columns`=7), `search_fields` (text fields
+ `fk__<label>`), `tag_fields` (every choice field, `PALETTE` colours;
`tag_choices=False` to skip), `fieldsets` (name alone, short fields two
a row, long text/M2M full width), `detail_fieldsets` (+ kept dates),
`icon` (`ICONS` by word of the class name). **`related` is the only
thing never guessed**: each name (a reverse FK's related name or an
M2M) gives a `RelatedTable` and, for a reverse FK, a tabular inline in a
form tab (required fields + up to 6; `related_inlines` selects, `()`
none). A related model nobody registered is registered as an
`AutoResource` with `show_in_navigation=False` by
`site.complete_auto()` - at the end of `GenericConfig.ready()` (after
the framework's own screens) and in `get_urls()` - so a later explicit
declaration wins. Bad `related` names raise `ImproperlyConfigured` at
registration. `exclude` applies to list, search and form. Example: the
Equipment group (`example/resources.py`), `docs/auto.md`.

### 5.12 Rows that are not a model's (`DataResource`)

For a list of dicts - an external API's answer, a file, a computation -
**never** build a custom page: declare a `DataResource`. Read only: a
list page and a page per row, no form, no add/change/delete, no bulk
actions, no history, no watch, not in the palette.

```python
from generic.api import CharColumn, FloatColumn, TagsColumn
from generic.sites import DataResource, TagStyle, register_data

@register_data                          # or site.register_data(ServiceResource)
class ServiceResource(DataResource):
    name = "services"                   # data/services/, api/data/services/
    label, label_plural = _("service"), _("services")
    icon, group, order = "cloud", _("Support"), 6
    permission = "example.view_ticket"  # str | iterable (all) | callable(user) | None = signed in
    key = "id"                          # data/services/<key>/ - no "/" in it
    ordering = ("name",)
    columns = {                         # a column, or a type: str int float Decimal bool date datetime list
        "name": CharColumn(title=_("Service")),
        "status": TagsColumn(title=_("Status"), choices=STATUSES,
                             tag_style=TagStyle(colors={...}), filter_type="multiselect"),
        "uptime_90d": FloatColumn(title=_("Uptime (%)")),
        "regions": TagsColumn(choices=REGIONS, filter_type="multiselect",
                              filter_many=True, orderable=False),
        "description": CharColumn(title=_("Description"), visible=False),
    }
    detail_stats = ("status", "uptime_90d")
    detail_fieldsets = ((None, {"fields": ("name", "description")}), ...)

    def get_rows(self, request):        # every request: cache what is slow
        return external.services()
```

Rows are dicts or objects; `a__b` paths walk nested values. Values the
API sends as text are read as their column says (ISO dates, numbers,
`"yes"`), a list is several values (any/all/none of), missing or null
is empty. Filtering, search, ordering, facets and exports run in Python
(`generic.api.rows`: `RowsDataTableViewSet`, `RowList`, `matches(q,
row)` reading the same `Q` the filter engines build - same whitelist,
400 on undeclared names). Other options: `list_display_links`,
`list_per_page`, `show_export`, `filter_row`, `table_options`,
`label_field`, `show_in_navigation`, `description`. Override `get_row`
to fetch one row directly.

Between data resources (both registered; checked in `get_urls`):
`related_tables = (RelatedRows("incidents", resource="incidents",
field="service"),)` - a tab of the other resource's own table on the
row's page, narrowed to the rows whose `field` holds this row's key, or
`rows=lambda request, row: api.incidents_of(row["id"])`; the table
sends `_related=<parent>.<tab>:<key>`, resolved through the parent's
declaration (400 unknown tab, 404 unknown key, parent's permission
needed), the pointing column hidden; `title`, `icon`, `description`,
`columns`, `page_length`. `links = {"service_name": RowLink("services",
key="service")}` (or `{"service": "services"}`) - that column, and the
value on the row's page, lead to the other resource's row, for readers
who may open it (hidden `_link_<name>` field fills the URL). Date
columns of data resources format text timestamps like a model's
(ISO in the active zone, drawn in the reader's language). Pages reuse
`generic/resource/list.html` and `detail.html`; override with
`generic/data/<name>/list.html`. Pages of its own: §5.13 (the runbook).
Example: *External services* (`example/external.py`,
`ServiceResource`), `docs/data.md`.

### 5.13 Pages of a resource's own (`@page`, `ResourcePage`)

When the generated pages are not enough - a map, a timeline, a gallery,
a report, a long text, JSON - **declare the page on the resource**, never
mount a view by hand. Any resource (`ModelResource`, `AutoResource`,
`DataResource`). The content is the project's; the framework gives the
address, sign-in, permission, record lookup, frame, title, breadcrumbs
(list › record › page) and the button.

```python
from generic.sites import ResourcePage, ResourcePageView, page

class CustomerResource(ModelResource):
    @page(title=_("Customer map"), icon="map", navigation=True,
          template="myapp/pages/customer_map.html")    # extends generic/resource/page.html
    def map(self, request):                              # <app>/<model>/map/
        return {"customers": self.get_list_queryset(request),
                "table": self.get_page_table_config(request, "map")}

    @page(button=False)                                   # any response passes through
    def geojson(self, request):
        return JsonResponse(...)

    @page(title=_("Letters"), detail=True, template="...")  # <app>/<model>/<pk>/letters/
    def letters(self, request, customer):                   # record already found + allowed
        return {...}

class TicketResource(ModelResource):
    pages = (ResourcePage("timeline", view=TicketTimelineView, detail=True,
                          title=_("Timeline"), icon="timeline", row_menu=True),)

class TicketTimelineView(ResourcePageView):   # TemplateView; self.resource/page/object set
    template_name = "myapp/pages/ticket_timeline.html"
```

Options (decorator and `ResourcePage`): `name` (slug; default method
name with dashes; not add/change/delete/detail/list), `view`
(`ResourcePage` only: `ResourcePageView` subclass gets everything; any
other view/function gets the guard, then runs with `pk`/`key`),
`title`, `detail`, `icon`, `description`, `template` (required when a
method returns a context), `permission` (after the resource's view
permission: `"change"`/`view`/`add`/`delete`, a permission string,
several, or `callable(user)`; object rules: override
`has_page_permission(request, page, obj)`), `button` (list page, or
record page - its form when no summary), `row_menu` (record pages),
`navigation` (resource pages), `methods` (`("get","post")` for a form).
Routes `site:<app>_<model>_<name>` / `site:data_<name>_<name>`, before
the record's route; `resource.get_page_url(name, obj=None)`. Checked at
registration (`check_pages`). In templates: `{% include
"generic/components/table.html" with config=... id=... %}` for a table,
`{% generic_chart %}` for a chart, `.prose` for long text; styles in
`extrastyle`. Example: `example/pages.py` (customer map + GeoJSON,
ticket timeline, service runbook), `docs/pages.md`.

### 5.14 Searches that ignore accents (`generic.search`)

```python
INSTALLED_APPS = [..., "generic", "generic.search", ...]    # then migrate

# myapp/migrations/00xx_search_indexes.py - PostgreSQL only, a no-op elsewhere
from generic.search.operations import CreateSearchIndex
operations = [CreateSearchIndex("ticket", ("reference", "title"), name="ticket_search")]

# a project's own search agrees with the framework's:
from generic.search import fold, normalize, text_lookup
Ticket.objects.filter(**{text_lookup("title"): term})   # title__unaccented__icontains
```

- Installed, **every** text match sets accents aside: table search,
  column text filters (contains/is/starts/ends), facets value search
  (choice labels by `normalize`), palette, resource and
  `AutocompleteView` autocompletes, `GenericListView ?q=`, wiki,
  `DataResource` rows (`rows.py`: `TRANSFORM` in `TRANSFORMS`, `fold`).
  Not installed: exactly the old `icontains`. Never write
  `f"{field}__icontains"` in the framework - call `text_lookup`.
- The `unaccented` transform is registered on every `Field`, bilateral,
  output text: PostgreSQL `generic_unaccent((col)::text)` (an
  `IMMUTABLE` wrapper over `unaccent`, created with the `unaccent` and
  `pg_trgm` extensions by `InstallUnaccent`, the app's migration -
  trusted extensions, the database owner suffices), SQLite a Python
  function registered on `connection_created`, others the bare column.
- `CreateSearchIndex` is a migration operation, not a `Meta.indexes`
  entry, because it must not exist outside PostgreSQL: one GIN
  `gin_trgm_ops` index per field on `UPPER(generic_unaccent(col))`.
- `search_rank = True`: `resource.rank_search_results(request,
  queryset, term)` orders by `word_similarity` (fields crossing a
  many-valued relation skipped); a no-op off PostgreSQL. See
  `docs/search.md`.

### 5.15 Imports (`Import`)

```python
from generic.sites import Import

class TicketResource(ModelResource):
    imports = Import(fields=("reference", "title", "customer", "status", "tags"),
                     key="reference",                 # found -> updated; None: create only
                     lookups={"customer": "code"})    # default: related naming field
```

- Off by default. Page `site:<app>_<model>_import` (`ResourceImportView`,
  `generic/resource/import.html`, Alpine `resourceImport` in
  `js/imports.js`), button on the list for `resource.can_import(request)`
  (declared + add or change as the mode needs + `permission`).
- Endpoints: `GET import/schema/`, `GET import/template/` (xlsx),
  `POST import/` multipart `file`, `mapping` (JSON list aligned with the
  headers), `commit`. Answer: `headers mapping unmatched missing rows
  counts errors preview committed`.
- Headers match name / translated title / export title / verbose name,
  accents and case aside (`simplify`). Cells: choices by value or label
  in any `LANGUAGES`, yes/no words, Excel/ISO/localized dates, `3,5`,
  relations by `text_lookup(lookup, "iexact")` **within the related
  resource's `get_queryset(request)`**, M2M comma-separated. Rows:
  resource form serializer (partial for updates; empty cell = keep),
  `has_change_permission(request, obj)` per update.
- One transaction; any error or `commit=false` rolls back (the preview
  is a real dry run). `acting_as(user, source="Import <file>")`, live
  events folded by `realtime.batch(resource)`. Declaration errors raise
  at registration (`check_import`) or first use (form fields). See
  `docs/imports.md`.

### 5.16 State machines (`transitions`)

```python
# models.py - django-fsm-2
status = FSMField(choices=Status.choices, default=Status.OPEN)

@transition(field=status, source=[Status.OPEN], target=Status.RESOLVED,
            permission="app.resolve_ticket",            # or callable(instance, user)
            conditions=[has_owner],
            custom={"label": _("Resolve"), "icon": "task_alt",
                    "confirm": _("Sure?"), "variant": "danger",
                    "fields": ("resolution",)})           # asked in a dialog
def resolve(self): ...

# resources.py
class TicketResource(ModelResource):
    transitions = ("status",)
```

- Offered when: `has_change_permission(request, obj)` + the
  transition's permission + conditions + source state
  (`transitions.may_take`). The summary JSON has `transitions` and
  `urls.transitions`; `detail.html` draws them, `summary.js` `take()`
  (confirm, or `Generic.dialogs.fields`), POST
  `<pk>/transitions/<name>/` -> the new summary.
- `transitions.take()`: row lock (`select_for_update(of=("self",))`),
  409 if the state moved or a condition fails, 403, 404, 400 (fields
  through the form serializer, partial); `acting_as(source=
  "Transition: <label>")`. Bulk: transitions without `fields`, each
  row through `take`, skipped ones counted.
- The state is read only: added to `get_readonly_fields`, refused in
  `editable_fields`, so not importable. Metadata only in `custom`;
  checked at registration (`get_transitions`). See
  `docs/transitions.md`.

### 5.17 Files (`FileField`, `ImageField`)

```python
attachment = models.FileField(_("attachment"), upload_to="tickets/%Y/%m/", blank=True,
                              validators=[FileExtensionValidator(["pdf", "png"])])
# settings: MEDIA_ROOT = BASE_DIR / "media" (W010 when empty); no MEDIA_URL
```

- Nothing to declare: a file field in `fields`/fieldsets is a chooser
  (`widgets.js` fileWidget: link to the current file, *Choose a file* /
  *Replace*, *Remove* when `blank=True`, *Cancel*; refused locally over
  `maxSize` or outside `accept`). Schema keys: `accept` (the
  `FileExtensionValidator`, or `image/*`), `maxSize`
  (`GENERIC["FILE_MAX_SIZE"]`, 10 MB). The value everywhere - record,
  table cell (`FileColumn`, size `null`), summary (`type: "file"`) -
  is `{"name", "url", "size"}` or `null`; exports write the name.
- Sent: JSON as before without a new file (an untouched file is left
  out; removed = `null`); with one, multipart - `_payload` = the same
  JSON (`_inlines` included, files left out) + a part per file, read
  back by `MultiPartJSONParser` into a plain dict. Classic multipart
  (no `_payload`) still works. `FORM_PARSERS` on every resource
  viewset and `ModelFormViewSet`.
- `FormFileField`: `null`/`""` clears a `blank=True` field (stores
  `""`), refused on a required one; size checked; model validators
  apply. Replaced or removed files are **never deleted** (the history
  names them).
- Download: `GET api/<app>/<model>/<pk>/files/<field>/`
  (`site:api_<app>_<model>-file`, `resource.get_file_url(pk, field)`):
  `get_object()` (view permission, row restrictions), only fields in
  `resource.get_file_fields(request)` (form, summary, list), 404 when
  empty or missing from storage, any storage; raster images `inline`,
  all else (HTML, SVG) `attachment`; always `nosniff` + `CSP: sandbox`.
  The serializer context carries `file_url` (`FILE_URL`), set by
  `ResourceViewSet.get_serializer_context`.
- Refused: file fields in `editable_fields` (`ImproperlyConfigured`),
  in `Import(fields=...)`; read-only in inline rows.
- Wiki images: `POST api/generic/wiki/images/` (multipart `file`;
  `add_wikipage` or `change_wikipage`; png/jpeg/gif/webp by extension
  **and** magic bytes, no SVG; ≤ FILE_MAX_SIZE) → `{"id", "url":
  "/wiki/images/<id>/"}`; `GET wiki/images/<id>/` for any signed-in
  reader (inline, nosniff, `Cache-Control: private, max-age=86400`).
  The editor's *Insert an image* offers *Upload an image* beside the
  address. See `docs/forms.md#files`, `docs/wiki.md#images`.
- Wiki files: `POST api/generic/wiki/files/` (multipart `file`; same
  permissions; any type, ≤ FILE_MAX_SIZE, not empty) → `{"id", "url":
  "/wiki/files/<id>/", "name", "size"}`; `GET wiki/files/<id>/` always
  `attachment` under its original name (nosniff, CSP sandbox). In a
  page: `<p class="wiki-file"><a href=...>name</a></p>` (Quill blot
  `wikiFile`, a block embed; `sanitize.py` allows `wiki-file` on `p`).
  The editor uploads on the paperclip, a drop or a paste (images to the
  image endpoint, the rest to files), at the drop point. Toolbar arrows
  / Alt+Up/Down move the cursor's line (`moveLine` in `wiki.js`).
  `WikiPage.attachments()` / `attachments_in(html)` read the uploads a
  page links to, in order; `attachments` in the page's API and the
  page's context (listed under the text). See `docs/wiki.md#files`.
- Several wikis: `generic_wiki.Wiki` (`name`, `slug` unique, not
  `api`/`images`/`files`, `description`, `position`); `WikiPage.wiki`
  (FK, CASCADE; `(wiki, slug)` unique; saved without one: the parent's,
  else `Wiki.objects.default()`, the first - migration 0005 made
  "Wiki" at `main` and put every old page in it). Routes: `wiki/`
  (`index`: the list, or straight into the only wiki for a reader
  without `add_wiki`), `wiki/<wiki>/` (`wiki`: its first page; an
  unknown slug that is a page's slug 301s to it - old addresses),
  `wiki/<wiki>/<slug>/` (`page`), `wiki/<wiki>/export.pdf` (`pdf`).
  API `wiki/api/wikis/` (add/change/delete_wiki; `page_count`,
  `pdf_url`), `pages/?wiki=<id>`; a page's `wiki` is set on create
  only, its parent must share it. Every read goes through
  `Wiki.objects.readable_by(user)`, narrowed by
  `GENERIC["WIKI_ACCESS"]` (`(user, wikis) -> wikis`). Writing pages:
  `Wiki.objects.writable_by(user)`, those read narrowed by
  `GENERIC["WIKI_EDIT_ACCESS"]` (same signature; the page view's `can`
  and `WikiPermission.has_object_permission` / `perform_create` -
  403); the wikis themselves still answer to the wiki permissions only.
  Never build a page's URL without its wiki: `page.get_absolute_url()`.
- Wiki PDF: `generic.wiki.pdf.render(wiki, base_url=)` -> bytes;
  cover, table of contents (bookmarks), pages depth-first; uploaded
  images embedded (data URIs), web images named and never fetched,
  files listed. Fonts: `WIKI_PDF_FONTS` or DejaVu/Liberation/Arial
  found on disk, else Latin-1 core fonts. `pdf.available()` false
  without fpdf2: no button, `export.pdf` 404. See `docs/wiki.md#pdf`.

---

## 6. URLs and endpoints (generated)

Pages (namespace `site`): `site:index`, `site:login`, `site:logout`,
`site:account`, `site:notifications`, and per resource
`site:<app>_<model>_list | _add | _detail | _change | _delete`
(paths `<app>/<model>/`, `add/`, `<pk>/`, `<pk>/change/`, `<pk>/delete/`).
Per data resource `site:data_<name>_list | _detail` (`data/<name>/`,
`data/<name>/<key>/`) and `api/data/<name>/` with `facets/`, `export/`,
`export-csv/`, `<key>/summary/` (route names `site:api_data_<name>-...`).

API (route names `site:api_<app>_<model>-<action>`):

| Request | Does |
| --- | --- |
| `GET api/<app>/<model>/` | rows, DataTables protocol (`draw`, `start`, `length`, `search[value]`, `order[i]...`, `filters` JSON tree, `_related`) |
| `GET .../facets/?column=<name>` | a column's values with counts under the other filters (`q=` search, `ids=` labels), or `{"kind": "range", min, max, empty}` |
| `POST api/<app>/<model>/` | create (JSON, `_inlines`; or multipart `_payload` + a part per file, §5.17) |
| `GET/PATCH/DELETE api/<app>/<model>/<pk>/` | read (with `_display`, `_label`, `_inlines`), update, delete (refused with reason when protected) |
| `GET .../<pk>/summary/` | summary JSON |
| `GET .../<pk>/files/<field>/` | one of the record's files, permission-checked (§5.17) |
| `GET .../<pk>/history/` | the record's versions, newest first (`limit`, `offset`); 404 where the model keeps none |
| `GET .../form-schema/` | form schema |
| `GET .../<pk>/deletion-preview/` | cascade preview |
| `GET .../export/`, `.../export-csv/` | every filtered row |
| `POST .../actions/` | `{"action", "ids": [...]}` or `{"action", "all": true}` |
| `GET .../import/schema/`, `.../import/template/`, `POST .../import/` | where `imports` is declared (§5.15) |
| `GET .../<pk>/transitions/`, `POST .../<pk>/transitions/<name>/` | where `transitions` is declared (§5.16) |
| `GET .../autocomplete/` | `?q=&page=` or `?ids=1,2` |
| `GET .../charts/<name>/` | chart payload, `?period=` + table params |

`filters` = `{"match": "all"|"any", "conditions": [condition or group, ...]}`,
condition = `{"column": "<public name>", "operator": "...", "value": ...}`,
groups nested ≤ 4, ≤ 50 conditions. Operators:
text `contains not_contains equals not_equals starts_with ends_with`
(value: string or list = any of); numbers `equals not_equals gt gte lt lte`,
`between` `{"from","to"}`; dates `on not_on before after on_or_before
on_or_after`, `between` `{"from","to"}`, `today yesterday this_week
last_week this_month last_month this_quarter last_quarter this_year
last_year` (no value), `last_days next_days older_than_days` (N);
boolean `is_true is_false`; multiselect `any_of none_of all_of` (list of
keys); every type `empty not_empty`. The older flat `advanced_filters`
(`{"<column>": {"operator": "include"|"exact"|..., "value": ...}}`) is
still accepted. Build filter URLs for links with `filters=` JSON.

Framework API under `api/generic/`: `account/preferences/`,
`account/profile/`, `watches/` (`status/`, `toggle/`), `saved-views/`,
`notifications/` (`unread-count/`, `read-all/`, `<pk>/read/`).

---

## 7. Front end, for custom pages

### Templates

Every page extends `generic/base.html`. Blocks: `title`, `favicon`
(the include `generic/includes/favicon.html`, also used by the sign-in
frame and the popup response: override that file to change the icon),
`styles`, `extrastyle`, `extrahead`, `bodyclass`, `sidebar`, `header`,
`breadcrumbs`, `usertools`, `messages`, `page_header` (`page_eyebrow`,
`page_title`, `page_subtitle`, `object_tools`, `toolbar`), `content`,
`footer`, `scripts`, **`components`** (page Alpine components — scripts
that must load before Alpine), `extrajs`.

Override a generated page per model:
`templates/generic/resource/<app>/<model>/detail.html` (or `list.html`,
`form.html`), or per app `generic/resource/<app>/detail.html`.

A custom page in the frame:

```python
from django.views.generic import TemplateView
from generic.sites import site
from generic.sites.views import SiteViewMixin
from generic.views.toolbar import Breadcrumb, ToolbarItem

class WorkloadView(SiteViewMixin, TemplateView):
    template_name = "myapp/workload.html"
    page_title = "Workload"

    def has_permission(self):
        return self.request.user.has_perm("myapp.view_task")

    def get_breadcrumbs(self):
        return [Breadcrumb(label="Workload")]

    def get_toolbar_items(self):
        return [ToolbarItem(url="...", label="Export", icon="download", variant="primary")]

# urls.py:  path("workload/", WorkloadView.as_view(site=site), name="workload")
site.add_link("Workload", route="workload", icon="monitoring", group="Planning")
```

Toolbar buttons stay on one line: what does not fit folds into a ⋯
menu, from the end of the list backwards (`pageToolbar` in `ui.js`
measures; `layout_toolbar` in `generic/views/toolbar.py` splits).
`ToolbarItem(placement=...)`: `"auto"` (default; a `variant="primary"`
button is pinned), `"bar"` (never folds), `"menu"` (always in ⋯).
Anything else raises `ValueError`. Never hand-build a "More" dropdown.

### CSS classes you may use (no new colours: use tokens)

`card`, `card__header`, `card__title`, `card__description`, `module`,
`stack`, `cluster`, `grid-auto`, `chart-grid`, `muted`, `empty-state`,
`button`, `button--primary`, `button--danger`, `button--ghost`,
`button--sm`, `icon-button`, `icon-button--sm`, `badge`, `badge--success|warning|danger|info`,
`tag`, `tag-list`, `callout callout--info|warning|danger|success`,
`input`, `input--sm`, `object-table`, `spinner`, `sr-only`, and — after
linking `generic/css/summary.css` in `extrastyle` — `stat`, `stat__label`,
`stat__value`, `summary__stats`. Icons: `{% icon "name" "icon--sm" %}`.
Tokens: `var(--color-accent)`, `--text-primary|secondary|muted`,
`--surface-raised|sunken|page`, `--border-color`, `--space-1..7`,
`--font-size-xs..xl`, `--border-radius(-sm|-lg|-pill)`.

### JavaScript (`window.Generic`)

- `Generic.api.get(url, params)`, `.post(url, body)`, `.patch`, `.put`,
  `.delete` → Promises of JSON; errors are `ApiError` with `.message`,
  `.status`, `.data`. CSRF handled.
- `Generic.operations.post(url, body)` / `.handle(answer)`: an answer
  carrying `operation` (§13g) drawn as a card with its report tree,
  followed until the run ends; anything else a toast.
- `Generic.toast(message, "success|info|warning|error")`,
  `Generic.flash(message, level)` (after navigation),
  `Generic.dialogs.confirm({title, message, confirmLabel, variant})`.
- `Generic.t(text)`, `Generic.format("%(n)s", {n: 1})`, `Generic.ready(fn)`,
  `Generic.debounce(fn, ms)`, `Generic.isSafeUrl(url)`, `Generic.config()`,
  `Generic.formatSize(bytes)`.
- `Generic.events.subscribe(topic)`, `Generic.events.on(type, handler)` → unsubscribe fn.
- `Generic.colors.clean(css)`, `.readableOn(background)`.
- `Generic.charts.customize(name | "*", (option, payload, theme) => option)`.
- Alpine: `x-data="apiResource('/api/...', {param: 1})"` exposes `data`,
  `loading`, `error`, `load(extra)`, `reload()`, `send(method, url, body)`.
- A table's filters from page code: `table.genericDataTable.addCondition({column, operator, value})`,
  `.setColumnCondition(...)`, `.setFilters(tree)`, `.clearFilters()`, then `.redraw()`;
  listen to `generic:filters-change` on the table. `.setFilterRow(true|false)`
  shows or hides the search row.
- Tables on custom pages: `<table class="js-generic-datatable display" data-config="id">`
  with `{{ table_config|json_script:"id" }}` where config = `{"url", "columns", "options"}`
  (e.g. `resource.get_table_config(request)`), in a template extending
  `generic/datatable.html`.
- JS files: plain ES5-style IIFE, **ASCII only** (write `—` not `—`),
  no modules, no build. Values reach the DOM through `textContent`/`x-text`,
  never `innerHTML`/`x-html` with data; URLs through `Generic.isSafeUrl`.

---

## 8. Real-time events, notifications, messages

**Who hears what** (`docs/events.md`): anything addressed to a
*person* is a **notification** (bell, *Notifications* page, toast on
open pages; e-mail per `UserPreferences.notification_channel`) - from
watches, tasks, admin messages or project code, all through
`generic.delivery.deliver`. Channels are only `notification`, `mail`
(+ `page` for tasks); there is **no** `event` channel since 1.0.0 (a
task declaring it raises). **Events** are wiring for open pages,
addressed to nobody; never make one the only way a person learns
something. Planned restarts keep their own banner (§13).

Resources publish `resource.changed` on topic `resource.<app>.<model>`
automatically (payload `{resource, change, id}`); tables, summary pages
and charts subscribe themselves. For custom streams:

```python
# myapp/events.py (imported from AppConfig.ready())
from generic.events import allow_staff, register_topic, publish_to_topic, publish_to_users
register_topic("project.{project_id}", permission=lambda user, topic, params: ...)
publish_to_topic("project.{project_id}", "project.changed", {"id": 3}, parameters={"project_id": "3"})
publish_to_users([user], "report.ready", {"url": "..."})
```

Durable notifications: `Notification.objects.create(user=..., title=..., body=..., level=..., url=...)`
(publishes itself) or `publish_notifications(Notification.objects.notify(users, title=...))`.
Delivery waits for the transaction commit. Through the reader's own
channels and language:

```python
from generic.delivery import by_preference, deliver
readers = User.objects.filter(...).select_related("generic_preferences")  # one query
for channels, group in by_preference(readers).items():
    deliver(group, channels=channels, url="/x/",
            message=lambda: (gettext("Title"), gettext("Body"), NotificationLevel.INFO))
```

`mail` sends one e-mail per address (never one mail to all), through
`send_mass_mail` and Django's default mailer, with nothing but the
messages - no `fail_silently` (deprecated in 6.1, gone in 7.0, where
the `TypeError` would be swallowed with the mail). Failures are logged,
never raised; `generic.W006` names a project on Django ≥ 6.1 without
`MAILERS`.

**Messages** (`generic.Message`, `generic/events/models.py`,
`messages.py`, `resources.py`): *People › Messages*, a `ModelResource`
registered by `register_screens()` (`SHOW_MESSAGES`). Fields: title,
body, level, url (site path or http(s), checked), `everyone` /
`users` / `groups` (active accounts only, distinct), `delivery`
(`preference` | `in_app` | `email` | `both`), `sender`, `sent_at`,
`recipient_count`; `notifications = GenericRelation(Notification)` -
deleting a message withdraws its notifications. Sent on commit from
`save_model`; never changed (`has_change_permission` False). From code:
`send(Message.objects.create(...))`. Permissions: `add_message` to
write (also a *Write a message* button on the notifications page),
`view_message`, `delete_message`.

---

## 9. Settings (`GENERIC = {...}`)

`SITE_TITLE`, `SITE_HEADER`, `SITE_ICON`, `SITE_URL`, `SHOW_ADMIN_LINK`,
`THEME` (`{"--ui-hue": "150", "--ui-colorfulness": "1", "--ui-tint": "0.35",
"--ui-contrast": "0", "--ui-stripes": "0.6"}`), `NAVIGATION`,
`SEARCH_RESULTS_PER_RESOURCE`, `TABLE_PAGE_SIZE`, `TABLE_DATETIME_FORMAT`
(None: date/datetime cells travel as ISO in the active zone and
`datatables/core.js formatStamp` draws them in `<html lang>`; a
strftime string fixes the text),
`TABLE_MAX_PAGE_SIZE`, `TABLE_ALLOW_UNLIMITED_PAGE_SIZE`,
`EXPORT_CHUNK_SIZE`, `EXPORT_MAX_ROWS`, `EXPORT_DATE_FORMAT`,
`EXPORT_DATETIME_FORMAT`, `IMPORT_MAX_ROWS`, `IMPORT_MAX_FILE_SIZE`,
`IMPORT_PREVIEW_ROWS`, `AUTOCOMPLETE_PAGE_SIZE`,
`AUTOCOMPLETE_MIN_INPUT_LENGTH`, `FORM_DEFAULT_SECTION`,
`FORM_RELATED_POPUP_WIDTH/HEIGHT`, `FORM_CHOICES_LIMIT`, `FILE_MAX_SIZE`,
`EVENTS_WEBSOCKET_URL`, `EVENTS_BROADCAST_GROUP`,
`EVENTS_RETENTION_DAYS`, `EVENTS_DISPATCH_ON_COMMIT`, `SHOW_PEOPLE`,
`SHOW_MESSAGES`, `SHOW_TASKS`, `SHOW_MAILINGS`, `API_TOKEN_DEFAULT_DAYS`,
`API_TOKEN_MAX_DAYS`, `API_TOKEN_LIMIT_PER_USER`,
`MAILING_MAX_ATTACHMENT_SIZE`, `HISTORY`, `OPERATION_FALLBACK`,
`WIKI_ACCESS`, `WIKI_EDIT_ACCESS`, `WIKI_PDF_FONTS`, `TRASH_DAYS` (30;
None keeps everything), `ACCESS_LOG_RETENTION_DAYS` (None),
`LOGIN_MAX_ATTEMPTS` (5; None turns the lock off),
`LOGIN_LOCKOUT_MINUTES` (15).
Read them via `from generic.conf import generic_settings`.

---

## 10. Modelling guidance (so the generated screens are good)

- Every model: `__str__`, `Meta.verbose_name(_plural)` with
  `gettext_lazy`, `Meta.ordering`, `verbose_name` on every field.
- `related_name` on every FK/M2M — it becomes the `RelatedTable` name.
- Status-like fields: `models.TextChoices` + `tag_fields` colours.
- Money/hours: `DecimalField`; quantize sums (`Decimal("0.01")`) because
  some databases drop trailing zeros.
- Choose `on_delete` deliberately: `PROTECT` for records that must stay
  referenced (the delete page explains the refusal), `CASCADE` for
  owned children (the delete page previews them), `SET_NULL` for optional
  links.
- Labels users pick from (`Tag`, `Category`, `Status` tables): add
  `color`/`background` CharFields to draw them as tags.
- Add `get_absolute_url` only if there is a public page ("View on site").
- Put permissions in groups created by a seed/migration; model
  permissions `view/add/change/delete` are what the screens obey.

## 11. Testing conventions

- **Every page is already covered**: `tests/test_pages.py` is a
  `generic.testing.PageSweep` subclass: it walks the URLconf and opens
  each page three ways (superuser → 200 or `expected`; a user with no
  permissions and a stranger → anything below 500), plus every
  generated endpoint per resource — rows, form schema, summary,
  history, each column's `facets/`, both exports, every chart, the
  import's schema and template, a record's transitions — and the
  OpenAPI description. A new page needs no new test; a page whose
  address needs a value adds a record to the `records` fixture (by model
  label) or teaches `value_for`. Framework models are pooled by the base
  (`framework_records`). **Every new project gets one** (docs/testing.md).
- pytest + pytest-django; `pytestmark = pytest.mark.django_db`.
- Use Django's `client.force_login(user)` / `admin_client` for pages and
  the JSON API; assert on JSON and `response.context`, not on scraped HTML.
- Per resource, at minimum: list endpoint returns rows (`draw=1`), a
  filter narrows (`filters` tree), permissions (403 without `view`),
  summary endpoint (`<pk>/summary/`), each custom action, each chart
  (`charts/<name>/` payload), each `@display` column value.
- Build explicit, named fixture data (not random) so assertions name rows.
- One behaviour per test, named as a sentence.
- Quality gates: `black --check .`, `isort --check-only .`, `flake8`,
  `pytest` (coverage ≥ 80%).
- **Browser tests** (`tests/browser/`, docs/testing.md): the example
  driven through a real Chromium - Python Playwright via
  pytest-playwright, against pytest-django's `live_server`; no Node.
  Opt-in: every test there is marked `browser`, `addopts` deselects it
  (`-m "not browser"`), and without the `browser` extra the folder is
  not collected; run `pytest tests/browser -m browser --no-cov`
  (`PLAYWRIGHT_CHROMIUM_EXECUTABLE` names another Chromium; failure
  screenshots in `test-results/`, CI job *Browser tests*). Its
  conftest: `desk` (25 tickets SD-1001..SD-1025), `admin`, `viewer`,
  `sign_in(user)` (a `force_login` session as a cookie), and an
  autouse console guard failing any test whose page raised or logged
  an error (`console.allow(status, path)` for an expected refusal);
  SQLite in a file (the server's threads must not share one in-memory
  connection), the CSRF middleware added, no WebSocket, events from the
  tests' own thread dropped, `DJANGO_ALLOW_ASYNC_UNSAFE`. A behaviour
  of the JavaScript gets a scenario there, waiting with `expect`,
  never `time.sleep`.
- CI runs Django 5.2 on Python 3.10 and 3.11, the latest Django on
  3.12 and 3.13. Where the two Djangos differ, switch on
  `django.VERSION`, never on the Python version, and never name in
  `filterwarnings` a warning class one of them lacks: pytest refuses to
  start. A `DeprecationWarning` from `generic.*` fails the suite;
  pending ones (Django's `RemovedInDjango70Warning` on 6.1, DRF's own)
  vary with what is installed, so a test pins the one that matters
  instead (`tests/test_delivery.py`: sending mail warns of nothing).

## 12. Translation (English and French ship)

- Declarations use `gettext_lazy as _`; views and actions `gettext`;
  templates `{% translate %}` / `{% blocktranslate %}`; JavaScript
  `Generic.t()` / `core.t()` against the `javascript-catalog` route.
  Named placeholders only (`%(count)s`), never `%s`.
- A short label that could mean something else elsewhere takes a
  context: `pgettext_lazy("ticket status", "Open")` — the framework's
  own *Open* is the row action. One catalog entry cannot hold both.
- The framework's catalogs live in `generic/locale/fr/LC_MESSAGES/`
  (`django` for pages, `djangojs` for the browser), the example's in
  `example/locale/fr/LC_MESSAGES/`; the `.mo` are committed and CI
  checks they match.
  `django-admin makemessages -l fr` / `compilemessages`, or
  `python scripts/compile_messages.py` where GNU gettext is missing.
- A page's language: the user's `UserPreferences.language`
  (`generic.middleware.UserLanguageMiddleware`), else the
  `django_language` cookie, else `Accept-Language`, else
  `LANGUAGE_CODE`. The account menu and the preferences form both set
  it; both refuse anything outside `LANGUAGES`.
- A new project string belongs in the project's own catalog
  (`LOCALE_PATHS`), not in `generic/locale/`. See `docs/i18n.md`.

## 13. Planned restarts, help and the frame

```python
from generic.maintenance import announce_restart, cancel_restart

announce_restart(scheduled_at=when, duration_minutes=10, is_manual=False,
                 comment_en="...", comment_fr="...", created_by=request.user)
```

- One row (`generic.RestartAnnouncement`) warns everyone three times —
  now (a stored notification), `MAINTENANCE_REMINDER_SECONDS` before,
  `MAINTENANCE_IMMINENT_SECONDS` before — as broadcast events
  `maintenance.announced|reminder|imminent|restarting|cancelled`. The
  frame draws a banner (`restartBanner`, `maintenance.js`), including on
  a page opened after the announcement (`chrome.client.maintenance`).
- `is_manual=False` restarts the server at the hour:
  `MAINTENANCE_RESTART_COMMAND`, else the dev reloader, else SIGTERM.
  `MAINTENANCE_RESTART=False` turns it into warnings only.
- Page `site:restart`, endpoints `generic:restart` (GET/POST/DELETE) and
  `generic:restart-schema`; all gated on
  `generic.add_restartannouncement`. See `docs/maintenance.md`.
- **Help and changelog**: pages `site:help` and `site:changelog` read
  files the project already keeps — `LICENSE` and `CHANGELOG.md` at its
  root (`GENERIC["LICENSE_FILE"]`, `["CHANGELOG_FILES"]`,
  `["HELP_LINKS"]`, `["HELP_TEXT"]`, `["VERSION"]`). The changelog is
  parsed as Keep a Changelog and rendered escaped, never as HTML -
  only its `backquoted` parts become `<code>` (`inline_code` filter). Both
  are in the account menu; see `docs/ui.md`.
- **The size of the interface**: every token in rem, the root font size
  the browser's; no size preference (removed in 1.0.0 - the browser's
  text size and zoom do it). A project changes its root size in its own
  stylesheet.
- **The frame**: the application's name sits in the top bar
  (`topbar_brand` block), with the navigation's button and its **pin**
  beside it — the pin is in the bar, not in the navigation, which is
  what is missing when it is wanted. The choice is also saved as
  `UserPreferences.navigation` (`pinned` / `floating`), which a browser
  that has never been told follows. The navigation is pinned or not
  (`sidebar-unpinned` on `<html>`, remembered in `localStorage`):
  unpinned, the page takes the whole width, `.sidebar-edge` on the left
  slides the navigation out while the pointer is on it, and the bar's
  button opens it and holds it (`sidebar-peeking`). `sidebar-open` /
  `sidebar-closed` describe the pinned column only — unpinned, the
  panel is parked outside the viewport, never `display: none`, or the
  edge and the pin would have nothing to bring back. Below 1024px none
  of this applies: the navigation is already an overlay. `ui.js` owns
  the behaviour.

## 13a. Watching a record

```python
from generic.watch import watch, unwatch, is_watching

watch(user, ticket)                    # this record: updated, deleted
watch(user, Ticket)                    # the model: created too
watch(user, Ticket, events=["created"], channels=["mail"])
```

- One `generic.Watch` row per user and target; an empty `object_id` is
  the whole model. `channels` empty follows the account's notification
  preference. Same channels as tasks (`generic.delivery`).
- Sent from `generic.sites.realtime`'s signal, **after commit**, and
  only to users holding the model's view permission — re-checked per
  message. Object-level rules: override
  `ModelResource.may_watch(user, obj)`. `watchable = False` on a
  resource removes the button and refuses the endpoint.
- UI: a *Watch* button in `object_tools` of the detail, form and list
  pages (`generic/components/watch_button.html`, Alpine
  `watchControl`). On a record it is a split control: the button
  follows the record, the arrow beside it opens a menu offering *This
  one* and *All of them* as two independent watches. The page
  `site:watches` (account menu) is where each watch's changes and
  channels are ticked. API: `generic:watch-list`, `-toggle`,
  `-status`. `queryset.update()` fires no signal, so it tells nobody.
  See `docs/watch.md`.

## 13b. Tasks

```python
# myapp/tasks.py - imported at start-up by the framework and by Celery
from generic.tasks import managed_task

@managed_task(label=_("Nightly digest"), announce=("notification",),
              report=("notification", "mail"), audience="staff")
def nightly_digest(run):
    run.note(gettext("Collecting"))     # a step, saved at once
    run.add(gettext("Tickets"), 12)     # a line of the result
    return gettext("12 tickets")        # the summary
```

- Four steps every time: **announce** (step 1), **run**, **collect**
  (what it returned becomes one result), **report** (step 4). A failure
  reports too. Channels: `notification`, `mail`, `page`
  (`generic.tasks.ALL` for the first two); audience: `trigger`,
  `staff`, `superusers`, `everyone`, or a callable. Each message is
  written in the reader's own language.
- One `generic.TaskRun` per run, with `summary`, `results`, `log`,
  `error`, and a report tree (`run.report.warning(...)`, `with
  run.report.section(...)`, §13g; warnings/errors set the report's
  notification level); its page shows all of it. `launch(name, user=...)` starts one
  from code; the *Tasks* page (`site:tasks`, permission
  `generic.run_task`) starts one by hand.
- With Celery and a broker, a worker does the work; without, the
  process that asked does. Same steps either way. The broker is the one
  of the Celery app the process loaded: the project package's
  `__init__.py` imports it (`from .celery import app as celery_app`),
  or the web server runs every task in the request.
- `django_celery_beat` installed puts its `PeriodicTask`, interval,
  crontab and clocked models in the **Tasks** group as resources, with
  *Run now*. `SHOW_TASKS`, `TASK_RECENT_RUNS`. See `docs/tasks.md`.

## 13g. Operations and reports (the work behind a button)

```python
# myapp/tasks.py
from generic.tasks import operation

@operation(label=_("Recompute invoices"), background=True,
           report=("notification",), permission="")
def recompute_invoices(run, ids):                       # arguments: JSON only
    for customer in Customer.objects.filter(pk__in=ids):
        with run.report.section(str(customer), isolated=True,
                                url=...) as part:       # savepoint; an exception
            part.success(...); part.warning(..., detail)  # -> error line, goes on
    return gettext("Done")                              # headline; else counts

# resources.py - an action (or any view) starts it:
@action(description=_("Recompute"), icon="calculate")
def recompute(self, request, queryset):
    return recompute_invoices.start(request, ids=list(queryset.values_list("pk", flat=True)))
# a view of its own: return operation_response(run)   # 202 running, 200 done
```

- **Never hand-build** progress/result feedback for a page's backend
  work: declare an `@operation` (or return a `Report` for work done in
  the request that keeps nothing). The tables' bulk actions and the
  summary page's actions draw the answer; custom pages call
  `Generic.operations.post(url, body)`.
- `generic.reports.Report`: `info/success/warning/error(title,
  detail="", url=..., **extra)`, `section(title, isolated=False)` (a
  section shows its worst level; `isolated` = savepoint, exception
  logged and written, work goes on), `level` (`warning`/`error`, else
  `success`), `counts()`, ≤ 2000 lines, text only, `url` a site path
  or http(s). JSON node `{level, title, detail, children, url?}`.
- An operation = a `managed_task` with `catalogue=False` (not on the
  Tasks page, 404 there, left out of *Run again*), `announce=("page",)`,
  `audience="trigger"`. `run.report` is the run's report, saved as it
  grows (`TaskRun.tree`); `TaskRun.language` is the starter's, active
  while it runs; `run.level`; `as_client()` gains `finished`, `level`,
  `report`, `counts`.
- `start(request_or_user, background=None, **arguments)`:
  `background=False` (default) in the request, answered with the whole
  report, **not notified**; `True`: answered at once (`202`), a Celery
  worker when reachable (broker and not eager), else
  `OPERATION_FALLBACK` (`"thread"`: a daemon thread started on commit,
  connections closed after; `"inline"`). Its end: a notification
  (`report` channels) to the starter and the event `operation.finished`
  (`as_client()`) to that user only; the card turns into the report,
  the bell skips its toast for a run a card shows.
- Answer: `{"message", "level", "operation": {...}}` (+ `count` from an
  action); `operation_payload(run | report)`.
- The starter may open the run's page without `view_taskrun`
  (`TaskRunResource.has_view_permission(request, obj)`); operations
  alone register the runs (`runs_are_kept()`), not the Tasks page.
  Example: *Check* (tickets, in the request) and *Review* (customers,
  background) in `example/tasks.py`. See `docs/operations.md`.

## 13h. Teams (`generic.teams`)

```python
INSTALLED_APPS += ["generic.teams"]                 # then migrate

team = models.ForeignKey("generic_teams.Team", on_delete=models.PROTECT,
                         related_name="folders")

class FolderResource(ModelResource):
    team_field = "team"
class DocumentResource(ModelResource):
    team_field = "folder__team"                     # or "teams" (M2M)

from generic.teams import scope_to_teams, teams_of, in_teams_of, sees_every_team
scope_to_teams(Document.objects.all(), user, "folder__team")
```

- Groups say what a person may do, teams which records: a member of
  several teams sees all of theirs. `get_queryset` narrows (so the
  list, search, facets, exports, charts, summary, history tab, files,
  related tables, palette, autocompletes, transitions, imports);
  another team's record is a 404. Superusers and holders of
  `generic_teams.see_every_team` see everything; nobody signed in,
  nothing.
- Relations: `FormModelSerializer.get_fields` narrows every writable
  relation whose related resource's `get_relation_queryset(request)`
  is not None (`narrow_relation` in `api/relations.py`) - embedded
  choices and validation alike, a key sent by hand is a 400. On for
  `team_field`, or `scope_relations = True` on any restricted resource;
  off otherwise (unchanged behaviour).
- `may_watch` asks `in_teams_of`; `get_initial` opens an add form on
  the reader's only team. A path through a many-valued relation is
  filtered by subquery (no duplicates); a path not ending at `Team`
  raises `ImproperlyConfigured`. `TeamResource` (People, `team_field
  = "pk"`). Not narrowed: *History › Changes* (an administrator's
  page), `update()`. See `docs/teams.md`; example `docmanager/`.
- Leaders: `Team.leaders` (M2M, `related_name="generic_led_teams"`,
  migration `generic_teams` 0002). A leader reaches the team's records
  like a member (`own_teams` = members or leaders, used by `teams_of`
  and `scope_to_teams`); `leaders_of(team | teams)` - active users,
  each once. What leading means otherwise is the project's.

## 13i. Numbering (`generic.numbering`)

```python
from generic.numbering import Pattern, allocate, peek

allocate("{team}-{type}-{year}-{seq:04}", namespace="documents",
         exists=lambda code: Document.objects.filter(code=code).exists(),
         team="LEG", type="CTR")              # "LEG-CTR-2026-0001"
Pattern(text, fields=("team", "type")).validate()   # ValidationError
peek(pattern, **values)                       # the next one, nothing taken
```

- Fields: `{seq}` (required, `{seq:04}` pads, ≤ 12), `{year}` `{yy}`
  `{month}` `{day}` (`timezone.localdate()`), any value passed. Only
  `seq` takes a spec; validation codes `malformed`, `unknown`, `spec`,
  `no_sequence`; rendering a field without a value: `missing`.
- One series per pattern filled in but for `#` (+ `namespace:`),
  digested past 255 characters: `{year}` restarts each year, each team
  counts apart. `generic.Sequence` (`key` unique, `value`), core app,
  migration `generic` 0017; `next_value(key)` creates the row in its own
  savepoint (a concurrent create is caught) then `select_for_update`.
  Call it in the transaction that stores the number; keep a unique
  constraint on the field. See `docs/numbering.md`; example
  `docmanager/documents/codification.py`.

## 13ter. Signing in through somebody else

```python
site.add_sso_provider(_("Entra ID"), route="oidc_authentication_init",
                      icon="corporate_fare", description=_("..."),
                      order=0, next_param="next")
# Also GENERIC["SSO_PROVIDERS"] = [{...}]; the two add up.
```

- The framework speaks **no OIDC and no SAML**: the project picks a
  library (`mozilla-django-oidc`, `django-allauth`, `djangosaml2`, a
  proxy) and the declaration points at the URL that library already
  serves. Never implement the protocol in `generic/`.
- With a provider declared, the sign-in page leads with its button and
  folds the password form into a `<details>` underneath; with none, the
  page is unchanged. `SSO_PASSWORD_LOGIN = False` removes the form -
  **except** when no provider is declared, because a page with no way
  in is a locked door, not a policy. A provider whose route does not
  resolve is left out quietly for the same reason.
- `?next=` travels with the button, after Django has already refused a
  destination pointing off the site. `next_param=""` for a library
  that carries its own state.
- An account with no usable password is already treated as externally
  managed (read-only name and address on the account page). See
  `docs/sso.md`.

## 13bis. People, groups and permissions

- The framework registers `AUTH_USER_MODEL`, `Group` and `Permission`
  under **People**, so a project manages accounts on its own site
  rather than in `/admin/`. Gated on the ordinary `auth.view_*`
  permissions; `SHOW_PEOPLE = False`, or registering the user model in
  the project's own `resources.py`, takes them off (they are only
  added where the model is still free).
- The password is `write_only` (`form_field_kwargs`) and drawn with
  `{"widget": "password"}`: it is never sent back, is checked against
  the project's `AUTH_PASSWORD_VALIDATORS` before anything is written,
  and is hashed in `save_model`. Empty on an existing account leaves
  it alone; empty on a new one means no usable password, for a
  directory account.
- **What you grant, you must already have** (`accounts/guard.py`): a
  non-superuser cannot tick *superuser*, cannot tick *staff* unless
  they are, cannot add a group or a permission granting anything they
  lack, and cannot open a superuser's form at all. Nobody can delete
  or deactivate the account they are signed in as - including through
  a bulk action, which goes through the same `delete_model`.
- Nothing is declared against a field a custom user model may not have:
  columns, fieldsets, search and the members tab are computed in
  `register_screens`. `history_exclude = ("password", "last_login")`.
  See `docs/people.md`.

## 13c. History

```python
from generic.history import acting_as, history_of, prune

with acting_as(user, source="Nightly import"):
    ticket.status = "closed"
    ticket.save()

history_of(ticket)                 # every version, newest first
```

- Every registered model keeps a version of every record, written from
  the model signals: one `generic.HistoryEntry` per version, holding
  the record's own fields **as they were** (a snapshot, not a diff).
  What changed is worked out when the history is read, by comparing an
  entry with the one before it, so a field the project starts or stops
  tracking never rewrites the past. Values are kept as the database
  returns them (a decimal quantized to its field's places).
- A save that changes nothing recorded writes nothing. Every save in
  one request - or one `acting_as` block - folds into one entry: one
  unit of work is one version. `update()` and `bulk_create()` fire no
  signal and record nothing, like the events and the watches.
- Many-to-many fields are carried forward and re-read only when
  `m2m_changed` fires; set from the far end
  (`tag.tickets.add(ticket)`) records nothing.
- **Who** is ambient, because a signal has no request:
  `generic.middleware.CurrentUserMiddleware` for a request,
  `acting_as(user, source=...)` for a block; a task run sets it
  itself. Without either, the entry says nobody.
- UI: a **History** tab on the summary page, beside the related tables
  (`generic/resource/includes/history_panel.html`, Alpine
  `recordHistory`), and a line at the top saying who touched the record
  last. Page `site:generic_historyentry_list` (*Changes*, in the
  History group) lists every change, behind
  `generic.view_historyentry` - a wider door than the tab, which only
  needs the record's view permission.
- `history = False` per resource, `history_exclude = (...)` per field,
  `HISTORY` and `HISTORY_RETENTION_DAYS` per project;
  `generic.history.prune()` deletes what is older. See
  `docs/history.md`.

## 13j. Trash and access log

```python
# models.py
from generic.trash import Trashable

class Contract(Trashable):          # adds deleted_at, deleted_by
    ...

# resources.py
class ContractResource(ModelResource):
    trash = True                    # ImproperlyConfigured without the fields
    access_log = True

    def may_download(self, request, obj, field):
        return field != "file" or request.user.has_perm("app.change_contract")
```

- With `trash`, every delete - the row's, the bulk action's, the
  delete page's, the API's `DELETE` - sets `deleted_at` instead. Every
  screen and endpoint shows live rows only; relations still point at
  the record. The *Trash* page (`ResourcePage` "trash", behind the
  delete permission) is the list with `?_trash=1`: *Restore* and
  *Delete for good*, nothing else. `generic.trash.empty(days)`,
  the `empty_trash` command and the managed task `generic.empty_trash`
  (declared when some resource has a trash) delete for good what is
  older than `TRASH_DAYS`; protected records stay.
- With `access_log`, `generic.access.record(request, obj, action,
  detail)` runs on the summary page (`viewed`, once per ten minutes per
  person) and on every file download (`downloaded`, with the name).
  Call it from a page of your own too. `AccessEntry` keeps the record
  as `app.model:pk`, so the entries outlive it; *History > Access log*
  lists them, behind `generic.view_accessentry`;
  `generic.access.prune()` applies `ACCESS_LOG_RETENTION_DAYS`.
- See `docs/trash.md`.

## 13e. The API for scripts (`generic.tokens`, `generic.openapi`)

```python
INSTALLED_APPS += ["knox", "generic.tokens", "drf_spectacular", "drf_spectacular_sidecar"]
REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] += ["generic.tokens.authentication.TokenAuthentication"]
REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"
path("api/", include("generic.openapi.urls"))      # before site.urls
```

- A token = `ApiToken(AbstractAuthToken)`, its own table, never
  `KNOX_TOKEN_MODEL` (knox's first migration creates its table anyway,
  and PostgreSQL then cannot truncate `auth_user` between tests):
  digest (pk), token_key, user (`related_name="api_tokens"`), created,
  expiry + name, scope (`read`/`read_write`),
  last_used_at (written once a minute at most, by `update()`). It acts
  with its owner's permissions; a read token on an unsafe method is a
  403 raised by the authentication class. Made on the account page
  (`AccountView.api_tokens`, `generic/account/api_tokens.html`, Alpine
  `apiTokens`), shown once; `generic_tokens.add_apitoken` to make one.
  `api/generic/tokens/` is session only. People › API tokens: read and
  revoke (`view_`/`delete_apitoken`), never add or change.
- Framework viewsets and hand-built API views carry `schema =
  framework_schema()`: `ResourceAutoSchema` when `drf_spectacular` is
  in `INSTALLED_APPS`, DRF's `DefaultSchema` otherwise. It types the
  list through `DataTablesPagination.get_paginated_response_schema`,
  adds the filter parameters, answers hand-built actions as objects or
  files, maps `TagsColumn`/`ManyRelatedColumn` by extensions, names
  generated serializers `<App><Name>`. A new endpoint or column type
  must keep `manage.py spectacular --validate --fail-on-warn` clean (CI
  runs it on the example). A user-scoped viewset sets `queryset =
  Model.objects.none()` for the generator. See `docs/api.md`.

## 13d. Scheduled mailings

- *Send by e-mail on a schedule…* in a list's Views menu (option
  `mailingUrl` of `get_table_options`, from `get_mailing_url`) opens the
  `ScheduledMailing` add form with `?table=<state key>&state=<json>`;
  `ResourceFormView.get_initial` reads JSON fields as JSON.
- `generic.ScheduledMailing`: name, owner, table (`site.<app>.<model>`),
  state (a saved view's), format xlsx/csv, frequency
  daily/weekdays/weekly/monthly + time (project `TIME_ZONE`), weekday,
  day_of_month (1-28), include_owner, users, groups (active, with an
  address, distinct), send_when_empty, is_active, next_run_at,
  last_sent_at, last_error.
- **Rows as each recipient**: `sending.send(mailing)` calls the
  resource's own `list` (count) and `export`/`export_csv` actions
  through a synthetic GET signed in as the recipient, state turned into
  `filters`/`search`/`ordering`/`columns` (`parameters()`), inside the
  recipient's language. Never read rows another way.
- Dispatcher `generic.send_scheduled_mailings` (`managed_task`, page
  channel only) or `manage.py send_scheduled_mailings`: claim under
  `select_for_update(skip_locked=True)`, move `next_run_at` first. A
  `MailingProblem` pauses the mailing and notifies the owner.
- Permissions: `add_scheduledmailing` (own), `view_`/`change_`/
  `delete_scheduledmailing` (everyone's). `mailing = False` on a
  resource, `SHOW_MAILINGS = False` for the project. The framework's
  own `generic.*` tasks do not turn `SHOW_TASKS = None` on. See
  `docs/mailings.md`.

## 13f. Logs and error reports (`generic.logs`)

- Settings: `ADMINS = admins([...])` (addresses from Django 6.0,
  `(name, address)` pairs before); `LOGGING = logging_config(level=,
  file=, max_bytes=10MB, backups=5, mail_errors=True, quiet=
  ("django.security.DisallowedHost",))`; with Celery,
  `CELERY_WORKER_HIJACK_ROOT_LOGGER = False` or the worker's errors
  bypass `LOGGING`. The example reads `DJANGO_ADMINS`,
  `DJANGO_LOG_LEVEL`, `DJANGO_LOG_FILE` (base.py); the prod stack
  writes `/app/logs/app.log` in the `app-logs` volume from every
  service.
- Root handlers: console, the file (`SharedRotatingFileHandler`:
  follows another process's rotation, rotates under an `fcntl` lock),
  `ErrorMailHandler` at ERROR with `require_debug_false`. `django` is
  redefined without handlers so Django's default `mail_admins` does not
  mail twice.
- `ErrorMailHandler`: same error (logger, level, message - or exception
  type + innermost line) once per `ERROR_MAIL_INTERVAL` (600 s; 0 =
  all), counted in the default cache, "[N more since the last mail]";
  cache failure → mail anyway; a send failure goes to `handleError`,
  never to the caller.
- Framework code logs failures with `logger.exception` on
  `logging.getLogger(__name__)` and never swallows them silently;
  `check --deploy` warns `generic.W009` when `ADMINS` is empty. See
  `docs/logging.md`.

## 14. Known pitfalls

- `site.urls` must be the **last** URL pattern.
- **A release moves five labels together**: `generic/__init__.py`
  `__version__` (the package's only version source), a dated
  `## [x.y.z]` section in `generic/CHANGELOG.md` (on top - it takes no
  Unreleased section) and in the root `CHANGELOG.md` (the example's;
  its Unreleased entries become that section), and the example's
  `GENERIC["VERSION"]` and `SPECTACULAR_SETTINGS["VERSION"]` in
  `example_project/settings/base.py`. `tests/test_help.py` checks all
  of them against `__version__`; the tag (`vX.Y.Z`) comes last.
- A DRF `@action`'s route name comes from its **method** name, not its
  `url_path`: `mark_all_read` with `url_path="read-all"` is
  `notification-mark-all-read`. `get_framework_api()` turns a name that
  finds nothing into `""`, and a page posting to `""` posts to itself
  (a 405) - `tests/sites/test_registry.py` checks every entry resolves.
- `daphne` first in `INSTALLED_APPS`, or `runserver` silently drops
  WebSockets.
- A related table's model must be registered, or the tab cannot load.
- A `list_display` path through a many-valued relation raises: use a
  method column.
- Computed columns need an annotation to be sortable/filterable.
- `QuerySet.update()` fires no signal: `announce(resource, "bulk")`.
- After changing JS/CSS, browsers cache static files: hard reload.
- Seeding users with passwords invalidates open sessions.
- Never `reverse()` at the top level of a `resources.py`: it is
  imported while the site is still being built, and the URLconf it
  freezes holds only what is registered so far - every screen added
  after it disappears.
- Windows tooling: keep JS ASCII; line length 79 for Python.

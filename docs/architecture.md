# Architecture

## The one idea

Everything in this package follows from a single rule: **a thing is
declared once, and every consumer reads that declaration.**

A column declared on a serializer field produces:

- the JSON column configuration DataTables receives,
- the whitelist of what may be filtered, and how,
- the whitelist of what may be ordered, and on which ORM path,
- the columns an export contains.

This is not only about avoiding duplication. It is what makes the
endpoints safe. The client sends *public column names* — `author`,
`pages` — and never an ORM path. Every name is resolved through the
serializer before it reaches the queryset. A name the serializer does
not expose is rejected, so `?filters={"match": "all", "conditions":
[{"column": "password", …}]}` cannot become a query. The facets the
filter editor lists go through the same whitelist.

## Module map

```
generic/
├── conf.py            Settings, with defaults, reloaded on override
├── models.py          Re-export so Django discovers the models
├── urls.py            Framework REST routes
│
├── api/
│   ├── columns.py       Column declarations -> ColumnOptions, FilterSpec
│   ├── tags.py          TagStyle: values as coloured tags; colour checks
│   ├── serializers.py   DataTableSerializer: fields -> table metadata
│   ├── filters.py       Filter engines, filter trees + the three backends
│   ├── facets.py        A column's values and counts, for the filter editor
│   ├── pagination.py    start/length -> the DataTables envelope
│   ├── renderers.py     ?format=datatables, and DataTables-shaped errors
│   ├── exports.py       Streaming Excel and CSV of the filtered set
│   ├── autocomplete.py  Select2 endpoint for multiselect filters
│   ├── forms.py         Serializer -> form schema
│   ├── inlines.py       Tabular inlines: parse, delete, validate, save
│   ├── relations.py     Labels and Select2 wiring of relation fields
│   ├── viewsets.py      DataTableViewSet, ModelFormViewSet, …
│   └── datatables.py    Compatibility shim for the old import path
│
├── sites/
│   ├── site.py          GenericSite: registry, URLs, navigation, search
│   ├── resources.py     ModelResource, the ModelAdmin counterpart
│   ├── serializers.py   list_display and fields -> generated serializers
│   ├── viewsets.py      ResourceViewSet: one endpoint per resource
│   ├── inlines.py       TabularInline, StackedInline
│   ├── views.py         List, add/change and delete pages
│   ├── decorators.py    @action, @display
│   ├── related.py       RelatedTable: a summary page's related tables
│   ├── charts.py        Chart: declared aggregates -> chart payloads
│   ├── imports.py       Import: a spreadsheet read, mapped, validated, written
│   ├── summary.py       A record, typed and formatted for its summary
│   └── realtime.py      Model changes -> resource.changed
│
├── accounts/
│   ├── models.py        UserPreferences, SavedView
│   ├── api.py           The signed-in user's own state
│   ├── views.py         Account settings, the language switch
│   ├── resources.py     The People screens: users, groups, permissions
│   └── guard.py         Nobody grants what they do not hold themselves
├── i18n.py              The languages a project offers, and the menu
├── middleware.py        UserLanguageMiddleware: the language of a user
│                        CurrentUserMiddleware: who the history records
│
├── history/
│   ├── models.py        HistoryEntry: one version of one record
│   ├── actor.py         Who is acting, where no request can be passed
│   ├── recording.py     Model changes -> a version, folded per request
│   ├── reading.py       Versions -> what changed, written out
│   └── resources.py     The Changes page
│
├── watch/               Watch: a user follows a record or a model
├── tasks/               Declared tasks: the four steps, runs, schedules
├── mailings/            A list, as each reader may see it, e-mailed on a schedule
│   ├── models.py        ScheduledMailing: which table, as whom, to whom, when
│   ├── schedule.py      The next sending, in local time
│   ├── sending.py       As each recipient: the resource's own export
│   ├── dispatch.py      The dispatcher task: what is due, claimed once
│   └── resources.py     The Scheduled mailings screen
├── delivery.py          One message, some people, the channels they chose
├── locale/              The framework's own catalogs (English, French)
│
├── help/
│   ├── changelog.py     Keep a Changelog, parsed into releases
│   ├── sources.py       Where the licence and the changelogs are found
│   └── views.py         The help page and the page of changes
│
├── maintenance/
│   ├── models.py        RestartAnnouncement: when, how long, by hand or not
│   ├── scheduler.py     The three warnings, and the restart itself
│   ├── api.py           Announce, read what is planned, call it off
│   └── views.py         The page an operator announces from
├── wiki/                Optional: pages, editor, history, pinned pages
├── tokens/              Optional: personal API tokens on knox (ApiToken)
├── openapi/             The OpenAPI description: ResourceAutoSchema, pages
├── search/              Optional: every text match sets accents aside
│   ├── lookups.py       The unaccented transform, per database
│   ├── operations.py    Migration operations: unaccent, trigram indexes
│   └── ranking.py       search_rank: best match first
│
├── events/
│   ├── registry.py      Declared topics and who may subscribe
│   ├── bus.py           publish() and the channel-layer plumbing
│   ├── consumers.py     The WebSocket consumer
│   ├── routing.py       ws/events/
│   ├── models.py        Notification
│   ├── serializers.py   Socket payload and table row
│   ├── signals.py       Model change -> event
│   └── api.py           Notification history endpoints
│
├── forms/
│   └── fieldsets.py     Admin-style layout, without ModelAdmin
│
├── views/
│   ├── mixins.py        Page chrome, access, popup, fieldsets
│   ├── toolbar.py       Toolbar buttons and breadcrumbs
│   ├── tables.py        list_display -> rendered rows
│   ├── list.py          Search, ordering, paging, bulk actions
│   ├── detail.py  edit.py  delete.py
│   └── datatable.py     Page bound to a DataTableViewSet; the
│                        filter_row check resources share
│
├── templates/generic/   base.html, pages, components/, charts/
├── templatetags/        Ordering links, query-string helpers,
│                        {% generic_chart %}
└── static/generic/      Design tokens, component CSS, vanilla JS;
                         charts.js draws chart payloads with ECharts
```

A chart is one more consumer of the same declarations: its endpoint is
an action of the resource's viewset, so it inherits the permission
checks, the table's filter whitelist and the `_related` narrowing, and
its payload names categories and series rather than a charting
library's options.

Dependencies point one way: `events` may use `api` (the notification
table is a data table), `api` never imports `events`. `views` may use
`api` (the datatable page reads a viewset's columns); `api` never
imports `views`, so a project can take the REST layer alone.

## Two ways to render a table

Both exist because they answer different questions.

`GenericListView` renders rows server-side from `list_display`. No
JavaScript, works without it, and is the right default for a screen
someone opens a few times a day.

`DataTableView` renders an empty table and a JSON configuration; the
browser fetches rows from the REST endpoint. Per-column filters, column
selection, saved state, exports, tens of thousands of rows.

The second reuses the first's chrome and the API's column declaration,
so moving a screen from one to the other changes the view class and the
template, not the model or the serializer.

## Why the fieldsets are reimplemented

`django.contrib.admin.helpers.AdminForm` does this well, and
`genericOLD` used it — passing `admin.site._registry[self.model]` into
it, which quietly required every model to be registered in the admin.

`generic/forms/fieldsets.py` is about 300 lines and depends on nothing
in `contrib.admin`. That keeps this layer usable in a project that does
not install the admin at all, and removes a coupling to a semi-private
API that shifts between Django versions.

## Request flow: a table draw

```
GET /api/books/?draw=3&start=0&length=25
    &filters={"match":"all","conditions":[{"column":"pages","operator":"gt","value":300}]}
    &search[value]=austen
    &columns[0][data]=title&order[0][column]=0&order[0][dir]=desc

  DataTableViewSet.filter_queryset
    └─ records the unfiltered count for recordsTotal
  AdvancedFilterBackend       tree -> names -> FilterSpec -> one Q
  DataTablesSearchBackend     icontains across the searchable columns
  DataTablesOrderingBackend   column index -> public name -> ORM path
  DataTablesPagination        start/length -> LIMIT/OFFSET
  Serializer                  rows -> JSON
  DataTablesPagination        {draw, recordsTotal, recordsFiltered, data}
```

## Why not `djangorestframework-datatables`

The previous code relied on it, via `?format=datatables`. It has not
kept pace with Django, and it derives filtering from the request's own
`columns[i][searchable]` echo — the client tells the server what it may
filter.

The replacement is about 300 lines across `filters.py`, `pagination.py`
and `renderers.py`, resolves everything through the serializer instead,
and is covered by tests. `?format=datatables` still works, because
`DataTablesRenderer` registers that format, so the existing JavaScript
needs no change.

## Defects fixed from `genericv2`

Carried over from the ancestor code and fixed here, each with a
regression test:

1. **Inline rows could not be created.** The parent foreign key was
   stripped from the inline *schema* but still validated as required by
   the serializer, so every new row failed with
   `{"book": ["This field is required."]}`.
   → `InlineProcessor.build_row_serializer` now supplies the real parent.

2. **Date filters broke on `DateField`.** The engine always used the
   `__date` lookup and timezone-aware day boundaries, which only exist
   on a `DateTimeField`. → `FilterSpec.value_type` distinguishes the two.

3. **Boolean filters were rejected.** The client offered a boolean
   filter; the server answered "Unsupported field type".
   → `boolean_engine`.

4. **Excel export ignored DRF's filter backends.** It called
   `get_queryset()` rather than `filter_queryset(get_queryset())`, so an
   export could contain rows the table itself did not show.

5. **Excel export crashed on Windows.** `workbook.save(stream.name)`
   cannot reopen an open `NamedTemporaryFile`. → save through the handle.

6. **`datatable_overrides` typos were silent.** Options were merged as
   dicts, so `{"visibl": False}` did nothing. → `ColumnOptions` is a
   dataclass and `replace()` raises on an unknown key.

7. **`min_rows` and `max_rows` overwrote each other's error.** Both
   assigned to `errors["_errors"]`. → the messages accumulate.

8. **Rows deleted and re-created in one request could not swap a unique
   slot.** Validation ran before the deletions. → phase ordering, see
   below.

9. **Model fields were invisible to the table.** Columns were read from
   `_declared_fields`, so a `ModelSerializer`'s generated fields never
   appeared, and labels were `None` because the fields were unbound.
   → the serializer is instantiated and `fields` is read.

## The inline phases

Applying an inline payload runs in three phases inside the caller's
transaction:

1. **Parse** — everything checkable without writing: row shape, that
   each referenced row belongs to *this* parent, add/delete permissions,
   row counts.
2. **Delete** — the removals are executed.
3. **Validate and save** — the remaining rows are validated against the
   state phase 2 left behind, then written.

Deleting before validating is what lets one request free a slot and
reuse it. Any failure in phase 3 raises, and the transaction takes the
deletions back with it — the tests assert exactly that.

On create, the parent is written *before* the rows are validated, for
the same reason: a uniqueness constraint spanning the parent cannot be
evaluated without one.

## Events

Two halves, deliberately independent:

- An **event** is transient. It reaches whoever is connected now.
  Publishing one never touches the database.
- A **notification** is durable, so a user who was offline still finds
  out. Storing one publishes an event through a signal.

Delivery is deferred to `transaction.on_commit`, so clients are never
told about a row a rollback then removes.

Subscriptions go through a **topic registry**. A client may only join a
topic the project declared, and each topic carries the rule saying who
may listen. Naming a group directly — `generic.user.1` — is refused.

## The UI: DRF-first

The generated screens are drawn in the browser from JSON. The list page
asks the endpoint for rows; the form asks for its schema and its
record; both send JSON back. The server renders the frame — sidebar,
header, the empty table and form — and the configuration they start
from, nothing more.

Four options were weighed for the interface:

- **django-unfold** is a polished admin theme, and many of its ideas
  were borrowed: grouped sidebar, command palette, user menu, tabs,
  collapsible sections, the dashboard. It was not adopted because it
  is a theme for `django.contrib.admin`: its lists are the admin's HTML
  changelist and its forms are Django forms posted as HTML. Neither
  DataTables nor the REST API fits in it, and both were requirements.
- **HTMX** exchanges HTML with the server. Here the server's product is
  JSON, so that every screen — and any other client — reads the same
  data through the same permission checks. HTMX would have meant a
  second, HTML rendering of everything.
- **Tailwind** would bring a Node build step into a reusable Django
  app, and utility classes into templates that projects then have to
  override. The design tokens — CSS custom properties — already make
  theming a matter of settings.
- **Alpine.js** was taken: a small script, no build, for the stateful
  bits of the frame — menus, the palette, the bell, the watch control,
  the theme switch. Tables stay on DataTables and forms on their own
  renderer; both are too large for inline templates.

What this buys: a permission is checked in one place, the resource,
whichever page or client asks; a script or a mobile app uses the very
endpoints the pages use; the tests assert on JSON instead of scraping
HTML.

What it costs: the generated pages need JavaScript. A project wanting
server-rendered pages keeps `generic.views`, which draw in the same
frame.


## Where the code came from

This package supersedes two earlier internal codebases:

- **`genericv2/api`** is the direct ancestor of `generic/api`. The
  column and form-schema designs were kept; the code was reorganised,
  typed, translated to English, and given a test suite. Several defects
  were fixed along the way - see [Defects fixed from
  `genericv2`](#defects-fixed-from-genericv2).
- **`genericOLD`** contributed the notification model, the user
  settings page, the full-featured DataTables client - exports, column
  picker, saved state - and the idea of taking Django admin's screens
  out of the admin. Its `django-autocomplete-light`, `six` and
  `django-datatables-view` dependencies are gone.
- **Django admin** and **django-unfold** are the models for the
  interface; neither is used at run time. See [The UI:
  DRF-first](#the-ui-drf-first).

Code written against the old import paths keeps working:
`generic.api.datatables` is a compatibility module re-exporting the new
locations (`tests/test_compat.py`).
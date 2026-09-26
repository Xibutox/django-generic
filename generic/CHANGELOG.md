# Changelog

What changed in django-generic, newest first. The *Help › What changed*
page of every application built on it reads this file - shipped inside
the package - after the application's own.

The format is [Keep a Changelog](https://keepachangelog.com), and the
versions follow [semantic versioning](https://semver.org): from 1.0.0
on, a declaration that works keeps working until the next major
version.

## [1.1.0] - 2026-09-26

### Added
- `generic.search`, an optional app: every text match the framework
  makes - the table search, column filters, the filter editor, the
  command palette, the autocompletes, classic list views, the wiki and
  data resources - sets accents aside as well as case, so `societe`
  finds *Société*. PostgreSQL through `unaccent` (its migration creates
  the extension and an indexable wrapper), SQLite through a Python
  function of the same name, other databases untouched.
- `generic.search.operations.CreateSearchIndex`: a GIN trigram index on
  exactly the expression a search compiles to, built on PostgreSQL and
  skipped elsewhere.
- Imports: `imports = Import(fields=..., key=...)` on a resource gives
  its list an *Import* button and a page to choose an Excel or CSV
  file, match its columns, preview what would be created, updated or
  refused - by row and column - and import, all or nothing. Headers,
  choices, relations and dates are read as the exports write them, so
  an export imports back unchanged. Endpoints `import/schema/`,
  `import/template/` and `import/`; hooks `clean_import_row` and
  `save_import_row`; settings `IMPORT_MAX_ROWS`,
  `IMPORT_MAX_FILE_SIZE`, `IMPORT_PREVIEW_ROWS`; the `import` extra.
- The API for scripts. `generic.tokens` (on django-rest-knox,
  `KNOX_TOKEN_MODEL = "generic_tokens.ApiToken"`): personal tokens made
  on the account page and shown once, read only or read and write, with
  an expiry and their last use; an *API tokens* screen under People to
  revoke anyone's; `generic.tokens.authentication.TokenAuthentication`.
  `generic.openapi` (on drf-spectacular): `api/schema/` and `api/docs/`
  describe every generated endpoint as it behaves - the DataTables
  envelope and its filter tree, charts, actions, exports, imports -
  listing only what the reader may use, Swagger UI served from the
  sidecar's files. Checks `generic.E006`, `E007`, `W008`, `E008`;
  settings `API_TOKEN_*`; the `api` extra.
- Scheduled mailings (`generic.mailings`): *Send by e-mail on a
  schedule* in a list's Views menu sends the table as it is - filters,
  search, columns, order - as Excel or CSV, daily, on weekdays, weekly
  or monthly, to people and groups. Each recipient gets the rows they
  may see, computed as them through the resource's own export, in
  their language. A dispatcher task (`generic.send_scheduled_mailings`,
  or `manage.py send_scheduled_mailings` from cron) claims each due
  mailing once; one that no longer works pauses and tells its owner.
  Behind `generic.add_scheduledmailing`; `ModelResource.mailing`,
  `SHOW_MAILINGS`, `MAILING_MAX_ATTACHMENT_SIZE`;
  `generic.delivery.mail_with_attachment`.
- `generic.sites.realtime.batch(resource)`: every change made in a
  block announced as one `bulk` event.
- `ModelResource.search_rank`: the command palette and the
  autocompletes list the closest match first (`pg_trgm`); `generic.W007`
  when the app is missing.

### Fixed
- Exports and forms speak each request's language. Column titles and
  form sections were turned into text when a resource's serializers
  were built - once per process - so every export and form after the
  first request kept that request's language.
- An account page shown to nobody - the API description, written with
  no request - no longer fails asking an anonymous user for a password.
- A JSON field of an add form takes its value from the address
  (`?state={...}`) as JSON rather than as text.

## [1.0.0] - 2026-09-25

The first official release: an admin-like application framework for
Django, driven by the REST API. Declare a model once and get its
screens; everything below is included.

### Declaring screens
- `ModelResource` and `@register`: from one declaration, a model's list
  page, summary page, add and change forms, delete page, REST endpoint,
  navigation entry and command palette results. Attributes and hooks
  keep the admin's names - `list_display`, `search_fields`,
  `fieldsets`, `inlines`, `actions`, `@display`, `get_queryset`.
- `auto(Model, related=(...))` and `AutoResource`: the resource worked
  out from the model - columns, search, coloured choices, a form two
  fields a row, related tables and form tabs - anything declared
  winning.
- `DataResource` and `@register_data`: rows that are in no table - an
  external API's answer - listed, filtered, searched, sorted, counted
  and exported like a model's, with a page per row, read only;
  `RelatedRows` and `RowLink` tie data resources together.
- Pages of a resource's own, `@page` and `ResourcePage`: a map, a
  timeline, a report, a JSON feed - any content, mounted at the
  resource's address, guarded by its permissions, the record found
  through its queryset, drawn in the frame and offered where it belongs.

### Tables
- DataTables driven by the server: pagination, multi-word search with
  exclusions and phrases, multi-column ordering, a column picker, saved
  views and presets, Excel and CSV exports of every filtered row, copy
  and print.
- Filters as chips: every operator per type, relative dates, groups of
  *all* and *any*, the values of a column offered with their counts,
  typed as `status:open hours:>2` in the search box or in a row of
  fields under the headers, kept in the address. The filter editor
  applies as it changes.
- Columns declared once on the serializer drive the configuration, the
  filtering and ordering whitelists and the export: text, numbers,
  decimals, booleans, dates, choices, relations and coloured tags.
- Bulk actions on a selection or on every filtered row, a row menu, and
  tables that refresh themselves when their rows change.

### Editing in place
- Editable cells, fields of a related model included, written through
  the endpoint with the related model's own permission.
- Grids: a table in which every writable cell is a control, rows added
  on top; declared grids over any set of records, shown by `GridView`.

### Forms
- Forms drawn from a JSON schema of the serializer: fieldsets, tabs,
  collapsed sections, read-only values, Select2 relations fed by
  autocomplete endpoints, popups to create or edit the related record.
- Tabular and stacked inlines, saved with the record in one
  transaction, and a deletion preview that says what goes with a
  record, or why it cannot go.

### Summary pages and charts
- A record's summary: figures, sections of typed values linking to the
  related records, and a tab per related table - the related model's
  full table narrowed to the record.
- Charts declared on the resource, computed by the database under the
  table's filters, drawn with Apache ECharts in the page's colours, on
  the list, the summary, the dashboard or any template.

### Real time
- Events over WebSocket with Django Channels, keeping open pages up to
  date: topics, and permissions per topic.
- Notifications for everything addressed to a person - the bell, the
  notifications page, a toast on every open page - and e-mail, as each
  person chooses; every e-mail addressed to its reader alone.
- Messages: *People › Messages* tells some people, some groups or
  everyone something, as a notification or an e-mail; the list records
  who sent what to how many and how many read it, and deleting a
  message withdraws it.
- Watching a record or a whole model, told by notification or e-mail,
  as each user chooses.
- Planned restarts announced to everyone connected, three warnings,
  then the restart.

### Records over time
- A version of every record of every registered model, read back by a
  History tab: who changed what, when, from what to what.
- Declared background tasks with their runs and results, and the Celery
  Beat schedules as ordinary screens.

### People and access
- Users, groups and permissions as screens, refusing any grant the
  person granting does not hold.
- Model permissions checked by the resource and enforced by the
  endpoint; clients send public column names, never ORM paths.
- Single sign-on providers offered on the sign-in page, the protocol
  left to the project's own library.

### The frame
- One frame for every page: collapsible navigation, top bar, command
  palette, breadcrumbs, a toolbar folding into a menu, toasts, dialogs.
- Colours computed from five parameters in OKLCH, light and dark
  themes, and per-user appearance: accent, contrast, colourfulness,
  tint and table stripes. The interface is sized in rem throughout and
  follows the browser's text size and zoom.
- A wiki with an editor, history and pages pinned to the dashboard; a
  help page reading the project's own licence and changelog.
- Classic server-rendered views - list, detail, forms, delete - for
  pages that want no JavaScript.

### Languages
- English and French, for the framework's pages and its JavaScript; a
  language menu and a per-user preference.

### Installation
- `pip install django-generic`: the core needs only Django and Django
  REST framework; the rest comes as extras. The package carries its
  templates, static files - every library vendored, no CDN, no build
  step - translations and changelog.
- `manage.py check` names what a project's wiring is missing or has out
  of place - the `request` context processor, a middleware, session
  authentication for the API, the site's URLs - with the line to write.
- The site may be mounted under a prefix in a project whose root is
  taken; without the `events` extra, the pages open no WebSocket.

### Deployment
- An example project with development and production settings, Docker
  images and Compose stacks for both, Daphne behind Caddy, Postgres,
  Redis, and Celery workers.
- Requires Python 3.10 or later, Django 5.2 or later and Django REST
  framework 3.16 or later. Extras: `export`, `events`, `tasks`, `beat`,
  `wiki`, `postgres`, `dev`.

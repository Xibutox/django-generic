# Changelog

What changed in the Support desk, the example application of this
repository, newest first.

This file is the application's: the *Help › What changed* page shows
it first, then the framework's own, which ships inside the package -
[generic/CHANGELOG.md](generic/CHANGELOG.md). A project built on
django-generic keeps its changelog here, at its root, the same way.

The format is [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Added
- Word files merged with a template. *Merge Word files*, in the
  sidebar, takes an optional template (`.docx` or `.dotx`) and Word
  documents, put in order with the arrows, and downloads them as one
  `.docx`: the template's styles, headers and footers, each document
  on a new page, or in place of a paragraph reading `{{ documents }}`
  in the template. On the ticket list, *Word attachments* merges the
  Word files attached to tickets (two seeded letters). The framework's
  side: the optional app `generic.docx` (the `docx` extra:
  python-docx and docxcompose, pure pip), `merge_docx()` and
  `docx_response()` for any view and any files, `POST
  api/generic/docx/merge/`, the page `docx/`, the settings
  `DOCX_MERGE_PERMISSION` and `DOCX_MERGE_MAX_FILES`, the check
  `generic.E009`, and `Generic.api.download()` in the browser: a POST
  whose answer is a file, saved under the server's name. See
  docs/docx.md.
- Files in the wiki: the editor's paperclip - or a drop, or a paste -
  uploads files into a page, where each becomes a block linking to its
  download; images dropped or pasted land in the text the same way.
  The arrows of the toolbar (Alt+Up / Alt+Down) move a line, an image
  or a file up and down the page, and a page lists its attachments
  under its text. *How we triage* holds a checklist file. The
  framework's side: `generic_wiki.WikiFile` (migration `0003`),
  `POST api/generic/wiki/files/`, `GET wiki/files/<id>/` (always a
  download), the `wiki-file` block kept by the cleaning, and
  `attachments` in the page's API. See docs/wiki.md.
- Operations: the work behind a button, answered with a report. On the
  ticket list (or a ticket's page) **Check** looks at each selected
  ticket in the request and answers with a card holding a section per
  ticket - folded when nothing is wrong, open on the warning or the
  error otherwise. On the customer list **Review** goes through the
  selected customers in the background (a thread on a laptop, a worker
  in Docker): the card says it is running, then turns into the report
  when it ends, and the bell leads to the run's page with the same
  tree. The framework's side: `generic.reports.Report` (levelled lines,
  sections that fold, isolated sections that roll back one item and go
  on), `@operation` and `operation_response` in `generic.tasks`, a
  report on every task run (`TaskRun.tree`, migration `0016`), the
  `OPERATION_FALLBACK` setting and `Generic.operations` in the browser.
  See docs/operations.md.

## [1.2.0] - 2026-09-27

### Added
- Tickets carry an attachment, chosen in their form and downloaded from
  their page - behind the ticket's own permission - and the wiki's
  pages show images uploaded from its editor. The seed attaches a log
  to SD-1000. The production stacks keep uploads in an `app-media`
  volume, to back up with the database (docs/deployment.md). The
  framework's side is in generic/CHANGELOG.md, 1.2.0.
- Browser tests: `tests/browser/` drives the Support desk through a
  real Chromium - signing in, the ticket list (search, ordering,
  paging, a reload, a `status:open` chip, a bulk transition, the Excel
  download), the add and change forms, a summary page's tabs (the
  regression test for 1.1.0's `GenericDataTables.start` race), a
  transition's dialog, the Triage grid, an import, the command
  palette, the dark theme, French and the navigation on a phone, a
  ticket's attachment (chosen, downloaded, replaced, removed, refused
  before sending, refused to a stranger) and a wiki image uploaded
  from the editor - and fails on any error a page logs. Python Playwright through
  pytest-playwright against `live_server`, no Node; opt-in with the
  new `browser` extra (`pytest tests/browser -m browser --no-cov`, a
  plain `pytest` leaves them out), and a CI job of their own that keeps
  the screenshots of what failed. See docs/testing.md.
- The production stack behind nginx: `docker/docker-compose.prod-nginx.yml`
  is the Caddy stack with nginx in front (the `nginx` image target),
  serving the server's own certificate, or plain HTTP to try it. For a
  server whose nginx already serves other applications,
  `docker/docker-compose.host-nginx.yml` runs the stack without a
  proxy - Daphne on 127.0.0.1, the static files copied to a folder -
  and `docker/nginx/host-site.conf.example` is the server block to add.
  `docker/nginx/django-generic.conf` holds what any nginx needs for the
  application: the WebSocket upgraded and kept open, the scheme and the
  client's address set by nginx, uploads the size imports send. CI runs
  `nginx -t` on every configuration. See docs/deployment.md.
- Unexpected errors are mailed to `DJANGO_ADMINS`, and everything is
  logged to standard output and, with `DJANGO_LOG_FILE`, to a file: the
  production stack writes `/app/logs/app.log` in an `app-logs` volume
  from every service. The worker logs through the project's settings
  rather than Celery's own handlers (`generic.logs`, docs/logging.md).

### Fixed
- The installation guide says how the framework really arrives: it is
  not on PyPI, where `django-generic` is an unrelated package, so a
  project builds its wheel from the repository, keeps it in `vendor/`
  and names it by its path in `requirements.txt`. Two walkthroughs, a
  new project from nothing and an existing one, both run as written;
  Docker, updating and working on the framework beside a project
  follow. The README and the feature pages no longer say `pip install
  django-generic[...]`.

## [1.1.0] - 2026-09-26

### Added
- Searches ignore accents: `region` finds *Région Occitanie*. The
  project installs `generic.search`, and tickets and customers have
  trigram indexes on PostgreSQL. Some seeded names carry their accents
  to show it.
- Tickets and customers can be imported from a spreadsheet: *Import*
  on their lists. A ticket's reference and a customer's code find the
  record to update.
- The admin account is sent the open urgent tickets every weekday at
  eight (*Scheduled mailings*, in the Tasks group), and the scheduler
  runs the mailings every five minutes.
- A ticket moves through its life by buttons: *Wait for the customer*,
  *Customer answered*, *Resolve* (with a resolution), *Close*, and
  *Reopen* for supervisors (`example.reopen_ticket`). The status is no
  longer edited in forms, the Triage grid or imports, and the list's
  *Close* action is the generated one.
- Scripts call the API with a token made on the account page; the
  seed prints a read-only one for admin. `api/docs/` describes every
  endpoint.

### Fixed
- *Run now* hands the task to the Celery worker. The web server never
  loaded the project's Celery application, found no broker, and ran
  every task in the request; `example_project/__init__.py` now imports
  it, as Celery's guide for Django does.
- A page left quiet keeps its live connection. With redis-py 8, a reply
  from Redis is given up on after 5 seconds - the time channels-redis
  waits for the next event - and every quiet WebSocket was closed and
  reopened, deaf in between. The channel layer now waits 15.
- The development Docker stack migrates first, in a `migrate` service
  web, worker and beat wait for: beat no longer exits on a new
  database, its tables not there yet.
- `pytest` in the development image passes whoever owns the mounted
  checkout: the coverage data go to `/tmp`.
- Mail is configured the Django 6.1 way, with `MAILERS`, and still
  with `EMAIL_BACKEND` and the `EMAIL_*` settings on Django 5.2
  (`mail_settings` in `example_project/settings/base.py`). The same
  `EMAIL_*` variables drive production; without `EMAIL_HOST`, mail
  still goes to the log and `check --deploy` still has nothing to say.

## [1.0.0] - 2026-09-25

The example released with django-generic 1.0.0: a small support desk
chosen to show every feature at work.

### Screens
- Tickets, customers, time entries, teams, agents and tags, declared by
  hand in `example/resources.py`: coloured tags, summary pages with
  figures, charts and related tables, inlines, bulk actions, presets.
- Suppliers, equipment and maintenance visits declared with two
  `auto()` lines.
- External services and their incidents, a status API's answer served
  by data resources, with a runbook page per service.
- Pages of their own: a map of the customers and the same as GeoJSON, a
  ticket's timeline.
- Triage and a ticket's hours as grids; the classic server-rendered
  views kept under `/demo/` for comparison.
- *Live updates*: what the connection behind every page carries, each
  frame with what it made happen, and channels of the project's own.

### Running it
- `seed_example` fills the desk with customers, a few hundred tickets,
  time entries, comments, a wiki, a welcome message to everyone and
  three users - `admin`, `viewer` and `guest`, password `demo`.
- Development and production settings, and a Docker stack for each.
- `debug.py`, the server under a debugger in one process, and the VS
  Code configurations for it - server, a command, the tests, a Celery
  worker, and attaching to the development stack in Docker.

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
- Browser tests: `tests/browser/` drives the Support desk through a
  real Chromium - signing in, the ticket list (search, ordering,
  paging, a reload, a `status:open` chip, a bulk transition, the Excel
  download), the add and change forms, a summary page's tabs (the
  regression test for 1.1.0's `GenericDataTables.start` race), a
  transition's dialog, the Triage grid, an import, the command
  palette, the dark theme, French and the navigation on a phone - and
  fails on any error a page logs. Python Playwright through
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
- Logs a production can read, and errors somebody hears of.
  `generic.logs.logging_config()` logs to standard output and, when
  asked, to a file rotated at 10 MB that the web server, the Celery
  worker, the scheduler and `manage.py` share without losing a line
  (`SharedRotatingFileHandler`); every unexpected error, with its
  traceback, goes by mail to `ADMINS` - the same error once every ten
  minutes (`ERROR_MAIL_INTERVAL`), the next mail counting the ones
  held back. `admins()` writes `ADMINS` the way the running Django
  reads it, and `check --deploy` warns when it is empty
  (`generic.W009`). The example reads `DJANGO_ADMINS`,
  `DJANGO_LOG_FILE` and `DJANGO_LOG_LEVEL`; its production stack
  writes `/app/logs/app.log` in an `app-logs` volume from every
  service, and its worker now logs through the project's settings
  rather than Celery's own handlers. See docs/logging.md.
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
- The history no longer lists a decimal that did not change. A value
  set by code without its places - `Decimal(2)` in a field of two - was
  kept as `2`, the database gave `2.00` back, and the next save of
  anything else showed "Estimated hours 2.00 -> 2.00" as well. A
  version now holds decimals as the database does. Found by the
  browser tests.
- The installation guide says how the framework really arrives: it is
  not on PyPI, where `django-generic` is an unrelated package, so a
  project builds its wheel from the repository, keeps it in `vendor/`
  and names it by its path in `requirements.txt`. Two walkthroughs, a
  new project from nothing and an existing one, both run as written;
  Docker, updating and working on the framework beside a project
  follow. The README, the feature pages, the checks' hints and the
  error messages no longer say `pip install django-generic[...]`.
- *Mark all as read* works, in the bell and on the notifications page.
  The framework looked its endpoint up by a route name DRF never gave
  it, got no address, and the bell posted to the page itself (a 405);
  the notifications page left the button out.
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

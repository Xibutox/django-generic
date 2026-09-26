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

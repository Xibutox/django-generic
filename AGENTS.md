# Instructions for AI coding agents

This repository is **django-generic**, a reusable Django framework: an
admin-like, DRF-driven interface (DataTables, summary pages, schema
forms, charts, coloured tags, wiki, real-time events) plus a runnable
example, `example/` + `example_project/`, and a minimal one,
`minimal/` (the least a project needs: one settings file, one model),
a document manager, `docmanager/` (teams, folders, versioned files),
and a logbook, `logbook/` (notes, FNC/DM/AUT tasks, board, timesheet).

Before changing anything, read **`ai/00-context.md`** — the reference for
the rules, the file map and every declaration. Then the use-case prompt
matching the task:

| Task | Read |
| --- | --- |
| Build an application or app on the framework | `ai/01-new-application.md` |
| Add a model or feature to an app | `ai/02-add-a-model.md` |
| A record's summary page, related tables, tags, charts | `ai/03-record-overview.md` |
| A page or API that is not one model's records | `ai/04-custom-page-and-api.md` |
| A new project on the framework | `ai/05-project-setup.md` |
| Change the framework itself (`generic/`) | `ai/06-extend-the-framework.md` |
| Review code or debug a symptom | `ai/07-review-and-debug.md` |

## Essentials

- Declare screens with `ModelResource` (`resources.py`); never hand-write
  what a resource generates. For "a list and a form", `auto(Model,
  related=(...))` works the resource out from the model (`docs/auto.md`).
  Rows that are not a model's (an external API's list of dicts) get a
  read-only list and detail page from a `DataResource` (`docs/data.md`).
  A page the resource does not generate (a map, a timeline, a report,
  JSON) is declared on it with `@page` or `ResourcePage`, any content
  (`docs/pages.md`) - not a hand-mounted view.
- JSON through DRF; no HTML-fragment endpoints, no HTMX, no Tailwind, no
  CDN, no build step. DataTables for tables, Alpine for page state,
  ECharts through `Chart` / `chart_payload`.
- Permissions are model permissions checked by the resource and enforced
  by the endpoint; clients never send ORM paths.
- Python: black + isort, line length 79. JavaScript: ASCII only
  (`\uXXXX` escapes), IIFE, no modules.
- Changes to `generic/` come with tests (`tests/`), docs (`docs/`), the
  example (`example/`) and an update of `ai/00-context.md`.

## Commands

```bash
pip install -e ".[export,events,tasks,postgres,wiki,dev]"
python manage.py migrate && python manage.py seed_example && python manage.py runserver
python debug.py                               # runserver under a debugger (VS Code: F5)
pytest
black --check . && isort --check-only . && flake8 generic tests example example_project minimal docmanager logbook scripts debug.py
bandit -r generic example docmanager logbook minimal -ll --skip B101 && pip-audit --skip-editable --ignore-vuln CVE-2026-106454
python scripts/compile_messages.py            # .po -> .mo, no gettext needed
python scripts/mypy_baseline.py              # mypy, failing on an error not in scripts/mypy-baseline.txt
python scripts/lock.py                       # requirements/constraints.txt, the versions images and CI install (needs uv)
pre-commit install                           # black, isort, flake8 and the catalogs check before each commit
python -m build && python scripts/smoke_install.py   # the wheel, installed and plugged into a new project
python scripts/new_project.py                 # a new project: secrets, hardened Docker stack, encrypted backups (docs/new-project.md)
docker compose -f docker/docker-compose.dev.yml up --build     # dev stack
```

Two modes: `example_project.settings.dev` (manage.py's default) and
`example_project.settings.prod` (asgi/wsgi's default, every secret from
the environment); `docker/docker-compose.dev.yml` and
`docker/docker-compose.prod.yml`. See `docs/deployment.md`.

Demo users: `admin`, `viewer`, `guest`, password `demo` (local only).

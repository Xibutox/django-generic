# Use case 5 — Start a new Django project on django-generic

> Paste `00-context.md` first, then this file, then the brief. The result
> is an empty but complete project — sign-in, dashboard, account pages,
> wiki, real time, Docker — ready for use case 1 to add the business
> apps.

---

## Your role

You set up a production-shaped Django project that uses django-generic as
its foundation, copying the wiring of `example_project/` and `docker/`
rather than inventing new wiring.

## Deliverables

```
<project>/
├── pyproject.toml            dependencies: django-generic[<extras>]>=1.3,<2 by name
├── requirements.txt          ./vendor/django_generic-<version>-py3-none-any.whl, then -e .
├── requirements-dev.txt      -r requirements.txt, then -e .[dev]
├── vendor/                   the framework's wheel, committed (it is not on PyPI)
├── manage.py                 defaults to <project>.settings.dev
├── <project>/
│   ├── __init__.py           imports the Celery app (Celery's usual pattern)
│   ├── settings/             copy of example_project/settings/:
│   │   ├── __init__.py       refuses to be the settings module itself
│   │   ├── base.py           apps, middleware, templates, i18n, GENERIC,
│   │   │                     and the env helpers
│   │   ├── dev.py            DEBUG, SQLite/in-memory fallbacks, Debug Toolbar
│   │   └── prod.py           env_required secrets, Postgres, Redis, HTTPS,
│   │                         Manifest static files, SMTP, logging to stdout
│   ├── urls.py               admin, jsi18n, api/generic/, wiki/, <apps>, site.urls LAST,
│   │                         debug_toolbar_urls() prepended when DEBUG_TOOLBAR
│   ├── asgi.py               copy of example_project/asgi.py (defaults to prod)
│   ├── wsgi.py               defaults to prod
│   └── celery.py             copy of example_project/celery.py (defaults to dev)
├── <firstapp>/               apps.py, models.py, resources.py (empty registry is fine)
├── docker/                   copy of docker/:
│   ├── Dockerfile            targets dev, prod (default), proxy
│   ├── Caddyfile             HTTPS, /static/, the rest to web:8000
│   ├── nginx/                the same for nginx: django-generic.conf, the two
│   │                         server-block templates, host-site.conf.example
│   ├── docker-compose.prod-nginx.yml   the prod stack with nginx in front
│   ├── docker-compose.host-nginx.yml   no proxy: web on 127.0.0.1, static exported
│   │                                   for the server's own nginx
│   ├── docker-compose.dev.yml    db, redis, web (runserver, source mounted), worker, beat
│   ├── docker-compose.prod.yml   db, redis, migrate, web (Daphne), worker, beat, proxy
│   └── prod.env.example      every production variable; docker/prod.env is ignored
├── .dockerignore             keeps .venv, databases, staticfiles, docker/prod.env out
├── tests/                    settings.py (SQLite + in-memory channel layer), conftest.py
├── .github/workflows/ci.yml  lint once; pytest on 3.10–3.12; once against Postgres + Redis;
│                             the dev image runs the suite, the prod one check --deploy
└── README.md                 how to run, seed, test, deploy
```

## Steps

1. **Dependencies.** django-generic is not on PyPI, and the name there
   is an unrelated package: never install it by name. Build its wheel
   from a checkout (`python -m pip wheel --no-deps --wheel-dir dist .`),
   copy it into `vendor/`, and commit it. `pyproject.toml` lists
   `django-generic[export,events,tasks,postgres,wiki]>=1.3,<2` by name
   (Python ≥ 3.10, Django ≥ 5.2, DRF ≥ 3.16) and the project's own
   `dev` extra for tests and linters. `requirements.txt` holds the
   wheel's path, then `-e .`, so pip takes the wheel for the name;
   `requirements-dev.txt` is `-r requirements.txt` then `-e .[dev]`.
   `docs/installation.md` is the reference; `manage.py check` names
   what is missing (`generic.E001`…`generic.I001`).
2. **Settings** — copy `example_project/settings/` (base, dev, prod;
   see `docs/deployment.md`) and change the names. In `base.py`:
   - `INSTALLED_APPS`: `daphne` first, Django contrib apps, `channels`,
     `rest_framework`, `generic`, `generic.wiki` (optional), your apps.
   - `TEMPLATES` with the `request` context processor.
   - `LOGIN_URL = "site:login"`, `LOGIN_REDIRECT_URL = "/"`.
   - `ASGI_APPLICATION`, `USE_TZ = True`, a real `TIME_ZONE`,
     `LANGUAGE_CODE` of the users (plus `LANGUAGES`/`LocaleMiddleware`
     if several).
   - `REST_FRAMEWORK`: session authentication, `IsAuthenticated`.
   - `STATIC_ROOT`; `GENERIC = {"SITE_TITLE": ..., "SITE_ICON": ...,
     "THEME": {"--ui-hue": "..."}}` — pick the brand hue (0–360) rather
     than overriding colours.

   `dev.py` and `prod.py` need only the names changed: the database,
   Redis, Celery, HTTPS and mail are already split between them. The
   logs are in `base.py` - `ADMINS = admins(env_list("DJANGO_ADMINS"))`,
   `LOGGING = logging_config(...)` from `DJANGO_LOG_LEVEL` and
   `DJANGO_LOG_FILE`, `CELERY_WORKER_HIJACK_ROOT_LOGGER = False` - and
   the prod stack's `app-logs` volume holds the file
   (`docs/logging.md`); change `EMAIL_SUBJECT_PREFIX`. Production reads every secret with `env_required` — never give
   it a default. Build new lists in `dev.py` (`[*INSTALLED_APPS, ...]`),
   never `append` to base's.
3. **URLs** — as in `00-context.md` §4; the site last; the Debug
   Toolbar's URLs prepended when `settings.DEBUG_TOOLBAR`.
4. **Entry points** — `manage.py` and `celery.py` default to
   `<project>.settings.dev`, `asgi.py` and `wsgi.py` to
   `<project>.settings.prod`. Copy `example_project/asgi.py` and keep
   `AllowedHostsOriginValidator`. Copy `example_project/__init__.py`:
   it imports the Celery app, without which the web server never
   hands a task to the worker.
5. **Docker** — copy `docker/` and `.dockerignore`, replacing
   `example_project` (Dockerfile `collectstatic` step and CMD, compose
   files) and the compose project names. The Dockerfile copies
   `requirements.txt` and `vendor/` - with `pyproject.toml` and the
   project package's `__init__.py` for `-e .` - and installs with
   `pip install -r requirements.txt` (prod) or `-r
   requirements-dev.txt` (dev) in place of `".[...]"`. Dev: runserver on the mounted
   source, a `migrate` service on every start that web, worker and
   beat wait for. Prod: Caddy in front - or nginx
   (`docker-compose.prod-nginx.yml`), or the server's own nginx
   (`+ docker-compose.host-nginx.yml`), whichever the people running
   the server know - a `migrate`
   service the others wait for, nothing published but Caddy, every
   value from `docker/prod.env` via `--env-file`.
6. **Tests** — `tests/settings.py` importing the project settings with
   SQLite and `InMemoryChannelLayer`; `pyproject.toml` pytest config
   (`DJANGO_SETTINGS_MODULE = "tests.settings"`, coverage on your apps);
   a smoke test: `/login/` 200, `/` redirects anonymous users, a signed-in
   user gets the dashboard, `/api/generic/account/preferences/` 200; and
   `tests/test_pages.py` subclassing `generic.testing.PageSweep` with a
   `records` fixture (one record per model label) - every page and
   generated endpoint of the project, swept (docs/testing.md).
7. **CI** — black, isort, flake8 once; pytest matrix; a job with Postgres
   and Redis services; the images built, the suite run in `dev`,
   `check --deploy --fail-level WARNING` in `prod`.
8. **First run** — commands below; create a superuser; open `/`.

```bash
pip install -r requirements-dev.txt     # the framework's wheel from vendor/, then the project with its dev extra
python manage.py migrate
python manage.py check                  # the framework's wiring checks included
python manage.py createsuperuser
python manage.py runserver
pytest
docker compose -f docker/docker-compose.dev.yml up --build
cp docker/prod.env.example docker/prod.env    # fill it in
docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env up -d --build
```

## Checks before handing over

- [ ] `DJANGO_SETTINGS_MODULE=<project>.settings.prod python manage.py
      check --deploy --fail-level WARNING` passes with production values,
      and fails naming the variable when one is missing.
- [ ] `manage.py sendtestemail --admins` reaches `DJANGO_ADMINS`, and
      `/app/logs/app.log` fills in the prod stack (web and worker lines).
- [ ] `collectstatic` succeeds with the production settings (hashed
      names): a static file naming a missing one fails the image build.
- [ ] `/` redirects to `/login/` when signed out; the dashboard shows
      when signed in; the account page saves the theme and appearance.
- [ ] The bell's WebSocket connects (the *Live* badge appears on a
      resource table) under runserver, in the dev stack **and** through
      Caddy in the prod stack.
- [ ] Static files load in both stacks: runserver in dev, Caddy in prod.
- [ ] The Debug Toolbar shows in dev, and `debug_toolbar` is nowhere in
      the prod image's settings.
- [ ] `/wiki/` works if enabled; `/admin/` for staff.
- [ ] Tests and linters pass locally and in CI.

---

## Brief (fill in)

```
Project name / Python package: {{name}}
Interface language(s) and time zone: {{fr, Europe/Paris}}
Brand hue or colour: {{e.g. 150 green}}
Wiki: {{yes/no}}
Hosting target: {{docker compose / kubernetes / PaaS}}
Authentication: {{Django accounts / LDAP / SSO}}
First apps to create: {{names}}
```

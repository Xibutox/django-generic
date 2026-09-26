# Development and production

The example project runs two ways, and a new project copies both:

| | Development | Production |
| --- | --- | --- |
| Settings | `example_project.settings.dev` | `example_project.settings.prod` |
| `DEBUG` | on | off, always |
| Secrets | a fixed development key | from the environment, or no start |
| Database | SQLite, or Postgres when `DATABASE_URL` is set | Postgres, required |
| Events, cache | in memory, or Redis when `REDIS_URL` is set | Redis, required |
| Tasks | run in the request without a broker | a Celery worker, always |
| Static files | served by runserver from the apps | collected with hashed names, served by Caddy |
| HTTPS | no | assumed: secure cookies, redirect, HSTS |
| Mail | printed to the console | SMTP, or the log without `EMAIL_HOST` |
| Debug Toolbar | on when installed | never installed |
| Docker | `docker/docker-compose.dev.yml` | `docker/docker-compose.prod.yml` |

## The settings

```
example_project/settings/
├── __init__.py     which module is which; refuses to be used alone
├── base.py         what the project is: apps, middleware, templates,
│                   languages, GENERIC - and the helpers reading the
│                   environment (env, env_bool, env_list, env_required,
│                   database_from_url, redis_backends)
├── dev.py          from .base import *, then development
└── prod.py         from .base import *, then production
```

Which one runs is `DJANGO_SETTINGS_MODULE`, and each entry point has
its default:

| Entry point | Default | Why |
| --- | --- | --- |
| `manage.py` | `dev` | what a developer types |
| `debug.py` | `dev` | `manage.py` under a debugger ([Debugging](#debugging)) |
| `example_project/celery.py` | `dev` | the same |
| `example_project/asgi.py` | `prod` | what a server imports: a server started without the variable must never run with DEBUG on |
| `example_project/wsgi.py` | `prod` | the same |

`example_project/__init__.py` imports the Celery application, as
Celery's own guide for Django does, so that every process of the
project has it - the web server and `manage.py` as well as the worker.
Without it only the worker would: a task started from a page would find
no broker configured and run in the request, the worker idle.

The production image sets `DJANGO_SETTINGS_MODULE` for every command
run in it, `manage.py` included. `example_project.settings` alone is
refused with a message saying which two to choose from — it is what an
environment set up for the single `settings.py` of earlier versions
still names.

**Production refuses to start** without `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS`, `DATABASE_URL` or `REDIS_URL`, naming the one
that is missing. A server that falls back to a development value runs,
and is not safe.

`dev.py` builds new lists when it adds the Debug Toolbar rather than
appending to base's: both modules share `base`, and production must
never inherit what development added.

## Development

On your machine, nothing to start but Django:

```bash
python manage.py migrate
python manage.py seed_example
python manage.py runserver
```

Or with the backends production runs, in Docker:

```bash
docker compose -f docker/docker-compose.dev.yml up --build
```

```bash
docker compose -f docker/docker-compose.dev.yml exec web python manage.py seed_example
```

- **migrate** runs `migrate --noinput` and exits; web, worker and beat
  wait for it to succeed. Beat reads its schedules the moment it
  starts, and on a new database would find no table. A branch that
  adds a migration is one more `up`.
- **web** runs `runserver 0.0.0.0:8000` from the `dev` image, with the
  working copy mounted over `/app`: a change to the code reloads the
  server, as on the host.
- **worker** and **beat** run Celery from the same image. Celery does
  not reload: after changing a task, restart the worker —
  `docker compose -f docker/docker-compose.dev.yml restart worker`.
- **db** (Postgres 16) and **redis** are published on 5432 and 6379,
  for a client on the host. Override with `POSTGRES_PORT`,
  `REDIS_PORT`, `WEB_PORT` - and `DEBUGPY_PORT`, 5678, where a
  debugger attaches ([Debugging](#debugging)).
- The Debug Toolbar shows for the host's browser: in a container it
  recognises the Docker gateway (see [the example](example.md#the-debug-toolbar)).

The suite runs there too, against that Postgres and Redis:

```bash
docker compose -f docker/docker-compose.dev.yml run --rm web pytest
```

The image keeps the coverage data in `/tmp` (`COVERAGE_FILE`): the
working copy mounted over `/app` is the host user's, who is not always
the container's uid 1000.

Nothing in this stack is a secret — fixed passwords, published ports.
Never expose it beyond your machine.

### Debugging

`manage.py runserver` serves the requests from a child process it
restarts on every change: a debugger that started `manage.py` is
attached to the parent, and its breakpoints are never hit. `debug.py`,
at the root, runs the same server in one process:

```bash
python debug.py
```

It is `manage.py runserver --noreload 127.0.0.1:8000` with the
development settings, and takes what `manage.py` takes: an address
(`python debug.py 0.0.0.0:8001`), runserver's options, or any other
command (`python debug.py seed_example`). Without a Celery broker a
task runs in the request that sends it, so a breakpoint in a task is
hit here too.

**VS Code.** The repository carries its `.vscode` folder: open it,
accept the recommended extensions (the Python Debugger among them),
select `.venv` as the interpreter, and press F5. `launch.json` offers:

| Configuration | What it starts |
| --- | --- |
| Django: debug.py (runserver) | the server; breakpoints in your code and in templates |
| Django: debug.py, into the libraries | the same, stepping into Django, DRF and the rest |
| Django: debug.py with reload | the server with its reloader: it restarts on save, the debugger follows the child |
| Django: a manage.py command | asks for a command - `seed_example`, `migrate generic 0012` - and runs it |
| Pytest: this file | the test file open in the editor |
| Pytest: tests matching... | the tests whose name matches a `-k` expression |
| Celery: worker | a worker in one process (`--pool=solo`); needs a broker |
| Django + Celery worker | both, stopped together |
| Docker: attach to the web container | attaches to the development stack's server, below |

The tests run without coverage under the debugger (`--no-cov`):
coverage's tracer and the debugger's cannot share the process, and
the breakpoints would be skipped. `settings.json` sets the test
explorer up the same way, and formats with black and isort on save.

For the worker, a broker: the development stack's Redis, and a `.env`
file at the root - VS Code passes it to every configuration, so the
server sends its tasks to the worker instead of running them itself:

```
CELERY_BROKER_URL=redis://localhost:6379/1
```

**In Docker.** The server waits for a debugger on port 5678, which the
development stack publishes; `debugpy` comes with the `dev` extra.
Stop the stack's own server, start this one, then run *Docker: attach
to the web container*:

```bash
docker compose -f docker/docker-compose.dev.yml stop web
```

```bash
docker compose -f docker/docker-compose.dev.yml run --rm --service-ports web python -Xfrozen_modules=off debug.py --listen 0.0.0.0:5678 --wait 0.0.0.0:8000
```

`--listen` opens the port, `--wait` holds the start until the debugger
is there; `-Xfrozen_modules=off` is what a debugger that starts Python
passes by itself. The container sees the working copy as `/app`,
which the configuration maps to the folder open in VS Code. Any other
client of debugpy - `nvim-dap`, for one - attaches to the same port.
`--listen` and `--reload` are refused together: the reloader would
replace the process the debugger is attached to at the first save.

## Production

```bash
cp docker/prod.env.example docker/prod.env
```

Fill in `docker/prod.env` — it is in `.gitignore` and `.dockerignore`,
never commit it — then:

```bash
docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env up -d --build
```

```bash
docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env exec web python manage.py createsuperuser
```

`--env-file` matters: the compose file reads every value from it, and a
missing required one stops `docker compose` before anything starts.

| Service | Image | Does |
| --- | --- | --- |
| **proxy** | `proxy` target: Caddy + the static files | HTTPS (certificates obtained and renewed by itself), the static files with long cache headers, everything else to Daphne, WebSockets included |
| **web** | `prod` target | Daphne, `--proxy-headers`; not published — only the proxy reaches it |
| **migrate** | `prod` target | `migrate --noinput`, once per start; web, worker and beat wait for it to succeed |
| **worker** | `prod` target | the Celery worker |
| **beat** | `prod` target | the scheduler, reading the Schedules pages. One, never two: each would send every task |
| **db** | `postgres:16-alpine` | not published; data in the `postgres-data` volume |
| **redis** | `redis:7-alpine` | not published; kept on disk (`appendonly`), since the task queue lives there |

### The variables

`docker/prod.env.example` lists them all, with what each does. The
ones that matter first:

| Variable | Example | Notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | 50 random characters | **Required.** `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_ALLOWED_HOSTS` | `desk.example.com` | **Required.** Comma-separated |
| `POSTGRES_PASSWORD` | | **Required.** Letters and digits, or percent-encoded: it goes into a URL |
| `SITE_ADDRESS` | `desk.example.com` | What Caddy serves and certifies. `:80` for plain HTTP |
| `DJANGO_HTTPS` | `1` | `0` only to try the stack over HTTP |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://desk.example.com` | Scheme included |
| `DJANGO_SITE_URL` | `https://desk.example.com` | For the links in the mails the site sends |
| `DJANGO_HSTS_SECONDS` | `31536000` | One hour by default; raise it once HTTPS works everywhere |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | | Without `EMAIL_HOST`, mails go to the log |
| `DJANGO_LOG_LEVEL` | `INFO` | Everything is logged to standard output: `docker compose ... logs web` |

### Trying it on your machine

In `docker/prod.env`: `SITE_ADDRESS=:80`, `DJANGO_HTTPS=0`,
`DJANGO_ALLOWED_HOSTS=localhost`, then the same `up` and open
<http://localhost/>. `DJANGO_HTTPS=0` matters: secure cookies are never
sent back over plain HTTP, and signing in would fail without a word.

### What production does that development does not

- **Static files** are collected when the image is built, with a hash
  of their content in every name (`ManifestStaticFilesStorage`), and
  served by Caddy with a year's cache. A release changes the names of
  what changed, so a browser never mixes two versions. The build fails
  if a file refers to one that is not there — a vendored script
  mentioning a source map it does not ship is enough.
- **HTTPS** is assumed: the proxy terminates it and says so in
  `X-Forwarded-Proto`, which Django trusts
  (`SECURE_PROXY_SSL_HEADER`); cookies are secure, HTTP redirects to
  HTTPS, HSTS is sent. Caddy overwrites any `X-Forwarded-*` a client
  sends, so the header cannot be forged from outside.
- **No persistent database connections**: under an ASGI server each
  request may run on a different thread, and a kept connection is
  never reused. Pool in front of Postgres if connections become the
  limit.
- **`check --deploy`** has nothing to say:

  ```bash
  docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env exec web python manage.py check --deploy
  ```

  `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD` are off
  unless asked for — they promise things about every subdomain and the
  browsers' built-in list — and their two warnings are silenced while
  they are, so that a warning there still means one.

### Updating

```bash
docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env up -d --build
```

The images are rebuilt, `migrate` runs, and web, worker and beat are
replaced once it has succeeded.

### Backups

The database is the only state worth keeping — Redis holds the queue
and the cache, Caddy its certificates:

```bash
docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env exec -T db pg_dump -U generic generic > backup.sql
```

### More than one web process

Daphne is one process. Events already work across several, through
Redis. To run more, add web services (or replicas behind a load
balancer) and list them in the Caddyfile's `reverse_proxy`, which
balances between its upstreams.

## The images

`docker/Dockerfile` builds three, by target:

| Target | From | Holds |
| --- | --- | --- |
| `dev` | `python:3.12-slim` | every extra, the test tools, the Debug Toolbar, the source; `runserver` |
| `prod` (default) | `python:3.12-slim` | `export,events,tasks,postgres,wiki` and the scheduler, the source, the collected static files; Daphne, as user `app` |
| `proxy` | `caddy:2-alpine` | `docker/Caddyfile` and the static files collected by the `prod` build |

The dependencies are installed from `pyproject.toml` and a stub of the
package before the source is copied, so a change to the code rebuilds
in seconds. `django-celery-beat` is installed with `--no-deps` — its
metadata still pins Django below 6.1 — and its own dependencies by
name. `.dockerignore` keeps local environments, databases, collected
files and `docker/prod.env` out of every image.

CI builds all three: the suite runs in `dev`, `check --deploy` in
`prod`, and `prod` and `proxy` are pushed (see `.gitlab-ci.yml`).

## Starting a new project from this one

The framework itself is a dependency, not something to copy: the new
project's `pyproject.toml` lists
`django-generic[export,events,tasks,postgres,wiki]`, which the
Dockerfile's `pip install ".[...]"` then brings in with the rest (see
[Installation](installation.md)).

Copy `example_project/` (renamed), `manage.py`, `docker/`,
`.dockerignore` and the `tests/settings.py` pattern, then replace:

- `example_project` with your package name — in the four entry
  points, `ROOT_URLCONF`, `WSGI_APPLICATION`, `ASGI_APPLICATION`, the
  Dockerfile's `collectstatic` step and CMD, and the compose files;
- the `example` app in `INSTALLED_APPS` with yours, and `GENERIC`'s
  title, icon and help;
- `django-generic` in the compose project names.

[Use case 5](../ai/05-project-setup.md) walks an assistant through the
same steps.

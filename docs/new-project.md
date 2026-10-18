# A new project, ready to deploy

`scripts/new_project.py` writes a complete Django project on the
framework in one command: the code, the framework's wheel, the Docker
stacks for development and production, every secret random, and
encrypted backups that check themselves and restore in one command.
The production stack follows the ISO/IEC 27002:2022 guidance for the
controls a deployment touches, and the project carries a
`SECURITY-CONTROLS.md` saying which choice answers which control.

It needs Python 3.10 or later and nothing installed (the standard
library alone); the project it writes needs Docker with Compose v2.
The same commands work on Windows, macOS and Linux.

```bash
git clone https://github.com/Xibutox/django-generic.git
cd django-generic
python scripts/new_project.py                 # asks, with a default for each answer
```

or, asking nothing:

```bash
python scripts/new_project.py ../desk --name desk --title "Support desk" \
    --domain desk.example.com --admins ops@example.com --no-input
```

| Option | Default | Is |
| --- | --- | --- |
| `TARGET` | `../mysite` | the new project's folder; must not exist, or be empty |
| `--name` | the folder's name | the Python package of the project |
| `--app` | `core` | its first app, with one model (`Item`) to replace |
| `--title` | from the name | the site's title |
| `--domain` | `localhost` | the site's name; Caddy obtains its certificate. `localhost` serves plain HTTP, to try the stack on this machine |
| `--admins` | none | who is mailed the errors |
| `--time-zone` | `Europe/Paris` | the servers' time zone, and the backups' |
| `--language` | `en` | `en` or `fr` |
| `--wheel PATH` / `--no-wheel` | built from this checkout | the framework's wheel for `vendor/` |
| `--no-input` | | ask nothing: the defaults |

Then, in the new folder:

```bash
python ops.py up                       # build and start the production stack
python ops.py manage createsuperuser   # the first account
python ops.py backup                   # a first backup
```

## What it writes

```
desk/
├── ops.py                 every command below, Python's standard library only
├── README.md              how to run, back up, restore, update - for the project's team
├── SECURITY-CONTROLS.md   ISO/IEC 27001 Annex A control → what the setup does, and what remains
├── pyproject.toml         django-generic[export,events,tasks,postgres,wiki], argon2-cffi
├── requirements.txt       ./vendor/django_generic-<version>-py3-none-any.whl, then -e .
├── requirements-dev.txt   + pytest, black, isort, flake8, pip-audit, the Debug Toolbar
├── vendor/                the framework's wheel (it is not on PyPI)
├── manage.py
├── desk/                  settings/{base,dev,prod}.py, urls, asgi, wsgi, celery
├── core/                  apps.py, models.py (Item), resources.py (auto(Item)), migrations
├── tests/                 settings.py, test_smoke.py
├── backups/               the backups (ignored by git)
└── docker/
    ├── Dockerfile         targets dev, prod, proxy (Caddy), backup (Postgres + GnuPG)
    ├── Caddyfile
    ├── compose.dev.yml    runserver on the mounted source; ports on 127.0.0.1 only
    ├── compose.prod.yml   the hardened stack, below
    ├── backup/            backup.sh, restore.sh, common.sh
    ├── prod.env           every production setting and secret (0600, ignored)
    └── dev.env            the development stack's own secrets (0600, ignored)
```

The settings are those of `example_project/settings/` - production
reads every secret with `env_required` and refuses to start without
it - with what a new deployment should start with: Argon2 first among
the password hashers, passwords of 12 characters or more, sessions of
8 hours, the sign-in lockout, and the access and security logs kept a
year (`apply_retention`).

## The secrets

`ops.py env` - which the script runs once - writes `docker/prod.env`
and `docker/dev.env`: Django's secret key (50 random bytes), the
database's and Redis's passwords and the backups' passphrase (32 random
bytes each, 256 bits), from Python's `secrets`, different in each file
and in each project. The files are created readable by their owner
alone, and `.gitignore` and `.dockerignore` keep them out of git and of
every image. Compose refuses to start a stack missing one
(`${VAR:?...}`), and production settings refuse to start without
them.

`ops.py env` never replaces an existing file unless given `--force`,
which keeps the old one aside (`prod.env.bak-<time>`): the database was
created with the old password, and the backups encrypted with the old
passphrase.

## The production stack

`docker/compose.prod.yml`: Caddy, Daphne, Celery's worker and
scheduler, Postgres, Redis, a one-off `migrate`, and the `backup`
service. Every container:

- may not gain privileges (`no-new-privileges`), drops every Linux
  capability and adds back only those its image's entry point needs
  (Postgres's, to prepare its folder; Caddy's, to listen on 80 and
  443; the backups', to read the uploaded files and write their
  folder). Redis and the application run as their own users with none;
- runs on a **read-only** filesystem, writing only to its volumes and
  an in-memory `/tmp`;
- has a memory and a process limit, and its log rotated (10 × 10 MB).

Three networks: `frontend` (Caddy, Daphne), `backend` - `internal`, no
route out, nothing published - for Postgres, Redis, the scheduler and
the backups, and `outbound` for the web server and the worker, which
send mail. Only Caddy publishes ports. Postgres checks passwords with
SCRAM-SHA-256 and checksums every data page; Redis requires its
password, read from a file rather than its command line.

The base images are pinned by minor version in the Dockerfile's
`ARG`s; `build --pull` takes their security fixes.

## The backups

Every day at `BACKUP_TIME`, the `backup` service:

1. dumps the database (`pg_dump`, custom format) and packs the uploaded
   files (`app-media`), each streamed straight into GnuPG - AES-256,
   from `BACKUP_PASSPHRASE` - so nothing unencrypted reaches the disk;
2. writes a `MANIFEST` (versions, SHA-256 of both files) and checks the
   backup: the checksums, then both files decrypted and read through
   (`pg_restore --list`, `tar -t`). Only then does `NAME.partial` take
   its final name;
3. deletes the backups older than `BACKUP_KEEP_DAYS`, never the newest;
4. on `BACKUP_TEST_WEEKDAY`, restores the newest in full into a
   throwaway database, counts its tables, migrations and files, drops
   it, and appends the result to `backups/restore-tests.log` - the
   restore test record ISO/IEC 27002 8.13 asks for.

The backup image is the database's own (`postgres:17`): `pg_dump` of
the server's version, and GnuPG already in it.

| Command | Does |
| --- | --- |
| `python ops.py backup` | a backup now |
| `python ops.py backups` | the list |
| `python ops.py verify [NAME]` | steps 2's checks on any backup |
| `python ops.py restore-test [NAME]` | step 4, now |
| `python ops.py restore NAME` | asks to type the project's name (`--yes` does not), takes a backup of the present state, stops the site, the workers and the scheduled backups, restores - the database into a new database beside the live one and the files beside the live ones, switched only once both are complete - then starts everything again |

`latest` names the newest backup, resolved before the safety backup is
taken. Any machine with GnuPG and Postgres's tools reads a backup by
hand (the project's README says how), so a lost server is not a lost
backup - provided `backups/` is copied off it and the passphrase kept
elsewhere: the two things the project's `SECURITY-CONTROLS.md` leaves
to the people running it.

## Kept working

`tests/test_new_project.py` writes a project and checks it: every file
filled in, the secrets random, private and never repeated, each
container's restrictions and the networks, the scripts' order of
operations, the production settings refusing to start without a secret
and passing `check --deploy`, and the project's own smoke test. CI's
`new-project` job writes one, starts it with `ops.py up`, and backs it
up, verifies, test-restores and restores it.

Changing the template - `scripts/project_template/`, every file ending
in `.tpl`, `{{ name }}` filled in by the script - is changing what every
new project starts with: run the test and, with Docker, the job's
steps.

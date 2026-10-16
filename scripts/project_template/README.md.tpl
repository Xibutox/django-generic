# {{ title }}

A Django project on [django-generic](https://github.com/Xibutox/django-generic)
{{ version }}, written by its `scripts/new_project.py`.

Everything below runs from this folder, the same on Windows, macOS and
Linux. Docker (with Compose v2) and Python 3.10+ are all it needs.

## First start

```bash
python ops.py up                       # build the images and start the stack
python ops.py manage createsuperuser   # the first account
python ops.py backup                   # a first backup, to see it work
```

Then open the site: <http://localhost/> when the domain was `localhost`,
`https://<domain>/` otherwise (ports 80 and 443 must reach the server:
Caddy obtains the certificate by itself).

`docker/prod.env` and `docker/dev.env` were written with random
secrets. **Copy `BACKUP_PASSPHRASE` from `docker/prod.env` into a
password manager now**: without it no backup can be read. Neither file
is committed, nor copied into an image. `python ops.py env --force`
writes new ones (the old ones are kept aside), for a new installation.

## The commands

| Command | Does |
| --- | --- |
| `python ops.py up` / `down` / `ps` / `logs [service]` | the production stack; `--dev` for the development one |
| `python ops.py manage ...` | `manage.py` in the web container: `createsuperuser`, `check --deploy`, `apply_retention` |
| `python ops.py backup` | an encrypted backup, now |
| `python ops.py backups` | the backups, newest last |
| `python ops.py verify [NAME]` | a backup's checksums, decrypted and read through |
| `python ops.py restore-test [NAME]` | restored in full into a throwaway database, then dropped; the result is added to `backups/restore-tests.log` |
| `python ops.py restore NAME` | back to a backup (`latest` for the newest) |

## Backups

The `backup` service of the production stack, every day at
`BACKUP_TIME`:

1. dumps the database (`pg_dump`, Postgres's own format) and packs the
   uploaded files, together, and encrypts both on the fly with GnuPG
   (AES-256, from `BACKUP_PASSPHRASE`): nothing unencrypted ever
   reaches the disk;
2. writes their SHA-256 in a `MANIFEST`, then **checks the backup**:
   the checksums, both files decrypted and read through. Only a backup
   that passed gets its final name; `*.partial` is one that did not;
3. deletes the backups older than `BACKUP_KEEP_DAYS` (the newest is
   always kept);
4. once a week (`BACKUP_TEST_WEEKDAY`), **restores the newest one in
   full** into a throwaway database, counts what came back, drops it,
   and records the result in `backups/restore-tests.log`.

Each backup is a folder in `backups/` (`BACKUP_DIR`):

```text
backups/{{ slug }}-20261016T023000Z/
    database.dump.gpg
    media.tar.gz.gpg
    MANIFEST
backups/restore-tests.log
```

**Copy `backups/` off the server** - another machine, a NAS, an object
store (`rsync`, `rclone`, the host's own backup): a backup on the disk
it protects is lost with it. The files are encrypted, so the copy can
go anywhere.

### Restoring

```bash
python ops.py backups             # which one
python ops.py restore latest      # or a name from the list
```

It asks you to type `{{ slug }}`, then:

1. takes a backup of the present state (so a restore can be undone by
   restoring that one);
2. stops the site and the workers;
3. checks the backup, restores the database **beside** the live one and
   unpacks the files beside the live ones - a restore that fails there
   changes nothing - then switches both;
4. starts everything again.

On a new server: copy the project (with `docker/prod.env`, or a new one
whose `BACKUP_PASSPHRASE` is the old one), put the backup folder in
`backups/`, `python ops.py up`, then `python ops.py restore NAME`.

### Restoring by hand

Any machine with GnuPG and Postgres's tools reads a backup, without
this project:

```bash
gpg --decrypt database.dump.gpg > database.dump       # asks for BACKUP_PASSPHRASE
pg_restore --no-owner -d DATABASE database.dump
gpg --decrypt media.tar.gz.gpg | tar -xzf - -C /path/to/media
```

## Developing

With Docker - Postgres and Redis in containers, runserver reloading on
every change, on <http://127.0.0.1:8000/>:

```bash
python ops.py up --dev
```

Or on this machine alone (SQLite, nothing to start):

```bash
python -m venv .venv
.venv\Scripts\activate                  # macOS, Linux: source .venv/bin/activate
pip install -r requirements-dev.txt     # the framework from vendor/
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
pytest
```

The screens are declared in `{{ app }}/resources.py`: start with the
framework's `ai/01-new-application.md` and `docs/auto.md`.

## Updating

- **The framework**: build its new wheel (`python -m pip wheel --no-deps
  --wheel-dir dist .` in its checkout), replace the one in `vendor/`,
  change its name in `requirements.txt`, then `python ops.py up`.
- **The base images' security fixes**: `docker compose -f
  docker/compose.prod.yml --env-file docker/prod.env build --pull`,
  then `python ops.py up`. Their versions are the `ARG`s at the top of
  `docker/Dockerfile`.
- **Known vulnerabilities** in the Python packages: `pip-audit` (in the
  dev requirements).

## Security

[SECURITY-CONTROLS.md](SECURITY-CONTROLS.md) lists what this setup
does for each ISO/IEC 27001:2022 Annex A control it touches, and what
remains the organisation's to do.

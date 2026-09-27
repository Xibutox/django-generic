# Logs and error reports

Django and the framework log every unexpected error with its traceback -
a page or an API call that raised, a task that failed, a mail that could
not leave, a live event that could not be sent. `generic.logs` decides
where those records go in production:

- **standard output**, always - what `runserver` prints, what
  `docker compose logs` and systemd's journal keep;
- **a file**, when one is named - rotated by size, and shared safely by
  every process that writes it: the web server, the Celery worker and
  its children, the scheduler, a `manage.py` command;
- **a mail to `ADMINS`** for every error, when `DEBUG` is off - the same
  error at most once every ten minutes, the next mail saying how many
  were held back.

## Turning it on

```python
# settings.py
from generic.logs import admins, logging_config

ADMINS = admins(["ops@example.com", "lead@example.com"])
SERVER_EMAIL = "desk@example.com"           # the sender of those mails
EMAIL_SUBJECT_PREFIX = "[Support desk] "

LOGGING = logging_config(
    level="INFO",                           # the least a record needs
    file=BASE_DIR / "logs" / "app.log",     # optional
)

# With Celery: the worker logs through LOGGING like every other process.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
```

The mails leave through the project's mailer (`MAILERS`, or
`EMAIL_BACKEND` before Django 6.1 - see [Mail](installation.md#mail)).
Without one that can reach a server, they are written to standard
output by the console mailer, and so to the log.

To try the whole path once the settings are in:

```bash
python manage.py sendtestemail --admins
```

### `logging_config()`

| Argument | Default | |
| --- | --- | --- |
| `level` | `"INFO"` | The least a record needs to be kept: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `file` | `None` | A path: the same lines as standard output go there too; its folder is created |
| `max_bytes` | 10 MB | The file rotates beyond this size: `app.log` becomes `app.log.1`, and so on |
| `backups` | `5` | Rotated files kept; the oldest goes |
| `mail_errors` | `True` | Every record at `ERROR` or above to `ADMINS`, when `DEBUG` is off |
| `quiet` | `("django.security.DisallowedHost",)` | Loggers silenced - a refused host name is not worth a mail, and the internet sends plenty |

It returns an ordinary `LOGGING` dict: a project adds its own loggers
to `["loggers"]`, or a handler of its own, before assigning it.

One line per record, with the process that wrote it:

```text
2026-09-27 09:33:25,680 ERROR django.request [1015] Internal Server Error: /example/ticket/12/
Traceback (most recent call last):
  ...
```

Django's own default mails the errors of its `django` logger to
`ADMINS` by itself; `logging_config()` redefines that logger so its
errors reach the handlers above like every other logger's - one mail,
not two.

### `admins()`

`ADMINS` from addresses, in the shape the running Django reads: the
addresses themselves from Django 6.0, `(name, address)` pairs before.
Blank entries are dropped, so a list read from the environment is given
as it comes.

## The file

`generic.logs.SharedRotatingFileHandler` is Python's
`RotatingFileHandler` for several writers. The plain one assumes a
single process: when one process rotates the file, the others keep
writing to the renamed copy, rotate it again over the first backup, and
lines are lost - about one in ten, with four processes writing at once.
Here each record first checks that the file it holds is still the one at
the path, and the rotation happens under a lock, once: whoever gets the
lock second finds it done and follows. A web server, a Celery worker and
a scheduler - even in separate containers sharing a volume - write one
file together.

Without `fcntl` (Windows) the lock is skipped: one writer per file.

Rotation by size only, and the file is never deleted: a server that
already rotates its logs by date - `logrotate` - uses its own handler
(`logging.handlers.WatchedFileHandler`) in place of `file`.

## The mails

`generic.logs.ErrorMailHandler` is Django's `AdminEmailHandler` - the
traceback, the request, the settings with their secrets hidden - with
two differences:

- **Once per error per interval.** The same error - the same logger,
  level and message, or for an exception its type and the line it was
  raised at - is mailed at most once every `ERROR_MAIL_INTERVAL`
  seconds (`GENERIC`, 600 by default; `0` mails every one). The next
  mail after that says *[37 more since the last mail]* in its subject.
  The count lives in the default cache, shared by every process when it
  is Redis; when the cache fails, the mail goes anyway.
- **A mail that cannot leave is never raised** into the code that
  logged the error - a failing page would fail again, differently. It
  is reported the way logging reports its own failures, on standard
  error.

## The check

In production nobody reads a `DEBUG` page, and an error that is only
logged is read the day someone thinks of looking.
`python manage.py check --deploy` warns when `ADMINS` is empty
(`generic.W009`). A project whose logs are watched another way - a log
collector, an error tracker - silences it with
`SILENCED_SYSTEM_CHECKS`.

## What is not covered

- **Errors in the browser.** A script error on a page stays in that
  browser's console; the framework reports its own failed requests to
  the reader (`#datatable-error`, the form's messages), and the server
  logs the request's side.
- **An error tracker.** Sentry, Rollbar and the like plug into Django's
  logging on their own; `logging_config()` and they live side by side.

## The example

The example project reads it all from the environment
(`example_project/settings/base.py`):

| Variable | Default | |
| --- | --- | --- |
| `DJANGO_LOG_LEVEL` | `INFO` | The least a record needs |
| `DJANGO_LOG_FILE` | none | A path, to log to a file too |
| `DJANGO_ADMINS` | none | Comma-separated addresses mailed every unexpected error (not in development: `DEBUG` is on) |

The production stack writes `/app/logs/app.log` in the `app-logs`
volume, from every service:

```bash
docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env exec web tail -f logs/app.log
docker compose -f docker/docker-compose.prod.yml --env-file docker/prod.env logs -f web worker
```

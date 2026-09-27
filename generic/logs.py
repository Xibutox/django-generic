"""Logs a production can read: a file, and the unexpected errors by mail.

Django logs every unexpected error - a view that raised, a task that
failed, a mail that could not leave - with its traceback. Where those
records go is the project's ``LOGGING``; this module gives it what a
production needs, in one call::

    # settings.py
    from generic.logs import admins, logging_config

    ADMINS = admins(["ops@example.com"])     # who is told of an error
    LOGGING = logging_config(
        level="INFO",
        file="/var/log/mysite/web.log",       # optional: also to a file
    )

- every record at ``level`` or above goes to standard output, and to
  ``file`` when one is given - rotated by size, and safe to share
  between the processes of a server or a Celery worker;
- every error goes by mail to ``ADMINS`` when ``DEBUG`` is off - once
  per interval for the same error, so a failing loop sends one mail and
  a count, not a thousand mails.

``python manage.py check --deploy`` warns when ``ADMINS`` is empty
(``generic.W009``). See docs/logging.md.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import logging.handlers
import os
from copy import copy
from typing import Any, Iterable, Iterator

import django
from django.utils.log import AdminEmailHandler

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

#: A file rotates past this size, keeping ``BACKUPS`` older ones.
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5

#: Loggers too noisy for the log: every refused host name would be an
#: error line otherwise, and the internet sends plenty.
QUIET = ("django.security.DisallowedHost",)

#: One line per record; the process tells apart the writers of a shared
#: file.
FORMAT = "{asctime} {levelname} {name} [{process}] {message}"


def admins(addresses: Iterable[str]) -> list[Any]:
    """``ADMINS`` from e-mail addresses, in the shape this Django reads.

    Django 6.0 takes the addresses; before, ``(name, address)`` pairs.
    Blank entries are dropped, so ``env_list("DJANGO_ADMINS")`` can be
    given as it comes.
    """
    found = [address.strip() for address in addresses if address.strip()]

    if django.VERSION >= (6, 0):
        return found

    return [(address, address) for address in found]


def logging_config(
    *,
    level: str = "INFO",
    file: str | os.PathLike[str] | None = None,
    max_bytes: int = MAX_BYTES,
    backups: int = BACKUPS,
    mail_errors: bool = True,
    quiet: Iterable[str] = QUIET,
) -> dict[str, Any]:
    """A ``LOGGING`` dict: standard output, a file, the errors by mail.

    ``level`` is the least a record needs to be kept. ``file``, when
    given, receives the same lines as standard output, and rotates
    beyond ``max_bytes`` keeping ``backups`` older files; its folder is
    created. ``mail_errors`` sends every record at ``ERROR`` or above
    to ``ADMINS``, when ``DEBUG`` is off. ``quiet`` names loggers to
    silence.
    """
    handlers: dict[str, Any] = {
        "console": {"class": "logging.StreamHandler", "formatter": "line"},
    }

    if file:
        handlers["file"] = {
            "class": "generic.logs.SharedRotatingFileHandler",
            "filename": os.fspath(file),
            "maxBytes": max_bytes,
            "backupCount": backups,
            "formatter": "line",
        }

    if mail_errors:
        handlers["mail_errors"] = {
            "class": "generic.logs.ErrorMailHandler",
            "level": "ERROR",
            "filters": ["require_debug_false"],
        }

    loggers: dict[str, Any] = {
        # Django's own default mails the errors of its loggers to
        # ADMINS itself; defined here, they reach the handlers above
        # once, like every other logger's.
        "django": {"handlers": [], "level": level, "propagate": True},
    }

    for name in quiet:
        loggers[name] = {
            "handlers": [],
            "level": "CRITICAL",
            "propagate": False,
        }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"}
        },
        "formatters": {"line": {"format": FORMAT, "style": "{"}},
        "handlers": handlers,
        "root": {"handlers": list(handlers), "level": level},
        "loggers": loggers,
    }


class SharedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating log file that several processes write together.

    ``RotatingFileHandler`` assumes one writer. Daphne's process, a
    Celery worker's children and ``manage.py`` commands each hold the
    file open; when one rotates it, the others go on writing into the
    renamed file, and rotate it again over the first backup - lines
    lost. Here each record first checks that the file it writes to is
    still the one at the path, and the rotation happens under a lock,
    once: whoever gets the lock second finds it done and follows.

    Without ``fcntl`` (Windows) the lock is skipped: one writer only.
    """

    def __init__(
        self,
        filename: str | os.PathLike[str],
        mode: str = "a",
        maxBytes: int = MAX_BYTES,
        backupCount: int = BACKUPS,
        encoding: str | None = "utf-8",
        delay: bool = True,
        errors: str | None = None,
    ) -> None:
        folder = os.path.dirname(os.path.abspath(filename))
        os.makedirs(folder, exist_ok=True)
        super().__init__(
            filename,
            mode=mode,
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            errors=errors,
        )
        self.lock_path = f"{self.baseFilename}.lock"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.follow()
        except Exception:  # pragma: no cover - the disk said no
            self.handleError(record)
            return

        super().emit(record)

    def follow(self) -> None:
        """Reopen the path if another process rotated the file away."""
        if self.stream is None or self.is_current():
            return

        stream, self.stream = self.stream, None
        stream.close()

    def is_current(self) -> bool:
        if self.stream is None:
            return False

        try:
            on_disk = os.stat(self.baseFilename)
        except FileNotFoundError:
            return False

        held = os.fstat(self.stream.fileno())

        return (on_disk.st_dev, on_disk.st_ino) == (held.st_dev, held.st_ino)

    def doRollover(self) -> None:
        with self.locked():
            if self.stream is not None and not self.is_current():
                # Rotated by another process while this one waited.
                self.follow()
                return

            super().doRollover()

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        if fcntl is None:  # pragma: no cover - Windows
            yield
            return

        with open(self.lock_path, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


class ErrorMailHandler(AdminEmailHandler):
    """Django's mail to ``ADMINS``, once per error per interval.

    The same error - the same logger, level and message, or for an
    exception its type and the line it was raised at - is mailed at
    most once every ``interval`` seconds (``GENERIC["ERROR_MAIL_
    INTERVAL"]``, ten minutes by default; ``0`` mails every one). The
    next mail after a quiet spell says how many were held back. The
    count lives in the default cache, shared by every process when it
    is Redis; when the cache fails, the mail goes anyway.

    A mail that cannot leave is never raised into the code that logged
    the error: it is reported the way logging reports its own failures.
    """

    def __init__(self, *args: Any, interval: int | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.interval = interval

    def emit(self, record: logging.LogRecord) -> None:
        from django.conf import settings

        if not settings.ADMINS:
            return

        try:
            held_back = self.held_back(record)

            if held_back is None:
                return

            if held_back:
                record = copy(record)
                record.msg = (
                    f"[{held_back} more since the last mail] {record.msg}"
                )

            super().emit(record)
        except Exception:
            self.handleError(record)

    def get_interval(self) -> int:
        if self.interval is not None:
            return self.interval

        from generic.conf import generic_settings

        return int(generic_settings.ERROR_MAIL_INTERVAL or 0)

    def held_back(self, record: logging.LogRecord) -> int | None:
        """``None`` to hold this one back, else how many were before it."""
        interval = self.get_interval()

        if interval <= 0:
            return 0

        from django.core.cache import cache

        key = f"generic:error-mail:{signature(record)}"

        try:
            if cache.add(key, 1, interval):
                count = cache.get(f"{key}:held") or 0
                cache.delete(f"{key}:held")

                return int(count)

            try:
                cache.incr(f"{key}:held")
            except ValueError:
                cache.set(f"{key}:held", 1, 24 * 60 * 60)
        except Exception:
            # No cache, no counting: better every mail than none.
            return 0

        return None


def signature(record: logging.LogRecord) -> str:
    """What makes two records the same error, as a short hash."""
    parts = [record.name, str(record.levelno)]

    if record.exc_info and record.exc_info[0] is not None:
        kind, _, trace = record.exc_info
        parts.append(f"{kind.__module__}.{kind.__qualname__}")

        while trace is not None and trace.tb_next is not None:
            trace = trace.tb_next

        if trace is not None:
            code = trace.tb_frame.f_code
            parts.append(f"{code.co_filename}:{trace.tb_lineno}")
    else:
        parts.append(record.getMessage()[:200])

    return hashlib.sha1(
        "\n".join(parts).encode(), usedforsecurity=False
    ).hexdigest()


__all__ = (
    "ErrorMailHandler",
    "SharedRotatingFileHandler",
    "admins",
    "logging_config",
)

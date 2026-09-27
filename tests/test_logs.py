"""Logs a production can read: ``generic.logs``.

A file several processes share and rotate without losing a line, the
unexpected errors mailed to ``ADMINS`` once per interval, and the
deployment check that says when nobody would be told.
"""

from __future__ import annotations

import logging
import multiprocessing
import subprocess
import sys
import textwrap
from pathlib import Path

import django
import pytest
from django.core import mail
from django.core.cache import cache
from django.core.checks import run_checks
from django.test import override_settings

from generic import logs
from generic.logs import (
    ErrorMailHandler,
    SharedRotatingFileHandler,
    admins,
    logging_config,
)

ROOT = Path(__file__).resolve().parent.parent

ADMINS = admins(["ops@example.com"])


def record(message="Boom", *, name="tests.logs", error=None):
    """A log record as ``logger.exception`` makes one."""
    exc_info = None

    if error is not None:
        try:
            raise error
        except Exception:
            exc_info = sys.exc_info()

    return logging.LogRecord(
        name, logging.ERROR, __file__, 1, message, (), exc_info
    )


def lines_in(folder: Path, stem: str) -> list[str]:
    return [
        line
        for path in folder.glob(f"{stem}*")
        if not path.name.endswith(".lock")
        for line in path.read_text().splitlines()
    ]


class TestAdmins:
    def test_the_shape_this_django_reads(self):
        found = admins(["ops@example.com", " ", "", " dev@example.com "])

        if django.VERSION >= (6, 0):
            assert found == ["ops@example.com", "dev@example.com"]
        else:
            assert found == [
                ("ops@example.com", "ops@example.com"),
                ("dev@example.com", "dev@example.com"),
            ]

    def test_nobody(self):
        assert admins([]) == []


class TestLoggingConfig:
    def test_standard_output_and_the_errors_by_mail(self):
        config = logging_config()

        assert set(config["handlers"]) == {"console", "mail_errors"}
        assert config["root"]["handlers"] == ["console", "mail_errors"]
        assert config["handlers"]["mail_errors"]["level"] == "ERROR"
        assert config["handlers"]["mail_errors"]["filters"] == [
            "require_debug_false"
        ]

    def test_a_file_when_given(self, tmp_path):
        config = logging_config(
            file=tmp_path / "app.log", max_bytes=100, backups=2
        )

        handler = config["handlers"]["file"]
        assert handler["filename"] == str(tmp_path / "app.log")
        assert (handler["maxBytes"], handler["backupCount"]) == (100, 2)
        assert "file" in config["root"]["handlers"]

    def test_without_the_mail(self):
        assert (
            "mail_errors" not in logging_config(mail_errors=False)["handlers"]
        )

    def test_django_errors_reach_the_root_once(self):
        """Django's own default mails its loggers' errors itself;
        redefined, ``django`` has no handler of its own left."""
        loggers = logging_config(level="WARNING")["loggers"]

        assert loggers["django"] == {
            "handlers": [],
            "level": "WARNING",
            "propagate": True,
        }

    def test_the_refused_host_names_are_quiet(self):
        loggers = logging_config()["loggers"]

        assert loggers["django.security.DisallowedHost"]["level"] == (
            "CRITICAL"
        )


@pytest.mark.django_db
class TestErrorMail:
    @pytest.fixture(autouse=True)
    def admins(self, settings):
        settings.ADMINS = ADMINS
        cache.clear()
        yield
        cache.clear()

    def test_an_error_is_mailed(self):
        ErrorMailHandler(interval=600).handle(record("Boom", error=KeyError()))

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["ops@example.com"]
        assert "Boom" in mail.outbox[0].subject
        assert "KeyError" in mail.outbox[0].body

    def test_the_same_error_is_mailed_once_per_interval(self):
        handler = ErrorMailHandler(interval=600)

        for _ in range(5):
            handler.handle(record("Boom", error=KeyError()))

        assert len(mail.outbox) == 1

    def test_the_next_mail_says_how_many_were_held_back(self):
        handler = ErrorMailHandler(interval=600)

        for _ in range(3):
            handler.handle(record("Boom", error=KeyError()))

        # The interval is over.
        key = f"generic:error-mail:{logs.signature(record(error=KeyError()))}"
        cache.delete(key)
        handler.handle(record("Boom", error=KeyError()))

        assert len(mail.outbox) == 2
        assert "[2 more since the last mail] Boom" in mail.outbox[1].subject

    def test_another_error_is_mailed_on_its_own(self):
        handler = ErrorMailHandler(interval=600)

        handler.handle(record("Boom", error=KeyError()))
        handler.handle(record("Boom", error=ValueError()))
        handler.handle(record("Something else"))

        assert len(mail.outbox) == 3

    def test_zero_mails_every_one(self):
        handler = ErrorMailHandler(interval=0)

        for _ in range(3):
            handler.handle(record("Boom"))

        assert len(mail.outbox) == 3

    def test_the_interval_is_a_setting(self, settings):
        settings.GENERIC = {"ERROR_MAIL_INTERVAL": 0}
        handler = ErrorMailHandler()

        handler.handle(record("Boom"))
        handler.handle(record("Boom"))

        assert len(mail.outbox) == 2

    def test_without_admins_nothing(self, settings):
        settings.ADMINS = []

        ErrorMailHandler(interval=0).handle(record("Boom"))

        assert mail.outbox == []

    def test_a_cache_that_fails_still_mails(self, monkeypatch):
        def broken(*args, **kwargs):
            raise ConnectionError("Redis is gone")

        monkeypatch.setattr(cache, "add", broken)
        handler = ErrorMailHandler(interval=600)

        handler.handle(record("Boom"))
        handler.handle(record("Boom"))

        assert len(mail.outbox) == 2

    def test_a_mail_that_cannot_leave_is_not_raised(self, monkeypatch):
        """Raised, it would reach the code that logged the error - a
        failing page would fail again, differently."""
        failures = []

        def refuse(*args, **kwargs):
            raise OSError("The mail server said no")

        monkeypatch.setattr(ErrorMailHandler, "send_mail", refuse)
        handler = ErrorMailHandler(interval=0)
        monkeypatch.setattr(handler, "handleError", failures.append)

        handler.handle(record("Boom"))

        assert len(failures) == 1


class TestSharedFile:
    def test_it_writes_and_makes_its_folder(self, tmp_path):
        path = tmp_path / "logs" / "app.log"
        handler = SharedRotatingFileHandler(path)

        handler.handle(record("Hello"))
        handler.close()

        assert path.read_text() == "Hello\n"

    def test_it_rotates(self, tmp_path):
        path = tmp_path / "app.log"
        handler = SharedRotatingFileHandler(path, maxBytes=50, backupCount=3)

        for number in range(20):
            handler.handle(record(f"line {number:02d}"))
        handler.close()

        # Three backups kept, the oldest lines dropped - and only them.
        assert (tmp_path / "app.log.3").exists()
        assert not (tmp_path / "app.log.4").exists()
        kept = sorted(lines_in(tmp_path, "app.log"))
        assert (
            kept
            == [f"line {number:02d}" for number in range(20)][-len(kept) :]
        )

    def test_two_writers_lose_nothing(self, tmp_path):
        """Two handlers on one path are two processes: when one rotates,
        the other writes to the new file rather than the renamed one."""
        path = tmp_path / "app.log"
        first = SharedRotatingFileHandler(path, maxBytes=200, backupCount=99)
        second = SharedRotatingFileHandler(path, maxBytes=200, backupCount=99)

        for number in range(100):
            (first if number % 2 else second).handle(record(f"line {number}"))
        first.close()
        second.close()

        assert sorted(lines_in(tmp_path, "app.log")) == sorted(
            f"line {number}" for number in range(100)
        )

    @pytest.mark.skipif(logs.fcntl is None, reason="no fcntl: one writer")
    def test_processes_lose_nothing(self, tmp_path):
        path = tmp_path / "app.log"
        context = multiprocessing.get_context("fork")
        writers = [
            context.Process(target=write_lines, args=(path, writer, 300))
            for writer in range(4)
        ]

        for process in writers:
            process.start()
        for process in writers:
            process.join(60)

        assert all(process.exitcode == 0 for process in writers)
        written = lines_in(tmp_path, "app.log")
        assert len(written) == 1200
        assert len(set(written)) == 1200
        assert len(list(tmp_path.glob("app.log.*"))) > 2


def write_lines(path: Path, writer: int, count: int) -> None:
    handler = SharedRotatingFileHandler(path, maxBytes=2000, backupCount=999)

    for number in range(count):
        handler.handle(record(f"writer {writer} line {number}"))

    handler.close()


class TestTheCheck:
    def deploy(self) -> list[str]:
        return [
            message.id
            for message in run_checks(include_deployment_checks=True)
            if message.id == "generic.W009"
        ]

    def test_nobody_to_tell(self, settings):
        settings.ADMINS = []

        assert self.deploy() == ["generic.W009"]

    def test_somebody_to_tell(self, settings):
        settings.ADMINS = ADMINS

        assert self.deploy() == []

    @override_settings(ADMINS=[])
    def test_not_outside_deployment(self):
        assert "generic.W009" not in [m.id for m in run_checks()]


def test_a_failing_page_is_logged_to_the_file_and_mailed_once(tmp_path):
    """The whole path, configured as a project configures it: a view
    that raises, and what reaches the file and the admins' mailbox.

    In a process of its own: the suite runs with LOGGING_CONFIG = None,
    and configuring logging here would change it for every other test.
    """
    script = textwrap.dedent(f"""
        import django
        from django.conf import settings
        from django.urls import path

        from generic.logs import admins, logging_config

        def boom(request):
            raise RuntimeError("the page broke")

        urlpatterns = [path("boom/", boom)]

        settings.configure(
            DEBUG=False,
            ALLOWED_HOSTS=["testserver"],
            ROOT_URLCONF=__name__,
            SECRET_KEY="x",
            INSTALLED_APPS=["django.contrib.contenttypes",
                            "django.contrib.auth"],
            DATABASES={{"default": {{"ENGINE": "django.db.backends.sqlite3",
                                     "NAME": ":memory:"}}}},
            CACHES={{"default": {{
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}}},
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            ADMINS=admins(["ops@example.com"]),
            LOGGING=logging_config(file={str(tmp_path / "app.log")!r}),
        )
        django.setup()

        from django.core import mail
        from django.test import Client
        from django.test.utils import setup_test_environment

        setup_test_environment()
        client = Client(raise_request_exception=False)
        for _ in range(3):
            assert client.get("/boom/").status_code == 500
        print(len(mail.outbox))
        print(mail.outbox[0].subject)
        """)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    count, subject = result.stdout.splitlines()
    # Three failures, one mail: not Django's own beside it, nor three.
    assert count == "1"
    assert "Internal Server Error: /boom/" in subject
    written = (tmp_path / "app.log").read_text()
    assert written.count("ERROR django.request") == 3
    assert "RuntimeError: the page broke" in written

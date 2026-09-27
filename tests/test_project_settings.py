"""The example project's two modes, development and production.

What each turns on, and what production refuses to start without. The
project is what a new one is copied from, so its settings are a
deliverable like the rest: a production module that falls back to a
development value would be copied along with it.
"""

from __future__ import annotations

import importlib.util
import os
import runpy
import subprocess
import sys
from pathlib import Path

import django
import pytest
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

ROOT = Path(__file__).resolve().parent.parent

#: Every variable the settings read: cleared before each load, so the
#: environment the suite runs in (CI sets DATABASE_URL) decides nothing.
READ = (
    "DJANGO_SECRET_KEY",
    "DJANGO_ALLOWED_HOSTS",
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "DJANGO_SITE_URL",
    "DJANGO_HTTPS",
    "DJANGO_HSTS_SECONDS",
    "DJANGO_HSTS_SUBDOMAINS",
    "DJANGO_HSTS_PRELOAD",
    "DJANGO_STATIC_ROOT",
    "DATABASE_URL",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS",
    "DEBUG_TOOLBAR",
    "DJANGO_ADMINS",
    "DJANGO_LOG_LEVEL",
    "DJANGO_LOG_FILE",
)

#: The settings Django 6.1 deprecates for MAILERS, and refuses to start
#: with beside it.
EMAIL_SETTINGS = {
    "EMAIL_BACKEND",
    "EMAIL_FILE_PATH",
    "EMAIL_HOST",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_HOST_USER",
    "EMAIL_PORT",
    "EMAIL_SSL_CERTFILE",
    "EMAIL_SSL_KEYFILE",
    "EMAIL_TIMEOUT",
    "EMAIL_USE_SSL",
    "EMAIL_USE_TLS",
}

SMTP = "django.core.mail.backends.smtp.EmailBackend"
CONSOLE = "django.core.mail.backends.console.EmailBackend"

PRODUCTION = {
    "DJANGO_SECRET_KEY": "test-" + "k3y" * 20,
    "DJANGO_ALLOWED_HOSTS": "desk.example.com, www.desk.example.com",
    "DATABASE_URL": "postgres://desk:s%40fe@db:5432/desk",
    "REDIS_URL": "redis://redis:6379/0",
    "DJANGO_ADMINS": "ops@example.com",
}


@pytest.fixture
def load(monkeypatch):
    """Run one settings module afresh, under the given environment."""

    def run(mode: str, **environ: str) -> dict:
        for name in READ:
            monkeypatch.delenv(name, raising=False)

        for name, value in environ.items():
            monkeypatch.setenv(name, value)

        # base.py reads the environment too: imported again, not reused.
        monkeypatch.delitem(
            sys.modules, "example_project.settings.base", raising=False
        )

        return runpy.run_module(f"example_project.settings.{mode}")

    return run


def mail_backend(settings: dict) -> str:
    """What the settings send mail through, on the Django running."""
    if "MAILERS" in settings:
        return settings["MAILERS"]["default"]["BACKEND"]

    return settings["EMAIL_BACKEND"]


def mail_only(settings: dict) -> dict:
    """The mail settings alone, to hand to override_settings."""
    names = {"MAILERS"} | EMAIL_SETTINGS

    return {name: settings[name] for name in names if name in settings}


class TestProduction:
    @pytest.mark.parametrize(
        "missing",
        [
            "DJANGO_SECRET_KEY",
            "DJANGO_ALLOWED_HOSTS",
            "DATABASE_URL",
            "REDIS_URL",
        ],
    )
    def test_it_refuses_to_start_without(self, load, missing):
        """A server that falls back to a development value runs, and is
        not safe: better not to start, and say what is missing."""
        environ = {k: v for k, v in PRODUCTION.items() if k != missing}

        with pytest.raises(ImproperlyConfigured, match=missing):
            load("prod", **environ)

    def test_it_reads_the_rest_from_the_environment(self, load):
        settings = load("prod", **PRODUCTION)

        assert settings["DEBUG"] is False
        assert settings["ALLOWED_HOSTS"] == [
            "desk.example.com",
            "www.desk.example.com",
        ]
        database = settings["DATABASES"]["default"]
        assert database["ENGINE"] == "django.db.backends.postgresql"
        # Percent-encoded in the URL, as it has to be.
        assert database["PASSWORD"] == "s@fe"
        assert "RedisChannelLayer" in (
            settings["CHANNEL_LAYERS"]["default"]["BACKEND"]
        )
        assert "RedisCache" in settings["CACHES"]["default"]["BACKEND"]
        assert settings["CELERY_TASK_ALWAYS_EAGER"] is False
        assert settings["CELERY_BROKER_URL"] == PRODUCTION["REDIS_URL"]

    def test_a_quiet_socket_is_not_timed_out(self, load):
        """channels-redis waits up to ``brpop_timeout`` on Redis for a
        socket's next event. A read that gives up first - redis-py 8's
        default does, after 5 seconds - closes every quiet socket."""
        layer = pytest.importorskip("channels_redis.core").RedisChannelLayer
        settings = load("prod", **PRODUCTION)

        (host,) = settings["CHANNEL_LAYERS"]["default"]["CONFIG"]["hosts"]

        assert host["address"] == PRODUCTION["REDIS_URL"]
        assert host["socket_timeout"] > layer.brpop_timeout

    def test_https_is_assumed(self, load):
        settings = load("prod", **PRODUCTION)

        assert settings["SESSION_COOKIE_SECURE"] is True
        assert settings["CSRF_COOKIE_SECURE"] is True
        assert settings["SECURE_SSL_REDIRECT"] is True
        assert settings["SECURE_HSTS_SECONDS"] == 3600
        assert settings["SECURE_PROXY_SSL_HEADER"] == (
            "HTTP_X_FORWARDED_PROTO",
            "https",
        )

    def test_plain_http_is_asked_for(self, load):
        """To try the stack on localhost: secure cookies would never
        come back over HTTP, and signing in would silently fail."""
        settings = load("prod", DJANGO_HTTPS="0", **PRODUCTION)

        assert settings["SESSION_COOKIE_SECURE"] is False
        assert settings["SECURE_SSL_REDIRECT"] is False
        assert settings["SECURE_HSTS_SECONDS"] == 0

    def test_nothing_of_development_comes_along(self, load):
        settings = load("prod", **PRODUCTION)

        assert "debug_toolbar" not in settings["INSTALLED_APPS"]
        assert not any(
            "debug_toolbar" in name for name in settings["MIDDLEWARE"]
        )
        assert "ManifestStaticFilesStorage" in (
            settings["STORAGES"]["staticfiles"]["BACKEND"]
        )

    def test_mail_goes_to_the_log_without_a_server(self, load):
        settings = load("prod", **PRODUCTION)

        assert mail_backend(settings) == CONSOLE
        # Decided, so the deployment check does not call it an error.
        assert "mail.E001" in settings["SILENCED_SYSTEM_CHECKS"]

    def test_mail_goes_out_with_one(self, load):
        settings = load(
            "prod",
            EMAIL_HOST="smtp.example.com",
            DJANGO_SITE_URL="https://desk.example.com",
            **PRODUCTION,
        )

        assert mail_backend(settings) == SMTP
        assert "mail.E001" not in settings["SILENCED_SYSTEM_CHECKS"]
        # The links in those mails are absolute.
        assert settings["GENERIC"]["SITE_URL"] == "https://desk.example.com"

    def test_django_builds_the_mailer_they_describe(self, load):
        """The variables reach the SMTP backend, under whichever
        settings the Django running reads them from."""
        settings = load(
            "prod",
            EMAIL_HOST="smtp.example.com",
            EMAIL_HOST_USER="desk",
            EMAIL_HOST_PASSWORD="s3cret",
            **PRODUCTION,
        )

        with override_settings(**mail_only(settings)):
            if hasattr(mail, "mailers"):
                backend = mail.mailers.default
            else:
                backend = mail.get_connection()

        assert type(backend).__module__.endswith("smtp")
        assert (backend.host, backend.port) == ("smtp.example.com", 587)
        assert (backend.username, backend.password) == ("desk", "s3cret")
        assert backend.use_tls is True


class TestMail:
    """MAILERS from Django 6.1, the EMAIL_* settings before: 6.1 refuses
    the two together, 5.2 - the oldest supported - knows only the
    second."""

    @pytest.mark.parametrize(
        "mode,environ",
        [
            ("dev", {}),
            ("prod", PRODUCTION),
            ("prod", {**PRODUCTION, "EMAIL_HOST": "smtp.example.com"}),
        ],
        ids=["development", "production", "production-smtp"],
    )
    def test_each_mode_speaks_the_running_django_s(self, load, mode, environ):
        settings = load(mode, **environ)

        if django.VERSION >= (6, 1):
            assert "default" in settings["MAILERS"]
            assert not EMAIL_SETTINGS & settings.keys()
        else:
            assert "MAILERS" not in settings
            assert "EMAIL_BACKEND" in settings

    def test_mailers_from_django_6_1(self, monkeypatch):
        from example_project.settings.base import mail_settings

        monkeypatch.setattr(django, "VERSION", (6, 1, 0, "final", 0))

        assert mail_settings(CONSOLE) == {
            "MAILERS": {"default": {"BACKEND": CONSOLE}}
        }
        assert mail_settings(SMTP, host="smtp.example.com", port=587) == {
            "MAILERS": {
                "default": {
                    "BACKEND": SMTP,
                    "OPTIONS": {"host": "smtp.example.com", "port": 587},
                }
            }
        }

    def test_the_email_settings_before(self, monkeypatch):
        from example_project.settings.base import mail_settings

        monkeypatch.setattr(django, "VERSION", (5, 2, 0, "final", 0))

        assert mail_settings(
            SMTP,
            host="smtp.example.com",
            port=587,
            username="desk",
            password="s3cret",
            use_tls=True,
        ) == {
            "EMAIL_BACKEND": SMTP,
            "EMAIL_HOST": "smtp.example.com",
            "EMAIL_PORT": 587,
            "EMAIL_HOST_USER": "desk",
            "EMAIL_HOST_PASSWORD": "s3cret",
            "EMAIL_USE_TLS": True,
        }

    def test_an_option_no_email_setting_holds_is_refused(self, monkeypatch):
        """A third-party backend's own option, say: before 6.1 it has
        no EMAIL_* setting to go to, and dropping it would be silent."""
        from example_project.settings.base import mail_settings

        monkeypatch.setattr(django, "VERSION", (5, 2, 0, "final", 0))

        with pytest.raises(ImproperlyConfigured, match="region"):
            mail_settings(SMTP, region="eu")


class TestDevelopment:
    def test_it_needs_nothing_to_start(self, load):
        settings = load("dev")

        assert settings["DEBUG"] is True
        assert settings["DATABASES"]["default"]["NAME"] == (
            ROOT / "example.sqlite3"
        )
        assert "InMemoryChannelLayer" in (
            settings["CHANNEL_LAYERS"]["default"]["BACKEND"]
        )
        assert settings["CELERY_TASK_ALWAYS_EAGER"] is True

    def test_it_takes_postgres_and_redis_when_given(self, load):
        """What the development Docker stack does."""
        settings = load(
            "dev",
            DATABASE_URL="postgres://generic:generic@db:5432/generic",
            REDIS_URL="redis://redis:6379/0",
        )

        assert settings["DATABASES"]["default"]["HOST"] == "db"
        assert "RedisChannelLayer" in (
            settings["CHANNEL_LAYERS"]["default"]["BACKEND"]
        )

    def test_the_toolbar_stays_out_of_a_test_run(self, load):
        assert load("dev")["DEBUG_TOOLBAR"] is False

    def test_what_it_adds_never_reaches_production(self, load, monkeypatch):
        """The toolbar is added to new lists, not to base's: the two
        modules share base, and a process may read both."""
        pytest.importorskip("debug_toolbar")
        monkeypatch.delenv("PYTEST_VERSION", raising=False)
        monkeypatch.setattr(sys, "argv", ["manage.py", "runserver"])

        development = load("dev")
        production = load("prod", **PRODUCTION)

        assert "debug_toolbar" in development["INSTALLED_APPS"]
        assert "debug_toolbar" not in production["INSTALLED_APPS"]
        assert not any(
            "debug_toolbar" in name for name in production["MIDDLEWARE"]
        )


class TestLogs:
    @pytest.mark.parametrize("mode", ["dev", "prod"])
    def test_standard_output_alone_by_default(self, load, mode):
        settings = load(mode, **PRODUCTION)

        assert set(settings["LOGGING"]["handlers"]) == {
            "console",
            "mail_errors",
        }
        assert settings["LOGGING"]["root"]["level"] == "INFO"

    def test_a_file_and_a_level_when_given(self, load, tmp_path):
        settings = load(
            "prod",
            **PRODUCTION,
            DJANGO_LOG_FILE=str(tmp_path / "app.log"),
            DJANGO_LOG_LEVEL="WARNING",
        )

        logging = settings["LOGGING"]
        assert logging["handlers"]["file"]["filename"] == str(
            tmp_path / "app.log"
        )
        assert logging["root"]["level"] == "WARNING"

    def test_the_errors_go_to_the_admins(self, load):
        from generic.logs import admins

        settings = load(
            "prod", **{**PRODUCTION, "DJANGO_ADMINS": "a@x.io, b@x.io"}
        )

        assert settings["ADMINS"] == admins(["a@x.io", "b@x.io"])
        assert settings["SERVER_EMAIL"] == settings["DEFAULT_FROM_EMAIL"]

    def test_the_worker_logs_like_the_rest(self, load):
        """Left to itself, Celery replaces the handlers of the root
        logger with its own: the worker's errors would reach neither
        the file nor the mail."""
        assert (
            load("prod", **PRODUCTION)["CELERY_WORKER_HIJACK_ROOT_LOGGER"]
            is False
        )


class TestDatabaseUrl:
    def parse(self, url):
        from example_project.settings.base import database_from_url

        return database_from_url(url)

    def test_a_relative_sqlite_path_is_the_repository_s(self):
        assert self.parse("sqlite:///desk.sqlite3")["NAME"] == (
            ROOT / "desk.sqlite3"
        )

    def test_an_absolute_one_stays_absolute(self):
        name = self.parse("sqlite:////var/lib/desk.sqlite3")["NAME"]

        assert name.as_posix().endswith("/var/lib/desk.sqlite3")
        assert name.is_absolute() or name.as_posix().startswith("/")

    def test_an_unknown_database_is_refused(self):
        with pytest.raises(ImproperlyConfigured, match="mysql"):
            self.parse("mysql://desk@db/desk")


class TestEntryPoints:
    @pytest.mark.parametrize(
        "path,mode",
        [
            ("manage.py", "dev"),
            ("example_project/celery.py", "dev"),
            # What a server imports: never DEBUG by accident.
            ("example_project/asgi.py", "prod"),
            ("example_project/wsgi.py", "prod"),
        ],
    )
    def test_each_defaults_to_its_mode(self, path, mode):
        source = (ROOT / path).read_text(encoding="utf-8")

        assert f'"example_project.settings.{mode}"' in source

    def test_the_package_alone_is_refused(self, monkeypatch):
        """What an environment still naming the single settings.py of
        earlier versions points at: Django would run on its defaults."""
        import example_project.settings as package

        monkeypatch.setenv("DJANGO_SETTINGS_MODULE", package.__name__)

        with pytest.raises(ImproperlyConfigured, match=".dev or"):
            importlib.reload(package)


def manage(*args: str, **environ: str) -> subprocess.CompletedProcess:
    """``manage.py`` in a process of its own, with production settings."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in READ and key != "DJANGO_SETTINGS_MODULE"
    }
    env.update(DJANGO_SETTINGS_MODULE="example_project.settings.prod")
    env.update(environ)

    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


class TestProductionForReal:
    """The two commands the production image depends on, run."""

    def environ(self, tmp_path) -> dict:
        return {
            **PRODUCTION,
            "DATABASE_URL": f"sqlite:///{(tmp_path / 'db').as_posix()}",
            "DJANGO_STATIC_ROOT": str(tmp_path / "static"),
        }

    @pytest.mark.parametrize(
        "mail",
        [{}, {"EMAIL_HOST": "smtp.example.com"}],
        ids=["mail-to-the-log", "mail-by-smtp"],
    )
    def test_check_deploy_has_nothing_to_say(self, tmp_path, mail):
        result = manage(
            "check",
            "--deploy",
            "--fail-level",
            "WARNING",
            # Django's deprecations are pending ones, hidden by default:
            # shown, the mail settings must not be among them.
            PYTHONWARNINGS="always::PendingDeprecationWarning",
            **self.environ(tmp_path),
            **mail,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "MAILERS" not in result.stderr, result.stderr

    def test_check_deploy_says_when_nobody_hears_of_errors(self, tmp_path):
        environ = self.environ(tmp_path)
        del environ["DJANGO_ADMINS"]

        result = manage(
            "check", "--deploy", "--fail-level", "WARNING", **environ
        )

        assert result.returncode == 1
        assert "generic.W009" in result.stderr

    def test_the_static_files_collect_with_hashed_names(self, tmp_path):
        """What the image build runs. A vendored file mentioning a
        source map it does not ship fails it, and the build with it."""
        result = manage(
            "collectstatic",
            "--noinput",
            **self.environ(tmp_path),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert (tmp_path / "static" / "staticfiles.json").exists()
        assert list((tmp_path / "static").rglob("base.*.css"))


@pytest.mark.skipif(
    importlib.util.find_spec("celery") is None,
    reason="Celery (the tasks extra) is not installed in this environment",
)
def test_a_task_started_by_the_site_goes_to_the_worker(tmp_path):
    """Every process of the project loads its Celery application, not
    only the worker: a task started from a page is handed to the broker
    the settings name instead of running in the request. Asked in a
    process of its own - the import makes that application Celery's
    current one, and the suite's must stay its own."""
    result = manage(
        "shell",
        "--no-imports",
        "-c",
        "from generic.tasks import get_task\n"
        "from generic.tasks.runner import can_queue\n"
        "print(can_queue(get_task('example.overdue_digest')))",
        **{
            **PRODUCTION,
            "DATABASE_URL": f"sqlite:///{(tmp_path / 'db').as_posix()}",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.split()[-1] == "True"

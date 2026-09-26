"""The example project's two modes, development and production.

What each turns on, and what production refuses to start without. The
project is what a new one is copied from, so its settings are a
deliverable like the rest: a production module that falls back to a
development value would be copied along with it.
"""

from __future__ import annotations

import importlib
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

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
    "DEBUG_TOOLBAR",
)

PRODUCTION = {
    "DJANGO_SECRET_KEY": "test-" + "k3y" * 20,
    "DJANGO_ALLOWED_HOSTS": "desk.example.com, www.desk.example.com",
    "DATABASE_URL": "postgres://desk:s%40fe@db:5432/desk",
    "REDIS_URL": "redis://redis:6379/0",
}


@pytest.fixture
def load(monkeypatch):
    """Run one settings module afresh, under the given environment."""

    def run(mode: str, **environ: str) -> dict:
        for name in READ:
            monkeypatch.delenv(name, raising=False)

        for name, value in environ.items():
            monkeypatch.setenv(name, value)

        return runpy.run_module(f"example_project.settings.{mode}")

    return run


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

        assert settings["EMAIL_BACKEND"].endswith("console.EmailBackend")

    def test_mail_goes_out_with_one(self, load):
        settings = load(
            "prod",
            EMAIL_HOST="smtp.example.com",
            DJANGO_SITE_URL="https://desk.example.com",
            **PRODUCTION,
        )

        assert settings["EMAIL_BACKEND"].endswith("smtp.EmailBackend")
        assert settings["EMAIL_PORT"] == 587
        # The links in those mails are absolute.
        assert settings["GENERIC"]["SITE_URL"] == "https://desk.example.com"


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

    def test_check_deploy_has_nothing_to_say(self, tmp_path):
        result = manage(
            "check",
            "--deploy",
            "--fail-level",
            "WARNING",
            **self.environ(tmp_path),
        )

        assert result.returncode == 0, result.stdout + result.stderr

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

"""scripts/new_project.py: a new project, its secrets, its hardened stack.

What the script writes is checked the way a project would use it: the
files rendered with nothing left to fill in, the secrets random and
private, the production stack locked down container by container, and
the project's own settings and smoke test run in a subprocess. CI's
``new-project`` job starts the generated stack and backs it up,
restores it and tests the restore (.github/workflows/ci.yml).
"""

from __future__ import annotations

import importlib.util
import os
import py_compile
import re
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPOSITORY = Path(__file__).resolve().parent.parent
SCRIPT = REPOSITORY / "scripts" / "new_project.py"

spec = importlib.util.spec_from_file_location("new_project", SCRIPT)
new_project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(new_project)


def generate(target: Path, *options: str) -> Path:
    new_project.main(
        [
            str(target),
            "--name",
            "desk",
            "--title",
            "Support desk",
            "--no-wheel",
            "--no-input",
            *options,
        ]
    )
    return target


def env_file(path: Path) -> dict:
    values = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    return generate(
        tmp_path_factory.mktemp("new") / "desk",
        "--domain",
        "desk.example.com",
        "--admins",
        "ops@example.com",
    )


@pytest.fixture(scope="module")
def stack(project) -> dict:
    return yaml.safe_load(
        (project / "docker" / "compose.prod.yml").read_text()
    )


class TestTheProject:
    def test_every_file_is_filled_in(self, project):
        for path in project.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                text = path.read_text("utf-8")
                assert "{{ " not in text, path
                assert not path.name.endswith(".tpl"), path

    def test_the_names_are_the_ones_asked_for(self, project):
        assert (project / "desk" / "settings" / "prod.py").is_file()
        assert (project / "core" / "resources.py").is_file()
        assert (project / ".gitignore").is_file()
        assert (project / ".dockerignore").is_file()
        assert "desk.settings.dev" in (project / "manage.py").read_text()
        assert "Support desk" in (project / "README.md").read_text()

    def test_the_python_compiles(self, project):
        for path in project.rglob("*.py"):
            py_compile.compile(str(path), doraise=True)

    def test_the_wheel_is_named_by_its_path(self, project):
        version = new_project.framework_version()
        requirements = (project / "requirements.txt").read_text()

        assert (
            f"./vendor/django_generic-{version}-py3-none-any.whl"
            in requirements
        )
        assert "-e ." in requirements

    def test_an_existing_folder_is_left_alone(self, project):
        with pytest.raises(SystemExit, match="not empty"):
            generate(project)

    @pytest.mark.parametrize(
        "name", ["Desk", "1desk", "generic", "django", "class", "my-desk"]
    )
    def test_names_python_could_not_import(self, name):
        with pytest.raises(ValueError):
            new_project.check_name(name, "The project's name")

    def test_a_value_left_out_is_refused(self):
        with pytest.raises(RuntimeError, match="title"):
            new_project.render("{{ title }}", {})


class TestTheSecrets:
    def test_written_private(self, project):
        if os.name == "nt":  # pragma: no cover
            pytest.skip("POSIX permissions")

        for name in ("prod.env", "dev.env"):
            mode = (project / "docker" / name).stat().st_mode & 0o777
            assert mode == 0o600, name

    def test_random_long_and_never_the_same(self, project, tmp_path):
        prod = env_file(project / "docker" / "prod.env")
        dev = env_file(project / "docker" / "dev.env")
        other = env_file(generate(tmp_path / "other") / "docker" / "prod.env")
        names = (
            "DJANGO_SECRET_KEY",
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "BACKUP_PASSPHRASE",
        )

        for name in names:
            assert len(prod[name]) >= 43, name
            # Safe in a URL (DATABASE_URL, REDIS_URL) and an env file.
            assert re.fullmatch(r"[A-Za-z0-9_-]+", prod[name]), name
            assert prod[name] != other[name], name
        for name in names[:3]:
            assert prod[name] != dev[name], name
        assert len(set(prod[name] for name in names)) == len(names)

    def test_the_domain_is_served_over_https(self, project):
        prod = env_file(project / "docker" / "prod.env")

        assert prod["DJANGO_ALLOWED_HOSTS"] == "desk.example.com"
        assert prod["SITE_ADDRESS"] == "desk.example.com"
        assert prod["DJANGO_HTTPS"] == "1"
        assert prod["DJANGO_SITE_URL"] == "https://desk.example.com"
        assert prod["DJANGO_ADMINS"] == "ops@example.com"

    def test_localhost_is_plain_http(self, tmp_path):
        prod = env_file(generate(tmp_path / "local") / "docker" / "prod.env")

        assert prod["SITE_ADDRESS"] == ":80"
        assert prod["DJANGO_HTTPS"] == "0"

    def test_never_committed_never_in_an_image(self, project):
        ignored = (project / ".gitignore").read_text()
        kept_out = (project / ".dockerignore").read_text()

        for line in ("docker/prod.env", "docker/dev.env", "backups/"):
            assert line in ignored
        assert "docker/*.env" in kept_out
        assert "backups" in kept_out

    def test_written_again_only_when_asked(self, project):
        ops = [sys.executable, str(project / "ops.py"), "env"]
        before = env_file(project / "docker" / "prod.env")

        refused = subprocess.run(
            [*ops, "--domain", "x.example.com", "--admins", ""],
            capture_output=True,
            text=True,
        )

        assert refused.returncode != 0
        assert "--force" in refused.stderr
        assert env_file(project / "docker" / "prod.env") == before


class TestTheProductionStack:
    def services(self, stack, *, but=()):
        return {
            name: service
            for name, service in stack["services"].items()
            if name not in but
        }

    def test_no_container_can_gain_privileges(self, stack):
        for name, service in self.services(stack).items():
            assert "no-new-privileges:true" in service["security_opt"], name
            assert service["cap_drop"] == ["ALL"], name
            assert service["read_only"] is True, name
            assert service["logging"]["options"]["max-size"], name
            limits = service["deploy"]["resources"]["limits"]
            assert limits["memory"] and limits["pids"], name

    def test_only_the_proxy_is_published(self, stack):
        published = [
            name
            for name, service in stack["services"].items()
            if service.get("ports")
        ]

        assert published == ["proxy"]

    def test_the_data_has_no_way_out(self, stack):
        assert stack["networks"]["backend"]["internal"] is True

        for name in ("db", "redis", "backup", "restore", "beat"):
            assert stack["services"][name]["networks"] == ["backend"], name

    def test_every_secret_is_required(self, stack):
        app = stack["services"]["web"]["environment"]

        assert ":?" in app["DJANGO_SECRET_KEY"]
        assert ":?" in app["DATABASE_URL"]
        assert app["REDIS_URL"].startswith("redis://:${REDIS_PASSWORD:?")

    def test_the_database_and_redis_ask_for_a_password(self, stack):
        db = stack["services"]["db"]["environment"]
        redis = " ".join(stack["services"]["redis"]["command"])

        assert db["POSTGRES_HOST_AUTH_METHOD"] == "scram-sha-256"
        assert "--data-checksums" in db["POSTGRES_INITDB_ARGS"]
        assert "requirepass" in redis
        # Never on Redis's command line, where `ps` would show it.
        assert "--requirepass" not in redis

    def test_backed_up_together_and_restored_on_demand(self, stack):
        backup = stack["services"]["backup"]
        restore = stack["services"]["restore"]

        assert "app-media:/media:ro" in backup["volumes"]
        assert "app-media:/media" in restore["volumes"]
        assert restore["profiles"] == ["restore"]
        assert ":?" in backup["environment"]["BACKUP_PASSPHRASE"]

    def test_the_development_stack_stays_on_this_machine(self, project):
        dev = yaml.safe_load(
            (project / "docker" / "compose.dev.yml").read_text()
        )

        for name, service in dev["services"].items():
            for port in service.get("ports", ()):
                assert port.startswith("127.0.0.1:"), name


class TestTheBackupScripts:
    def test_the_shell_is_strict_and_encrypts(self, project):
        common = (project / "docker" / "backup" / "common.sh").read_text()

        assert "set -euo pipefail" in common
        assert "umask 077" in common
        assert "--cipher-algo AES256" in common

    def test_nothing_unencrypted_reaches_the_disk(self, project):
        backup = (project / "docker" / "backup" / "backup.sh").read_text()

        assert "pg_dump --format=custom" in backup
        assert re.search(r"pg_dump [^\n]*\| encrypt", backup)
        assert re.search(r"tar -czf - [^\n]*\| encrypt", backup)

    def test_the_live_database_is_switched_last(self, project):
        restore = (project / "docker" / "backup" / "restore.sh").read_text()

        assert restore.index("restore_database_into") < restore.index(
            "RENAME TO"
        )

    def test_restore_latest_means_before_the_safety_backup(
        self, project, monkeypatch
    ):
        """`ops.py restore latest` takes a backup first; "latest" is the
        one that was newest before it, not that one."""
        spec = importlib.util.spec_from_file_location(
            "ops", project / "ops.py"
        )
        ops = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ops)
        backups = project / "backups"
        for name in ("desk-20260101T000000Z", "desk-20260102T000000Z"):
            (backups / name).mkdir()
            (backups / name / "MANIFEST").write_text("")
        (backups / "desk-20260103T000000Z.partial").mkdir()
        calls = []
        monkeypatch.setattr(ops, "compose", lambda *a: calls.append(a))

        ops.main(["restore", "latest", "--yes"])

        assert ops.backup_names()[-1] == "desk-20260102T000000Z"
        assert calls[0][-2:] == ("backup", "now")
        assert calls[2][-1] == "desk-20260102T000000Z"


class TestTheSettings:
    def run(self, project, settings, *command, **environment):
        return subprocess.run(
            [sys.executable, "manage.py", *command],
            cwd=project,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join([str(project), str(REPOSITORY)]),
                "DJANGO_SETTINGS_MODULE": f"desk.settings.{settings}",
                **environment,
            },
        )

    def test_production_refuses_to_start_without_its_secrets(self, project):
        result = self.run(project, "prod", "check")

        assert result.returncode != 0
        assert "DJANGO_SECRET_KEY is not set" in result.stderr

    def test_production_passes_the_deployment_checks(self, project):
        prod = env_file(project / "docker" / "prod.env")
        result = self.run(
            project,
            "prod",
            "check",
            "--deploy",
            "--fail-level",
            "WARNING",
            DJANGO_SECRET_KEY=prod["DJANGO_SECRET_KEY"],
            DJANGO_ALLOWED_HOSTS=prod["DJANGO_ALLOWED_HOSTS"],
            DJANGO_ADMINS=prod["DJANGO_ADMINS"],
            DATABASE_URL="sqlite:////tmp/desk-check.sqlite3",
            REDIS_URL="redis://localhost:6379/0",
        )

        assert result.returncode == 0, result.stderr

    def test_the_smoke_test_passes(self, project):
        pytest.importorskip("pytest_django")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=project,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join([str(project), str(REPOSITORY)]),
                "DJANGO_SETTINGS_MODULE": "tests.settings",
            },
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "4 passed" in result.stdout

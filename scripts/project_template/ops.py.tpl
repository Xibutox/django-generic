#!/usr/bin/env python
"""{{ title }}: running it, and keeping its data safe.

One command for what the Docker stacks do, the same on Windows, macOS
and Linux. Python 3.10+ and Docker (with Compose v2) are all it needs.

    python ops.py env              write docker/prod.env and docker/dev.env,
                                   every secret random
    python ops.py up [--dev]       build and start the stack
    python ops.py down [--dev]     stop it (the data stays)
    python ops.py ps | logs [SERVICE]
    python ops.py manage ARGS...   manage.py in the web container
                                   (createsuperuser, check --deploy, ...)

    python ops.py backup           an encrypted backup, now
    python ops.py backups          the backups, newest last
    python ops.py verify [NAME]    checksums, decryption, readability
    python ops.py restore-test [NAME]
                                   restore into a throwaway database, and
                                   record it in backups/restore-tests.log
    python ops.py restore NAME|latest
                                   back to a backup: a backup of now
                                   first, then the restore

The production stack runs a backup every day at BACKUP_TIME and a
restore test every week by itself; these commands are for the moments
in between. See README.md and SECURITY-CONTROLS.md.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCKER = ROOT / "docker"
SLUG = "{{ slug }}"
TITLE = "{{ title }}"
PROJECT = "{{ project }}"

STACKS = {
    "prod": (DOCKER / "compose.prod.yml", DOCKER / "prod.env"),
    "dev": (DOCKER / "compose.dev.yml", DOCKER / "dev.env"),
}


# -- The environment files ------------------------------------------------


def secret(length: int = 32) -> str:
    """Random, from the system's cryptographic source, and safe in a URL
    and an env file: letters, digits, ``-`` and ``_`` only. 32 bytes are
    256 bits."""
    return secrets.token_urlsafe(length)


def prod_values(domain: str, admins: str, time_zone: str) -> dict:
    local = domain in {"", "localhost", "127.0.0.1"}
    scheme = "http" if local else "https"
    host = "localhost" if local else domain

    return {
        "DJANGO_SECRET_KEY": secret(50),
        "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1" if local else domain,
        "DJANGO_CSRF_TRUSTED_ORIGINS": f"{scheme}://{host}",
        "DJANGO_SITE_URL": f"{scheme}://{host}",
        "SITE_ADDRESS": ":80" if local else domain,
        "DJANGO_HTTPS": "0" if local else "1",
        "DJANGO_HSTS_SECONDS": "",
        "DJANGO_ADMINS": admins,
        "DJANGO_DEFAULT_FROM_EMAIL": f"no-reply@{host}",
        "DJANGO_LOG_LEVEL": "INFO",
        "TZ": time_zone,
        "POSTGRES_DB": PROJECT,
        "POSTGRES_USER": f"{PROJECT}_app",
        "POSTGRES_PASSWORD": secret(),
        "REDIS_PASSWORD": secret(),
        "BACKUP_PASSPHRASE": secret(),
        "BACKUP_TIME": "02:30",
        "BACKUP_KEEP_DAYS": "30",
        "BACKUP_TEST_WEEKDAY": "7",
        "BACKUP_DIR": "../backups",
        "EMAIL_HOST": "",
        "EMAIL_PORT": "587",
        "EMAIL_HOST_USER": "",
        "EMAIL_HOST_PASSWORD": "",
        "EMAIL_USE_TLS": "1",
        "HTTP_PORT": "80",
        "HTTPS_PORT": "443",
    }


def dev_values() -> dict:
    return {
        "DJANGO_SECRET_KEY": secret(50),
        "POSTGRES_DB": PROJECT,
        "POSTGRES_USER": f"{PROJECT}_dev",
        "POSTGRES_PASSWORD": secret(),
        "REDIS_PASSWORD": secret(),
        "WEB_PORT": "8000",
        "POSTGRES_PORT": "5432",
        "REDIS_PORT": "6379",
    }


#: What each production variable is, written above it in the file.
NOTES = {
    "DJANGO_SECRET_KEY": (
        "Signs sessions and tokens. Random; never shared with another site."
    ),
    "DJANGO_ALLOWED_HOSTS": "The names the site answers to, comma-separated",
    "SITE_ADDRESS": (
        "What Caddy serves and obtains a certificate for (ports 80 and 443 "
        'must reach this machine). ":80" serves plain HTTP, for localhost '
        "only."
    ),
    "DJANGO_HTTPS": "1 behind HTTPS: secure cookies, the redirect, HSTS.",
    "DJANGO_HSTS_SECONDS": (
        "One hour when empty. Raise it to 31536000 (a year) once HTTPS works "
        "everywhere the site is reached."
    ),
    "DJANGO_ADMINS": (
        "Who is mailed an unexpected error, comma-separated addresses."
    ),
    "TZ": "The servers' time zone: the logs' timestamps and BACKUP_TIME.",
    "POSTGRES_PASSWORD": (
        "Set in the database when it is created: changing it here later "
        "also takes ALTER ROLE in the database."
    ),
    "BACKUP_PASSPHRASE": (
        "Encrypts every backup. KEEP A COPY OUTSIDE THIS SERVER (a password "
        "manager, a safe): without it no backup can ever be read."
    ),
    "BACKUP_TIME": "Every day at this time (TZ), a backup; HH:MM.",
    "BACKUP_KEEP_DAYS": "How long a backup is kept before it is deleted.",
    "BACKUP_TEST_WEEKDAY": (
        "The day of the weekly restore test, 1 (Monday) to 7."
    ),
    "BACKUP_DIR": (
        "Where the backups are written on this machine, relative to "
        "docker/. Copy it off the server (rsync, rclone, a NAS)."
    ),
    "EMAIL_HOST": "Without it, the mails are written to the log instead.",
}


def env_text(values: dict, title: str, notes: dict) -> str:
    lines = [
        f"# {title}",
        f"# Written by `python ops.py env` on "
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.",
        "# Secret: readable by its owner only, never committed (.gitignore),",
        '# never in an image (.dockerignore). An empty value is "not given".',
        "",
    ]

    for name, value in values.items():
        if name in notes:
            lines.append(f"# {notes[name]}")
        lines.append(f"{name}={value}")

    return "\n".join(lines) + "\n"


def write_secret_file(path: Path, text: str, force: bool) -> None:
    """Written with permissions for its owner alone (0600) from the
    first byte; an existing file is kept aside rather than lost."""
    if path.exists():
        if not force:
            raise SystemExit(
                f"{path.relative_to(ROOT)} exists: kept. --force writes a new "
                f"one (the old one is kept as .bak-...), but the database "
                f"and the backups were made with the old secrets."
            )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        path.rename(path.with_name(f"{path.name}.bak-{stamp}"))

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def command_env(args) -> None:
    domain = args.domain
    if domain is None:
        domain = ask(
            "The site's domain name (localhost to try it here)", "localhost"
        )
    admins = (
        args.admins
        if args.admins is not None
        else ask(
            "Who is mailed the errors (comma-separated, may be empty)", ""
        )
    )
    time_zone = args.time_zone or "{{ time_zone }}"

    prod = prod_values(domain, admins, time_zone)
    write_secret_file(
        DOCKER / "prod.env",
        env_text(prod, f"{TITLE}: the production stack's settings.", NOTES),
        args.force,
    )
    write_secret_file(
        DOCKER / "dev.env",
        env_text(
            dev_values(), f"{TITLE}: the development stack's settings.", {}
        ),
        args.force,
    )
    (ROOT / "backups").mkdir(exist_ok=True)

    if os.name == "nt":
        print(
            "Windows: docker/prod.env holds the secrets. Keep the project in "
            "a folder only your account can read."
        )
    print("Wrote docker/prod.env and docker/dev.env, every secret random.")
    print(
        "Copy BACKUP_PASSPHRASE from docker/prod.env into a password manager "
        "now: the backups cannot be read without it."
    )


def ask(question: str, default: str) -> str:
    if not sys.stdin.isatty():
        return default
    answer = input(f"{question} [{default}]: ").strip()
    return answer or default


# -- Docker Compose -------------------------------------------------------


def compose(stack: str, *arguments: str, check: bool = True) -> int:
    file, env_file = STACKS[stack]

    if not env_file.exists():
        raise SystemExit(
            f"{env_file.relative_to(ROOT)} is missing: run "
            f"`python ops.py env` first."
        )
    if shutil.which("docker") is None:
        raise SystemExit("Docker is not installed, or not on the PATH.")

    command = [
        "docker",
        "compose",
        "-f",
        str(file),
        "--env-file",
        str(env_file),
        *arguments,
    ]
    result = subprocess.run(command, cwd=ROOT)  # nosec B603 - fixed program

    if check and result.returncode:
        raise SystemExit(result.returncode)

    return result.returncode


def stack_of(args) -> str:
    return "dev" if getattr(args, "dev", False) else "prod"


def command_up(args) -> None:
    compose(stack_of(args), "up", "-d", "--build", "--remove-orphans")
    if stack_of(args) == "prod":
        print("Started. First account: python ops.py manage createsuperuser")


def command_down(args) -> None:
    compose(stack_of(args), "down")


def command_ps(args) -> None:
    compose(stack_of(args), "ps")


def command_logs(args) -> None:
    compose(stack_of(args), "logs", "--tail", "200", *args.service)


def command_manage(args) -> None:
    # No terminal for the container when there is none here (a script).
    terminal = () if sys.stdin.isatty() else ("-T",)
    compose(
        stack_of(args),
        "exec",
        *terminal,
        "web",
        "python",
        "manage.py",
        *args.arguments,
    )


def command_backup(args) -> None:
    compose("prod", "run", "--rm", "backup", "now")


def command_backups(args) -> None:
    compose("prod", "run", "--rm", "backup", "list")


def command_verify(args) -> None:
    compose("prod", "run", "--rm", "backup", "verify", args.name)


def command_restore_test(args) -> None:
    compose("prod", "run", "--rm", "backup", "test", args.name)


def env_value(name: str, default: str = "") -> str:
    """A value of docker/prod.env, as Compose reads it."""
    for line in STACKS["prod"][1].read_text("utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip() or default
    return default


def backup_names() -> list[str]:
    """The complete backups in BACKUP_DIR, oldest first."""
    folder = (DOCKER / env_value("BACKUP_DIR", "../backups")).resolve()
    if not folder.is_dir():
        return []
    return sorted(
        path.name
        for path in folder.glob(f"{SLUG}-*")
        if (path / "MANIFEST").is_file() and not path.name.endswith(".partial")
    )


def command_restore(args) -> None:
    names = backup_names()
    # Named now: the backup taken before restoring becomes the latest.
    name = names[-1] if args.name == "latest" and names else args.name
    if name not in names:
        raise SystemExit(
            f"No backup named {name}. `python ops.py backups` lists them."
        )

    if not args.yes:
        print(
            f"This replaces the database and the uploaded files of {SLUG} "
            f"with the backup {name}. A backup of the present state is "
            f"taken first."
        )
        if input(f"Type {SLUG} to go on: ").strip() != SLUG:
            raise SystemExit("Nothing was changed.")

    print("A backup of the present state first...")
    compose("prod", "run", "--rm", "backup", "now")
    print("Stopping the application...")
    compose("prod", "stop", "proxy", "web", "worker", "beat", "backup")
    try:
        compose("prod", "--profile", "restore", "run", "--rm", "restore", name)
    finally:
        print("Starting the application again...")
        compose("prod", "up", "-d")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1],
    )
    commands = parser.add_subparsers(dest="command", required=True)

    env = commands.add_parser("env", help="write the environment files")
    env.add_argument("--domain", help="the site's domain, or localhost")
    env.add_argument("--admins", help="addresses mailed the errors")
    env.add_argument("--time-zone", help="e.g. Europe/Paris")
    env.add_argument(
        "--force", action="store_true", help="replace existing files"
    )
    env.set_defaults(handler=command_env)

    for name, handler, text in (
        ("up", command_up, "build and start"),
        ("down", command_down, "stop"),
        ("ps", command_ps, "the containers"),
    ):
        sub = commands.add_parser(name, help=text)
        sub.add_argument(
            "--dev", action="store_true", help="the development stack"
        )
        sub.set_defaults(handler=handler)

    logs = commands.add_parser("logs", help="the last lines of the logs")
    logs.add_argument("--dev", action="store_true")
    logs.add_argument("service", nargs="*")
    logs.set_defaults(handler=command_logs)

    manage = commands.add_parser(
        "manage", help="manage.py in the web container"
    )
    manage.add_argument("--dev", action="store_true")
    manage.add_argument("arguments", nargs=argparse.REMAINDER)
    manage.set_defaults(handler=command_manage)

    commands.add_parser("backup", help="a backup now").set_defaults(
        handler=command_backup
    )
    commands.add_parser("backups", help="the backups").set_defaults(
        handler=command_backups
    )
    for name, handler, text in (
        ("verify", command_verify, "check a backup"),
        (
            "restore-test",
            command_restore_test,
            "restore into a throwaway database",
        ),
    ):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("name", nargs="?", default="latest")
        sub.set_defaults(handler=handler)

    restore = commands.add_parser("restore", help="back to a backup")
    restore.add_argument("name", help="a backup's name, or latest")
    restore.add_argument("--yes", action="store_true", help="do not ask")
    restore.set_defaults(handler=command_restore)

    args = parser.parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()

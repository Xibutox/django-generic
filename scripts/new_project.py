"""A new Django project on django-generic, ready to deploy, in one command.

    python scripts/new_project.py                  # asks, with defaults
    python scripts/new_project.py ../desk --name desk --title "Support desk" \\
        --domain desk.example.com --no-input

What it writes, beside this checkout or wherever TARGET says:

- the project: settings split into base, dev and prod (every production
  secret read from the environment), URLs, ASGI and Celery, a first app
  with one model, a smoke test;
- the framework's wheel in ``vendor/``, built from this checkout and
  named by ``requirements.txt`` (django-generic is not on PyPI);
- ``docker/``: the images, a development stack and a hardened production
  stack - Caddy in front, Postgres and Redis on a network with no way
  out, every container without root's capabilities, on a read-only
  filesystem - and its encrypted, verified, daily backups;
- ``docker/prod.env`` and ``docker/dev.env``, every password, key and
  passphrase random, readable by their owner alone;
- ``ops.py``: start, stop, back up, verify, test a restore, restore - the
  same commands on Windows, macOS and Linux;
- ``README.md`` and ``SECURITY-CONTROLS.md``, the second mapping each
  choice to the ISO/IEC 27001:2022 Annex A / 27002:2022 controls.

Only the standard library: it runs before anything is installed. See
docs/new-project.md.
"""

from __future__ import annotations

import argparse
import keyword
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "project_template"

#: Names a project or app cannot take: they would shadow a package the
#: project imports.
RESERVED = {
    "django",
    "generic",
    "rest_framework",
    "channels",
    "daphne",
    "celery",
    "redis",
    "tests",
    "test",
    "docker",
    "vendor",
    "site",
    "ops",
    "manage",
}

#: Template files whose name changes in the project.
RENAMED = {
    "gitignore": ".gitignore",
    "dockerignore": ".dockerignore",
    "gitattributes": ".gitattributes",
}


def framework_version() -> str:
    text = (REPOSITORY / "generic" / "__init__.py").read_text("utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def wheel_name(version: str) -> str:
    return f"django_generic-{version}-py3-none-any.whl"


def check_name(value: str, what: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value or ""):
        raise ValueError(
            f"{what} '{value}': lower-case letters, digits and _, starting "
            f"with a letter"
        )
    if keyword.iskeyword(value) or value in RESERVED:
        raise ValueError(f"{what} '{value}' is taken by Python or a package")
    return value


def check_time_zone(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+)*", value):
        raise ValueError(f"time zone '{value}': e.g. Europe/Paris or UTC")
    return value


def ask(question: str, default: str, interactive: bool, check=None) -> str:
    while True:
        answer = default
        if interactive:
            answer = input(f"{question} [{default}]: ").strip() or default
        try:
            return check(answer) if check else answer
        except ValueError as error:
            if not interactive:
                raise SystemExit(str(error))
            print(f"  {error}")


def answers(args) -> dict:
    interactive = not args.no_input and sys.stdin.isatty()

    target = Path(
        args.target
        or ask("Folder of the new project", "../mysite", interactive)
    ).resolve()
    default_name = re.sub(r"[^a-z0-9_]", "_", target.name.lower()).strip("_")
    if not default_name or not default_name[0].isalpha():
        default_name = "mysite"
    name = args.name or ask(
        "Python package of the project",
        default_name,
        interactive,
        lambda value: check_name(value, "The project's name"),
    )
    check_name(name, "The project's name")
    app = args.app or ask(
        "Its first app",
        "core",
        interactive,
        lambda value: check_name(value, "The app's name"),
    )
    check_name(app, "The app's name")
    if app == name:
        raise SystemExit("The app and the project need two different names.")
    title = args.title or ask(
        "The site's title", name.replace("_", " ").title(), interactive
    )
    domain = args.domain or ask(
        "Its domain name (localhost to try it on this machine)",
        "localhost",
        interactive,
    )
    admins = (
        args.admins
        if args.admins is not None
        else ask("Who is mailed the errors (may be empty)", "", interactive)
    )
    time_zone = args.time_zone or ask(
        "Time zone", "Europe/Paris", interactive, check_time_zone
    )
    check_time_zone(time_zone)
    language = args.language or ask(
        "Interface language (en or fr)", "en", interactive
    )

    return {
        "target": target,
        "project": name,
        "app": app,
        "app_class": "".join(part.title() for part in app.split("_")),
        "slug": name.replace("_", "-"),
        "title": title.replace('"', "'"),
        "domain": domain,
        "admins": admins,
        "time_zone": time_zone,
        "language": {"fr": "fr", "en": "en-us"}.get(language, language),
    }


def render(text: str, context: dict) -> str:
    for key, value in context.items():
        text = text.replace("{{ %s }}" % key, str(value))

    left = re.search(r"\{\{ [a-z_]+ \}\}", text)
    if left:
        raise RuntimeError(f"{left.group(0)} is not given a value")

    return text


def write_project(context: dict) -> list[Path]:
    target = context["target"]
    written = []

    for source in sorted(TEMPLATE.rglob("*.tpl")):
        relative = source.relative_to(TEMPLATE).with_suffix("")
        parts = [
            {
                "project_name": context["project"],
                "app_name": context["app"],
            }.get(part, RENAMED.get(part, part))
            for part in relative.parts
        ]
        destination = target.joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            render(source.read_text("utf-8"), context),
            "utf-8",
            newline="\n",
        )
        if destination.suffix == ".sh" or destination.name in {
            "manage.py",
            "ops.py",
        }:
            destination.chmod(0o755)
        written.append(destination)

    return written


def build_wheel(destination: Path, version: str) -> Path:
    """The framework's wheel, from this checkout: what a project installs
    without reaching the repository (docs/installation.md)."""
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(  # nosec B603 - this interpreter, fixed arguments
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--quiet",
                "--wheel-dir",
                folder,
                str(REPOSITORY),
            ],
            check=True,
        )
        built = Path(folder) / wheel_name(version)
        destination.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy2(built, destination / built.name))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        epilog="Without --no-input, every option not given is asked for.",
    )
    parser.add_argument("target", nargs="?", help="the new project's folder")
    parser.add_argument("--name", help="its Python package, e.g. desk")
    parser.add_argument("--app", help="its first app (default: core)")
    parser.add_argument("--title", help="the site's title")
    parser.add_argument("--domain", help="its domain name, or localhost")
    parser.add_argument("--admins", help="addresses mailed the errors")
    parser.add_argument("--time-zone", help="default: Europe/Paris")
    parser.add_argument("--language", help="en (default) or fr")
    wheel = parser.add_mutually_exclusive_group()
    wheel.add_argument(
        "--wheel", type=Path, help="a wheel already built, in place of one"
    )
    wheel.add_argument(
        "--no-wheel",
        action="store_true",
        help="leave vendor/ empty (put the wheel there yourself)",
    )
    parser.add_argument(
        "--no-input", action="store_true", help="ask nothing: the defaults"
    )
    args = parser.parse_args(argv)

    context = answers(args)
    target = context.pop("target")
    version = framework_version()
    context.update(version=version, wheel=wheel_name(version))

    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} exists and is not empty: nothing written.")

    print(f"Writing {context['title']} in {target}")
    write_project({**context, "target": target})

    vendor = target / "vendor"
    vendor.mkdir(exist_ok=True)
    if args.wheel:
        shutil.copy2(args.wheel, vendor / wheel_name(version))
    elif not args.no_wheel:
        print("Building the framework's wheel...")
        build_wheel(vendor, version)

    # The secrets: written by the project's own ops.py, which writes
    # them again whenever asked to.
    subprocess.run(  # nosec B603 - this interpreter, the file just written
        [
            sys.executable,
            str(target / "ops.py"),
            "env",
            "--domain",
            context["domain"],
            "--admins",
            context["admins"],
            "--time-zone",
            context["time_zone"],
        ],
        check=True,
        stdin=subprocess.DEVNULL,
    )

    print(f"""
Done. Next:

  cd {target}
  python ops.py up                       # the production stack, in Docker
  python ops.py manage createsuperuser   # the first account
  python ops.py backup                   # and a first backup

or, to work on it: python -m venv .venv, activate it, then
  pip install -r requirements-dev.txt && python manage.py migrate
  python manage.py runserver

README.md says the rest; SECURITY-CONTROLS.md, what each choice answers
in ISO/IEC 27001 / 27002.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())

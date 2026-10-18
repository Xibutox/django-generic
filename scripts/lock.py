"""Write ``requirements/constraints.txt``: one version for every package.

The Docker images and CI install with these versions as constraints
(``PIP_CONSTRAINT``, ``pip install -c``), so two builds of the same commit
get the same packages, and the versions pip-audit checked are the ones
that ship. The list is read from ``requirements/constraints.in`` - every
extra, the document manager's libraries, the scheduler, the servers - and
resolved by uv (``pip install uv``) for every system, Python 3.12 on::

    python scripts/lock.py             # add what constraints.in gained
    python scripts/lock.py --upgrade   # every package to its newest
    python scripts/lock.py --check     # fail if constraints.txt is stale

Without ``--upgrade`` the versions already written are kept: only what
``constraints.in`` added or changed is resolved again.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess  # nosec B404 - runs uv, named below, never a shell
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "requirements"
SOURCE = FOLDER / "constraints.in"
OVERRIDES = FOLDER / "overrides.txt"
TARGET = FOLDER / "constraints.txt"


def command(output: Path, upgrade: bool) -> list[str]:
    """The uv command writing the constraints to ``output``."""
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("uv is needed: pip install uv")
    args = [
        uv,
        "pip",
        "compile",
        "requirements/constraints.in",
        "--override",
        "requirements/overrides.txt",
        "--universal",
        "--python-version",
        "3.12",
        "--no-emit-package",
        "django-generic",
        "--quiet",
        "--custom-compile-command",
        "python scripts/lock.py",
        "-o",
        str(output),
    ]
    if upgrade:
        args.append("--upgrade")
    return args


def pins(path: Path) -> list[str]:
    """The lines that name a version, comments left out."""
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.lstrip().startswith("#")
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--upgrade", action="store_true")
    group.add_argument("--check", action="store_true")
    options = parser.parse_args(argv)

    if not options.check:
        subprocess.run(  # nosec B603 - fixed arguments
            command(TARGET, options.upgrade), cwd=ROOT, check=True
        )
        print(f"Wrote {TARGET.relative_to(ROOT)}")
        return 0

    # Resolved again from the versions already written: anything that
    # differs is something constraints.in asks for and the file lacks.
    with tempfile.TemporaryDirectory() as folder:
        fresh = Path(folder) / "constraints.txt"
        shutil.copyfile(TARGET, fresh)
        subprocess.run(  # nosec B603 - fixed arguments
            command(fresh, False), cwd=ROOT, check=True
        )
        if pins(fresh) != pins(TARGET):
            print(
                "requirements/constraints.txt does not match "
                "constraints.in: run python scripts/lock.py",
                file=sys.stderr,
            )
            return 1
    print("requirements/constraints.txt is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())

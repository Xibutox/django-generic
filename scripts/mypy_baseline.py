"""Run mypy on ``generic`` and fail on any error the baseline lacks.

mypy reports errors the framework has carried for a long time - most of
them django-stubs trailing the Django in use. Rather than ignoring all of
mypy, CI keeps those in ``scripts/mypy-baseline.txt`` and fails on a new
one::

    python scripts/mypy_baseline.py            # fail on a new error
    python scripts/mypy_baseline.py --update   # write the current errors

An error is its file, message and code, without its line, so code moving
around does not count as new. Fixing errors is welcome: ``--update``
then shrinks the baseline, and the check says when it can.
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404 - runs mypy, never a shell
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "mypy-baseline.txt"

#: ``path:line: error: message  [code]`` - mypy's default format.
LINE = re.compile(r"^(?P<path>[^:]+):\d+: error: (?P<rest>.*)$")


def current() -> Counter[str]:
    """Every error mypy reports now, keyed without its line number."""
    result = subprocess.run(  # nosec B603 - fixed arguments
        [sys.executable, "-m", "mypy", "generic", "--no-error-summary"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        sys.stderr.write(result.stdout + result.stderr)
        sys.exit("mypy did not run")
    errors: Counter[str] = Counter()
    for line in result.stdout.splitlines():
        match = LINE.match(line.replace("\\", "/"))
        if match:
            errors[f"{match['path']}: {match['rest']}"] += 1
    return errors


def read() -> Counter[str]:
    if not BASELINE.exists():
        return Counter()
    lines = BASELINE.read_text(encoding="utf-8").splitlines()
    return Counter(line for line in lines if line and line[0] != "#")


def write(errors: Counter[str]) -> None:
    header = (
        "# mypy errors carried on purpose: python scripts/mypy_baseline.py"
        " --update\n"
    )
    body = "".join(f"{key}\n" for key in sorted(errors.elements()))
    BASELINE.write_text(header + body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true")
    options = parser.parse_args(argv)

    errors = current()
    if options.update:
        write(errors)
        print(f"{sum(errors.values())} errors written to {BASELINE.name}")
        return 0

    new = errors - read()
    fixed = read() - errors
    for key in sorted(new.elements()):
        print(f"new: {key}")
    if new:
        print(
            f"{sum(new.values())} new mypy error(s). Fix them, or - for an "
            "error that is the stubs' and not the code's - run "
            "python scripts/mypy_baseline.py --update",
            file=sys.stderr,
        )
        return 1
    if fixed:
        print(
            f"{sum(fixed.values())} baseline error(s) fixed: "
            "python scripts/mypy_baseline.py --update shrinks the baseline"
        )
    print(f"mypy: no new error ({sum(errors.values())} in the baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

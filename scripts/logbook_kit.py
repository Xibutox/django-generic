"""Assemble the logbook's migration kit in a new folder: the logbook,
the framework as a wheel, the Docker files and the two migration
scripts - everything to run it away from this repository.

    python scripts/logbook_kit.py ../logbook-kit
    python scripts/logbook_kit.py ../logbook-kit --zip

See logbook/kit/README.md for what is in it and how it is used.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess  # nosec B404 - pip, with fixed arguments
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGBOOK = ROOT / "logbook"
SKIPPED = shutil.ignore_patterns(
    "db.sqlite3", "staticfiles", "__pycache__", "*.pyc", "kit", "migration"
)
RENAMED = {"env.example": ".env.example"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("dest", type=Path, help="A new, empty folder.")
    parser.add_argument("--zip", action="store_true", help="Zip it too.")
    options = parser.parse_args()
    dest: Path = options.dest.resolve()

    if dest.exists() and any(dest.iterdir()):
        parser.error(f"{dest} is not empty.")

    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(LOGBOOK, dest / "logbook", ignore=SKIPPED)

    for path in sorted((LOGBOOK / "kit").iterdir()):
        shutil.copy2(path, dest / RENAMED.get(path.name, path.name))

    shutil.copy2(LOGBOOK / "migration" / "export_planner.py", dest)
    (dest / "import").mkdir()
    (dest / "import" / ".gitkeep").touch()
    (dest / ".gitignore").write_text(".env\nimport/*.json\n", encoding="utf-8")
    subprocess.run(  # nosec B603
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(ROOT),
            "--no-deps",
            "--quiet",
            "--wheel-dir",
            str(dest / "vendor"),
        ],
        check=True,
    )
    print(f"The kit: {dest}")

    if options.zip:
        archive = shutil.make_archive(str(dest), "zip", dest.parent, dest.name)
        print(f"Zipped: {archive}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

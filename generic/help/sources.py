"""Where the help page finds the licence and the changelogs.

Both are files a project already has next to its code. What is
configured is only where to look, and the defaults are the usual names
at the root of the project - so a project that writes a ``CHANGELOG.md``
and a ``LICENSE`` gets both pages with nothing to declare.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from django.conf import settings

from generic.conf import generic_settings
from generic.help.changelog import Release, read

#: Tried in order at the root of the project, when nothing is declared.
LICENCE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE")
CHANGELOG_NAMES = ("CHANGELOG.md", "CHANGELOG", "CHANGES.md")

#: A licence is a few pages at most; beyond this something else is being
#: pointed at, and a page view must not read it into memory.
MAX_LICENCE_SIZE = 256 * 1024


def project_root() -> Path:
    """Where the project's own files live."""
    base = getattr(settings, "BASE_DIR", None)

    return Path(base) if base else Path.cwd()


def framework_root() -> Path:
    """Where the framework's own files live: its package, which ships
    its changelog - installed from a wheel as from a checkout."""
    return Path(__file__).resolve().parent.parent


@dataclasses.dataclass(frozen=True)
class ChangelogSource:
    """One changelog file, with the name a reader sees above it."""

    label: str
    path: Path
    releases: list[Release]

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "releases": [release.as_dict() for release in self.releases],
        }


def _declared_changelogs() -> list[tuple[str, Path]]:
    """``CHANGELOG_FILES`` as ``(label, path)`` pairs."""
    declared = generic_settings.CHANGELOG_FILES or ()
    pairs: list[tuple[str, Path]] = []

    for entry in declared:
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            label, path = entry
        else:
            label, path = "", entry

        pairs.append((str(label), Path(path)))

    return pairs


def changelogs() -> list[ChangelogSource]:
    """Every changelog worth showing, the application's first.

    Declared explicitly, or found at the root of the project and of the
    framework - an application's own changes matter more to the person
    reading than the framework's, so they come first.
    """
    pairs = _declared_changelogs()

    if not pairs:
        root = project_root()
        application = str(generic_settings.SITE_TITLE or "")
        pairs = [(application, root / name) for name in CHANGELOG_NAMES]
        pairs.append(("django-generic", framework_root() / "CHANGELOG.md"))

    sources: list[ChangelogSource] = []

    for label, path in pairs:
        releases = read(path)

        if releases:
            sources.append(
                ChangelogSource(
                    label=label or path.stem.replace("_", " ").title(),
                    path=path,
                    releases=releases,
                )
            )

    return sources


def licence() -> dict[str, str]:
    """The licence text, and the file it came from.

    ``{"name": ..., "text": ...}``, empty when the project has none to
    show - which is a page without that section, not an error.
    """
    declared = generic_settings.LICENSE_FILE
    candidates = (
        [Path(declared)]
        if declared
        else [project_root() / name for name in LICENCE_NAMES]
    )

    for path in candidates:
        try:
            if not path.is_file() or path.stat().st_size > MAX_LICENCE_SIZE:
                continue

            return {
                "name": path.name,
                "text": path.read_text(encoding="utf-8"),
            }
        except OSError:
            continue

    return {"name": "", "text": str(generic_settings.LICENSE_TEXT or "")}

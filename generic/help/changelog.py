"""Reading a CHANGELOG the way it is written, as data.

The changes an application went through are already written down, in the
file the developers edit when they change something. Nothing here
invents a second place to record them: it reads those files and turns
them into rows a page can draw.

The shape understood is `Keep a Changelog <https://keepachangelog.com>`_,
which is what most projects already write::

    ## [1.4.0] - 2026-09-18

    ### Added
    - A row of search fields under the column headers.

    ### Fixed
    - A date column drawn as a link filtered as text.

A heading without brackets, an ``Unreleased`` section and a plain
paragraph between headings are all accepted. Anything the parser does
not recognise becomes a note under the release it follows, rather than
being dropped: the point is to show what was written.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

#: Enough for years of releases; a file larger than this is not a
#: changelog and must not be read into memory on a page view.
MAX_SIZE = 512 * 1024

#: ``## [1.4.0] - 2026-09-18``, ``## 1.4.0 - 2026-09-18``, ``## Unreleased``
RELEASE = re.compile(
    r"^##\s+\[?(?P<version>[^\]\s]+)\]?\s*(?:[-–]\s*(?P<date>.+))?$"
)
#: ``### Added``
SECTION = re.compile(r"^###\s+(?P<name>.+?)\s*$")
#: ``- something`` or ``* something``
ITEM = re.compile(r"^\s*[-*]\s+(?P<text>.+?)\s*$")


@dataclasses.dataclass(frozen=True)
class Section:
    """One kind of change inside a release: Added, Fixed, ..."""

    name: str
    items: list[str]


@dataclasses.dataclass(frozen=True)
class Release:
    """One version, as the file describes it."""

    version: str
    date: str
    sections: list[Section]
    notes: list[str]

    @property
    def is_unreleased(self) -> bool:
        return self.version.lower() in {"unreleased", "next", "master"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "date": self.date,
            "isUnreleased": self.is_unreleased,
            "sections": [
                {"name": section.name, "items": list(section.items)}
                for section in self.sections
            ],
            "notes": list(self.notes),
        }


def parse(text: str) -> list[Release]:
    """Every release a changelog holds, newest first as written."""
    releases: list[Release] = []
    version = date = ""
    sections: list[Section] = []
    notes: list[str] = []
    current: list[str] | None = None
    # A note goes on until a blank line: a paragraph wrapped at the
    # file's width is one paragraph on the page.
    in_note = False

    def flush() -> None:
        if version:
            releases.append(
                Release(
                    version=version,
                    date=date,
                    sections=list(sections),
                    notes=list(notes),
                )
            )

    for raw in text.splitlines():
        line = raw.rstrip()
        release = RELEASE.match(line)

        if release:
            flush()
            version = release.group("version").strip()
            date = (release.group("date") or "").strip()
            sections = []
            notes = []
            current = None
            in_note = False
            continue

        if not version:
            # Anything before the first release heading is the file's
            # own title and preamble.
            continue

        section = SECTION.match(line)

        if section:
            sections.append(Section(name=section.group("name"), items=[]))
            current = sections[-1].items
            in_note = False
            continue

        item = ITEM.match(line)

        if item:
            text_item = item.group("text")

            if current is None:
                # A list with no "### Added" above it: keep it under the
                # release itself rather than losing it.
                sections.append(Section(name="", items=[]))
                current = sections[-1].items

            current.append(text_item)
            in_note = False
            continue

        if not line.strip():
            in_note = False
            continue

        # An indented line under a list item is the rest of that item:
        # entries are wrapped at the width the file is written to, and
        # showing the second half as a paragraph of its own scatters
        # the sentence across the page.
        if raw[:1].isspace() and current:
            current[-1] = f"{current[-1]} {line.strip()}"
            continue

        if in_note and notes:
            notes[-1] = f"{notes[-1]} {line.strip()}"
        else:
            notes.append(line.strip())

        in_note = True

    flush()

    return releases


def read(path: Path) -> list[Release]:
    """Parse one file, or nothing when it cannot be read."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_SIZE:
            return []

        return parse(path.read_text(encoding="utf-8"))
    except OSError:
        # A changelog that cannot be read is not worth a 500: the page
        # says the section is empty.
        return []

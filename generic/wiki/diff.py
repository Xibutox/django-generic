"""What changed between two versions of a page, as lines of text.

A page is HTML; a reader comparing two versions wants its words. Each
block - a paragraph, a heading, a list item, a table row - is a line;
the lines are compared, and a line that changed says which words did.

    diff(before_html, after_html)
    -> {"lines": [{"op": "equal" | "insert" | "delete", "text"},
                  {"op": "change", "parts": [{"op", "text"}]},
                  {"op": "skip", "count": 12}],
        "added": 3, "removed": 1}

Only text comes out - never HTML: the client writes it with
``textContent``.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any

#: Tags that start and end a line.
BLOCKS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "blockquote",
        "pre",
        "tr",
        "div",
        "table",
        "ul",
        "ol",
    }
)

#: Unchanged lines kept around a change; a longer run is folded.
CONTEXT = 2

_SPACES = re.compile(r"\s+")
_WORDS = re.compile(r"\s+|\w+|[^\w\s]")


class _Lines(HTMLParser):
    """The text of a page, a line per block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.current: list[str] = []

    def flush(self) -> None:
        text = _SPACES.sub(" ", "".join(self.current)).strip(" |")
        self.current = []

        if text:
            self.lines.append(text)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in BLOCKS:
            self.flush()
        elif tag == "br":
            self.flush()
        elif tag == "hr":
            self.flush()
            self.lines.append("---")
        elif tag == "img":
            values = dict(attrs)
            name = (
                values.get("alt")
                or PurePosixPath((values.get("src") or "").rstrip("/")).name
            )
            self.current.append(f" [{name or 'image'}] ")

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCKS:
            self.flush()
        elif tag in ("td", "th"):
            # A row is one line, its cells apart.
            self.current.append(" | ")

    def handle_data(self, data: str) -> None:
        self.current.append(data)


def lines_of(html: str | None) -> list[str]:
    """The lines of text ``html`` reads as."""
    parser = _Lines()
    parser.feed(html or "")
    parser.close()
    parser.flush()

    return parser.lines


def words(before: str, after: str) -> list[dict[str, str]]:
    """One changed line, as the runs of words kept, taken out and put
    in."""
    old = _WORDS.findall(before)
    new = _WORDS.findall(after)
    parts: list[dict[str, str]] = []

    def add(op: str, text: str) -> None:
        if not text:
            return

        if parts and parts[-1]["op"] == op:
            parts[-1]["text"] += text
        else:
            parts.append({"op": op, "text": text})

    matcher = SequenceMatcher(None, old, new, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            add("equal", "".join(old[i1:i2]))
            continue

        add("delete", "".join(old[i1:i2]))
        add("insert", "".join(new[j1:j2]))

    return parts


def fold(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Long runs of unchanged lines as ``{"op": "skip", "count"}``,
    ``CONTEXT`` lines kept on each side of a change."""
    folded: list[dict[str, Any]] = []
    index = 0

    while index < len(lines):
        if lines[index]["op"] != "equal":
            folded.append(lines[index])
            index += 1
            continue

        end = index

        while end < len(lines) and lines[end]["op"] == "equal":
            end += 1

        run = lines[index:end]
        head = CONTEXT if index else 0
        tail = CONTEXT if end < len(lines) else 0

        if len(run) > head + tail + 1:
            folded += run[:head]
            folded.append({"op": "skip", "count": len(run) - head - tail})
            folded += run[len(run) - tail :] if tail else []
        else:
            folded += run

        index = end

    return folded


def diff(before: str | None, after: str | None) -> dict[str, Any]:
    """From ``before`` to ``after``, two pages' HTML."""
    old = lines_of(before)
    new = lines_of(after)
    lines: list[dict[str, Any]] = []
    added = removed = 0
    matcher = SequenceMatcher(None, old, new, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            lines += [{"op": "equal", "text": text} for text in old[i1:i2]]
            continue

        # As many lines before as after: each one rewritten.
        if tag == "replace" and i2 - i1 == j2 - j1:
            for was, now in zip(old[i1:i2], new[j1:j2]):
                lines.append({"op": "change", "parts": words(was, now)})
                added += 1
                removed += 1

            continue

        lines += [{"op": "delete", "text": text} for text in old[i1:i2]]
        lines += [{"op": "insert", "text": text} for text in new[j1:j2]]
        removed += i2 - i1
        added += j2 - j1

    return {"lines": fold(lines), "added": added, "removed": removed}

"""What a piece of work has to say about itself, as a tree.

Work behind a simple button is rarely simple: one click recomputes forty
invoices, three of them have no address, one of them fails, and the
person who clicked needs to read that - not a single "Done." and not a
traceback. A report is the shape for it: messages with a level, grouped
into sections that fold, the worst level of a section showing on its
title so a closed section still says whether it went well::

    report = Report()

    for customer in customers:
        with report.section(customer.name, isolated=True) as section:
            section.info(gettext("12 invoices recomputed."))

            if not customer.address:
                section.warning(gettext("No address: nothing was sent."))

    return report        # from an @action, or operation_response(report)

``isolated=True`` is the usual pattern for "one item at a time": the
section runs in a savepoint, and an exception inside it rolls that item
back, becomes an error line of the section, and lets the next item go
on. Outside an isolated section an exception propagates as always.

The same methods are on a task run (``run.warning(...)``), which keeps
its report on the row: :mod:`generic.tasks` and its operations.

A report travels as JSON - a list of nodes, each ``{"level", "title",
"detail", "children"}`` - and the browser draws it with
``Generic.operations`` (``js/operations.js``). Text only: a node is
never HTML.
"""

from __future__ import annotations

import contextlib
import logging
import time
import traceback
from typing import Any, Callable, Iterator

from django.db import transaction
from django.utils.translation import gettext, ngettext

logger = logging.getLogger(__name__)

#: From the least to the most serious. The names are the toasts' own, so
#: a level reaches the browser as it is.
LEVELS = ("info", "success", "warning", "error")

#: A title is a line; a detail is a paragraph, not a log file.
MAX_TITLE = 500
MAX_DETAIL = 4000

#: Nodes kept in one report. Work over a hundred thousand rows should
#: say what went wrong, not keep a line per row that went right.
MAX_NODES = 2000


def worst(levels: Any, default: str = "info") -> str:
    """The most serious of some levels."""
    found = [level for level in levels if level in LEVELS]

    if not found:
        return default

    return max(found, key=LEVELS.index)


def check_level(level: str) -> str:
    if level not in LEVELS:
        raise ValueError(
            f"Unknown report level {level!r}. Choose from {', '.join(LEVELS)}."
        )

    return level


def node_level(node: dict[str, Any]) -> str:
    """A node's own level, or its children's worst when it is worse."""
    return worst(
        [node.get("level", "info")]
        + [node_level(child) for child in node.get("children") or []]
    )


def count_levels(nodes: list[dict[str, Any]]) -> dict[str, int]:
    """How many lines of each level, sections left out."""
    counts = dict.fromkeys(LEVELS, 0)

    def walk(items: list[dict[str, Any]]) -> None:
        for item in items:
            children = item.get("children") or []

            if children:
                walk(children)
            elif item.get("level") in counts:
                counts[item["level"]] += 1

    walk(nodes)

    return counts


def describe_counts(counts: dict[str, int], fine: Any = None) -> str:
    """ "2 errors, 1 warning" - or ``fine``, that all went well."""
    parts = []

    if counts.get("error"):
        parts.append(
            ngettext("%(count)s error", "%(count)s errors", counts["error"])
            % {"count": counts["error"]}
        )

    if counts.get("warning"):
        parts.append(
            ngettext(
                "%(count)s warning", "%(count)s warnings", counts["warning"]
            )
            % {"count": counts["warning"]}
        )

    if not parts:
        return gettext("Everything went well.") if fine is None else fine

    return ", ".join(parts)


class Section:
    """A place lines are written to: the report itself, or a section."""

    def __init__(
        self,
        nodes: list[dict[str, Any]],
        report: "Report",
    ) -> None:
        self._nodes = nodes
        self._report = report

    # -- lines -------------------------------------------------------------

    def add(
        self,
        level: str,
        title: Any,
        detail: Any = "",
        **extra: Any,
    ) -> dict[str, Any]:
        """One line. ``extra`` keys travel with it (a ``url``, a count)."""
        node = {
            "level": check_level(level),
            "title": str(title)[:MAX_TITLE],
            "detail": str(detail or "")[:MAX_DETAIL],
            "children": [],
            **extra,
        }

        if "url" in node and not _safe_url(node["url"]):
            # A line may lead to a record; never to a script.
            del node["url"]

        if self._report.size >= MAX_NODES:
            self._report.truncated += 1
            return node

        self._report.size += 1
        self._nodes.append(node)
        self._report.changed()

        return node

    def info(self, title: Any, detail: Any = "", **extra: Any) -> dict:
        return self.add("info", title, detail, **extra)

    def success(self, title: Any, detail: Any = "", **extra: Any) -> dict:
        return self.add("success", title, detail, **extra)

    def warning(self, title: Any, detail: Any = "", **extra: Any) -> dict:
        return self.add("warning", title, detail, **extra)

    def error(self, title: Any, detail: Any = "", **extra: Any) -> dict:
        return self.add("error", title, detail, **extra)

    # -- sections ----------------------------------------------------------

    @contextlib.contextmanager
    def section(
        self,
        title: Any,
        detail: Any = "",
        *,
        isolated: bool = False,
        level: str = "info",
        **extra: Any,
    ) -> Iterator["Section"]:
        """Lines grouped under a title, folded in the browser.

        ``isolated=True``: the block runs in a savepoint, and an
        exception rolls it back and is written as the section's last
        line instead of stopping the work.
        """
        node = self.add(level, title, detail, **extra)
        section = Section(node["children"], self._report)

        if not isolated:
            yield section
            self._report.changed(force=True)
            return

        try:
            with transaction.atomic():
                yield section
        except Exception as error:  # noqa: BLE001 - written down instead
            logger.exception("Isolated section %r failed", node["title"])
            section.error(describe_exception(error))
            self._report.failures += 1

        self._report.changed(force=True)


class Report(Section):
    """A tree of messages about one piece of work.

    ``on_change`` is called as lines arrive - throttled to once a second
    unless forced - which is how a task run saves the report it is
    writing while it writes it.
    """

    def __init__(
        self,
        nodes: list[dict[str, Any]] | None = None,
        *,
        title: Any = "",
        on_change: Callable[[], None] | None = None,
        interval: float = 1.0,
    ) -> None:
        self.nodes: list[dict[str, Any]] = nodes if nodes is not None else []
        self.title = str(title or "")
        self.size = _size(self.nodes)
        self.truncated = 0
        #: Isolated sections that ended in an exception.
        self.failures = 0
        self._on_change = on_change
        self._interval = interval
        self._last = 0.0
        super().__init__(self.nodes, self)

    def changed(self, force: bool = False) -> None:
        if self._on_change is None:
            return

        now = time.monotonic()

        if force or now - self._last >= self._interval:
            self._last = now
            self._on_change()

    @property
    def level(self) -> str:
        """How it went: ``warning`` or ``error`` when a line says so,
        ``success`` otherwise - lines of information are not news."""
        found = worst([node_level(node) for node in self.nodes])

        return found if found in ("warning", "error") else "success"

    def counts(self) -> dict[str, int]:
        return count_levels(self.nodes)

    def as_list(self) -> list[dict[str, Any]]:
        nodes = list(self.nodes)

        if self.truncated:
            nodes.append(
                {
                    "level": "warning",
                    "title": f"... {self.truncated} more",
                    "detail": "",
                    "children": [],
                }
            )

        return nodes

    def for_page(self) -> list[dict[str, Any]]:
        """The tree as a template draws it: each node's shown level, and
        for a section its counts and whether it starts open."""

        def walk(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
            drawn = []

            for node in nodes:
                children = node.get("children") or []
                shown = node_level(node)
                drawn.append(
                    {
                        **node,
                        "shown": shown,
                        "children": walk(children),
                        "counts": (
                            describe_counts(count_levels(children), "")
                            if children
                            else ""
                        ),
                        "open": shown in ("warning", "error"),
                    }
                )

            return drawn

        return walk(self.as_list())

    def as_client(self, message: Any = "") -> dict[str, Any]:
        """What an action or a view answers: a headline and the tree."""
        return {
            "message": str(
                message or self.title or describe_counts(self.counts())
            ),
            "level": self.level,
            "report": self.as_list(),
            "counts": self.counts(),
        }


def describe_exception(error: BaseException) -> str:
    """The exception's own line: what a reader can act on."""
    return "".join(traceback.format_exception_only(type(error), error)).strip()


def _size(nodes: list[dict[str, Any]]) -> int:
    return sum(1 + _size(node.get("children") or []) for node in nodes)


def _safe_url(url: Any) -> bool:
    """A site path or an http(s) address: what a line may link to."""
    if not isinstance(url, str) or not url:
        return False

    if url.startswith("/") and not url.startswith("//"):
        return True

    return url.startswith(("https://", "http://"))

"""Which units of work a block of code wrote.

An undo puts back what one action did, and the history already holds
it: every version carries the batch - the unit of work - it was written
in. What the history does not know is which batches belong to the
action a person just ran: a bulk action may open a block of its own
(``acting_as``) inside the request's. :func:`capture` notes every batch
the recorder writes a version in while it is open::

    with capture() as captured:
        resource.delete_model(request, obj)

    captured.batches            # {"3f2a..."}

Kept apart from :mod:`generic.history.undo` so the recorder can tell it
without importing what an undo needs.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class Captured:
    """The batches written in while a :func:`capture` block ran."""

    batches: set[str] = field(default_factory=set)


_captured: ContextVar[tuple[Captured, ...]] = ContextVar(
    "generic_history_captured",
    default=(),
)


@contextmanager
def capture() -> Iterator[Captured]:
    """Note the batches every version written in this block belongs to.

    Blocks nest: an outer one hears of what an inner one heard.
    """
    captured = Captured()
    token = _captured.set((*_captured.get(), captured))

    try:
        yield captured
    finally:
        _captured.reset(token)


def noticed(batch: str) -> None:
    """Tell every open :func:`capture` block that ``batch`` was written
    in. Called by the recorder for each version it writes or folds."""
    if not batch:
        return

    for captured in _captured.get():
        captured.batches.add(batch)


__all__ = ["Captured", "capture", "noticed"]

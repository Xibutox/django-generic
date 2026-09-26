"""Who is changing things, where no request can be passed.

History is written from the model signals, which know the record and
nothing about the person: by then the request is three frames up, or
there is no request at all. The acting user is therefore ambient - a
context variable, set for the length of a request by
:class:`generic.middleware.CurrentUserMiddleware` and for the length of
a block by :func:`acting_as`::

    with acting_as(request.user, source="Import"):
        ...

A context variable, not a thread local: it is copied into each task of
an event loop, so an ASGI server handling two requests at once keeps
them apart, and a thread pool does too.

Each actor carries a **batch** - the unit of work. Several saves of the
same record inside one request are one change, and the recorder folds
them into one entry instead of writing a version each. Outside any
block every save gets a batch of its own, which is the safe default:
unrelated saves are never merged.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

from django.utils.encoding import force_str

#: How the user's name is stored on an entry, so it still reads as
#: something after the account is gone.
LABEL_LENGTH = 200


@dataclass(frozen=True)
class Actor:
    """Who is acting, and what one piece of their work is called.

    ``user`` is held as it was handed over - a request's user is a lazy
    object, and resolving it here would cost a query on every request,
    including the ones that write nothing. It is resolved once, when
    something is actually recorded.
    """

    user: Any = None
    source: str = ""
    batch: str = ""

    def person(self) -> Any:
        """The user, if there is one signed in. ``None`` otherwise."""
        if self.user is None or not getattr(
            self.user, "is_authenticated", False
        ):
            return None

        return self.user

    @property
    def label(self) -> str:
        person = self.person()

        return force_str(person)[:LABEL_LENGTH] if person is not None else ""


_actor: ContextVar[Actor | None] = ContextVar(
    "generic_history_actor",
    default=None,
)


def new_batch() -> str:
    return uuid.uuid4().hex


def current_actor() -> Actor:
    """Who is acting now. A fresh batch when nobody said."""
    actor = _actor.get()

    if actor is not None:
        return actor

    # No block and no request: this save stands alone, so it gets a
    # batch nothing else can share and never folds into an earlier
    # entry.
    return Actor(batch=new_batch())


def set_actor(user: Any = None, source: str = "") -> Any:
    """Start acting as somebody. Returns the token to reset with."""
    return _actor.set(
        Actor(user=user, source=str(source or ""), batch=new_batch())
    )


def reset_actor(token: Any) -> None:
    try:
        _actor.reset(token)
    except ValueError:  # pragma: no cover - reset in another context
        _actor.set(None)


@contextmanager
def acting_as(user: Any = None, source: str = "") -> Iterator[Actor]:
    """Record everything saved in this block as done by ``user``."""
    token = set_actor(user, source)

    try:
        yield current_actor()
    finally:
        reset_actor(token)

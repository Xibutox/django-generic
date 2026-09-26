"""What the application knows how to run.

A task is declared once, like a resource: what it is called, who hears
about it, and through which channels. The declaration is what the
catalogue page lists, what the runner reads at each of its four steps,
and what a scheduled row points at.

Declaring does not choose *when*: that is a schedule
(``django_celery_beat``) or somebody pressing the button.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Callable, Iterable, Sequence

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

#: Where a message about a run can go, and which of those deliver
#: something. Shared with the watch module through
#: :mod:`generic.delivery`, so the two features name the same things
#: alike: ``page`` is the run's own page, which holds it all anyway.
from generic.delivery import ALL, CHANNELS  # noqa: F401 (re-exported)

logger = logging.getLogger(__name__)

#: Who hears about a run. A callable takes the run and returns users.
AUDIENCES = ("trigger", "staff", "superusers", "everyone")


def check_channels(channels: Iterable[str], field: str) -> tuple[str, ...]:
    """Channel names, refused early rather than at three in the morning."""
    if isinstance(channels, str):
        channels = (channels,)

    chosen = tuple(channels)

    for channel in chosen:
        if channel not in CHANNELS:
            # "event" was one before 1.0.0: a notification now reaches
            # the pages its reader has open by itself.
            hint = (
                " A notification already reaches the pages its reader "
                "has open."
                if channel == "event"
                else ""
            )
            raise ImproperlyConfigured(
                f"{field}: unknown channel {channel!r}. "
                f"Choose from {', '.join(CHANNELS)}.{hint}"
            )

    return chosen


@dataclasses.dataclass(frozen=True)
class TaskDefinition:
    """One task the application offers, and how it reports."""

    #: The name Celery and a schedule both use. Dotted, by convention
    #: the function's own import path.
    name: str
    function: Callable[..., Any]
    label: str = ""
    description: str = ""
    icon: str = "bolt"
    #: Step 1: who is told the run is starting, and how.
    announce: tuple[str, ...] = ("notification",)
    #: Step 4: who is told how it went, and how.
    report: tuple[str, ...] = ("notification",)
    audience: Any = "trigger"
    #: What a user needs to start this one by hand. Empty means the
    #: permission to run tasks at all.
    permission: str = ""
    #: The Celery task, when Celery is installed. ``None`` means every
    #: run happens in the process that asked for it.
    celery_task: Any = None

    @property
    def title(self) -> str:
        return str(self.label or self.name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.title,
            "description": str(self.description or ""),
            "icon": self.icon,
            "announce": list(self.announce),
            "report": list(self.report),
            "queued": self.celery_task is not None,
        }


class TaskRegistry:
    """Every declared task, by name."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskDefinition] = {}

    def register(self, definition: TaskDefinition) -> TaskDefinition:
        existing = self._tasks.get(definition.name)

        if (
            existing is not None
            and existing.function is not definition.function
        ):
            # Two tasks under one name would make a schedule ambiguous:
            # the row names the task, and nothing else tells them apart.
            raise ImproperlyConfigured(
                f"Two tasks are called {definition.name!r}. "
                "Give one of them its own name."
            )

        self._tasks[definition.name] = definition

        return definition

    def unregister(self, name: str) -> None:
        self._tasks.pop(name, None)

    def get(self, name: str) -> TaskDefinition | None:
        return self._tasks.get(name)

    def all(self) -> Sequence[TaskDefinition]:
        """Every task, by label, so a page can list them in order."""
        return sorted(
            self._tasks.values(), key=lambda task: task.title.lower()
        )

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tasks))

    def choices(self) -> list[tuple[str, str]]:
        return [(task.name, task.title) for task in self.all()]


#: The registry the whole application shares.
registry = TaskRegistry()


def get_task(name: str) -> TaskDefinition:
    """The declared task, or a plain error naming what is registered."""
    definition = registry.get(name)

    if definition is None:
        known = ", ".join(registry.names()) or str(_("none"))

        raise LookupError(f"No task is called {name!r}. Registered: {known}.")

    return definition

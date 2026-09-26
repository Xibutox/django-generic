"""Topic registry.

A client may ask to subscribe to a topic - a table that should refresh
itself, a record somebody else is editing. Letting it name any group
would let it read anyone's stream, so a topic only exists once the
project has declared it, together with the rule saying who may listen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

#: Channels rejects group names outside this alphabet.
TOPIC_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

#: ``(user, topic_name, parameters) -> bool``
PermissionCheck = Callable[[Any, str, dict[str, str]], bool]


def allow_authenticated(
    user: Any,
    topic: str,
    parameters: dict[str, str],
) -> bool:
    return bool(user and getattr(user, "is_authenticated", False))


def allow_staff(
    user: Any,
    topic: str,
    parameters: dict[str, str],
) -> bool:
    return allow_authenticated(user, topic, parameters) and bool(
        getattr(user, "is_staff", False)
    )


@dataclass(frozen=True)
class Topic:
    """A named stream clients may subscribe to."""

    name: str
    #: Decides whether a given user may join. Defaults to "any signed in
    #: user", which is the weakest rule worth having - override it for
    #: anything a user should not see wholesale.
    permission: PermissionCheck = allow_authenticated
    description: str = ""
    #: Placeholders in the name, as in ``project.{project_id}``.
    parameters: tuple[str, ...] = field(default_factory=tuple)

    def group_name(self, parameters: dict[str, str] | None = None) -> str:
        parameters = parameters or {}
        missing = set(self.parameters) - set(parameters)

        if missing:
            raise ValueError(
                f"Topic '{self.name}' needs parameters: "
                f"{', '.join(sorted(missing))}."
            )

        name = self.name.format(
            **{key: parameters[key] for key in self.parameters}
        )

        if not TOPIC_NAME_PATTERN.match(name):
            raise ValueError(
                f"'{name}' is not a valid topic name. Allowed "
                f"characters: letters, digits, dot, dash, underscore."
            )

        return f"generic.topic.{name}"

    def allows(self, user: Any, parameters: dict[str, str]) -> bool:
        return bool(self.permission(user, self.name, parameters))


class TopicRegistry:
    """Process wide map of declared topics."""

    def __init__(self) -> None:
        self._topics: dict[str, Topic] = {}

    def register(
        self,
        name: str,
        *,
        permission: PermissionCheck = allow_authenticated,
        description: str = "",
        parameters: tuple[str, ...] = (),
    ) -> Topic:
        placeholders = tuple(re.findall(r"\{(\w+)\}", name))

        if placeholders and not parameters:
            parameters = placeholders

        topic = Topic(
            name=name,
            permission=permission,
            description=description,
            parameters=parameters,
        )

        existing = self._topics.get(name)

        if existing is not None and existing != topic:
            raise ValueError(
                f"Topic '{name}' is already registered with a different "
                f"configuration."
            )

        self._topics[name] = topic

        return topic

    def unregister(self, name: str) -> None:
        """Forget a topic. Unknown names are ignored."""
        self._topics.pop(name, None)

    def get(self, name: str) -> Topic | None:
        return self._topics.get(name)

    def resolve(
        self,
        name: str,
    ) -> tuple[Topic, dict[str, str]] | None:
        """Match a concrete name against the registered patterns.

        ``project.12`` resolves to the ``project.{project_id}`` topic
        with ``{"project_id": "12"}``.
        """
        topic = self._topics.get(name)

        if topic is not None and not topic.parameters:
            return topic, {}

        for candidate in self._topics.values():
            if not candidate.parameters:
                continue

            pattern = re.escape(candidate.name)

            for parameter in candidate.parameters:
                pattern = pattern.replace(
                    re.escape("{" + parameter + "}"),
                    f"(?P<{parameter}>[A-Za-z0-9_-]+)",
                )

            match = re.fullmatch(pattern, name)

            if match:
                return candidate, match.groupdict()

        return None

    def clear(self) -> None:
        """Drop every registration. Intended for tests."""
        self._topics.clear()

    def __iter__(self) -> Iterator[Topic]:
        return iter(self._topics.values())

    def __len__(self) -> int:
        return len(self._topics)


registry = TopicRegistry()


def register_topic(
    name: str,
    *,
    permission: PermissionCheck = allow_authenticated,
    description: str = "",
    parameters: tuple[str, ...] = (),
) -> Topic:
    """Declare a topic clients may subscribe to."""
    return registry.register(
        name,
        permission=permission,
        description=description,
        parameters=parameters,
    )

"""Tags: values drawn as small coloured labels.

A tag is a label with at most two colours, read from whatever the value
is - a related record, a choice, a dict a method returned::

    # One colour: the tag is tinted with it, and follows the theme.
    TagStyle(color="color")

    # A background: drawn exactly, with a readable text colour when
    # none is given.
    TagStyle(background="background", color="text_color")

    # Fixed colours by value, for a choice field.
    TagStyle(colors={"urgent": "#dc2626", "low": "#64748b"})

Colours reach an inline ``style`` in the browser, so every one is
checked against :data:`COLOR_PATTERN` on its way out; anything else is
dropped rather than risk a CSS injection.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Callable, Iterable, Mapping, Union

from django.db import models
from django.utils.encoding import force_str

#: A CSS colour, and nothing else: a hex value, a named colour, or one
#: of the colour functions with plain numeric arguments.
COLOR_PATTERN = re.compile(
    r"^(?:"
    r"#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})"
    r"|[a-z]{3,30}"
    r"|(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\([0-9a-z .,%/+-]{1,80}\)"
    r")$",
    re.IGNORECASE,
)

#: An attribute name, or a callable taking the value.
Reader = Union[str, Callable[[Any], Any], None]


def clean_color(value: Any) -> str | None:
    """``value`` when it is a CSS colour, ``None`` otherwise."""
    if value is None:
        return None

    text = force_str(value).strip()

    if not text or not COLOR_PATTERN.match(text):
        return None

    return text


def read(item: Any, reader: Reader) -> Any:
    """An attribute of ``item``, or what a callable makes of it."""
    if reader is None:
        return None

    if callable(reader):
        return reader(item)

    if isinstance(item, Mapping):
        return item.get(reader)

    value = getattr(item, reader, None)

    return value() if callable(value) else value


def json_key(value: Any) -> Any:
    """A key a JSON payload can carry: a number or a string."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    return force_str(value)


@dataclasses.dataclass(frozen=True)
class TagStyle:
    """How the values of a column or a field are drawn as tags.

    Each of ``label``, ``color``, ``background`` and ``title`` names an
    attribute of the value - of the related record, usually - or is a
    callable taking the value. ``colors`` gives fixed colours by value
    (or by label): a colour string, or ``{"color", "background"}``.
    """

    #: The text of the tag. Defaults to the value's ``str()``, or the
    #: label of a choice.
    label: Reader = None
    #: The text colour; alone, the colour the tag is tinted with.
    color: Reader = None
    #: The background colour: the tag is then drawn exactly.
    background: Reader = None
    #: A tooltip.
    title: Reader = None
    #: Fixed colours by value or label.
    colors: Mapping[Any, Any] | None = None
    #: The colour of a tag nothing else gives one to.
    default: Any = None

    def mapped(self, *keys: Any) -> Any:
        if not self.colors:
            return None

        for key in keys:
            if key is None:
                continue

            for candidate in (key, force_str(key)):
                if candidate in self.colors:
                    return self.colors[candidate]

        return None

    def describe(self, item: Any, label: Any = None) -> dict[str, Any] | None:
        """One tag, as the client draws it, or ``None`` for no value.

        ``{"label": "Billing", "id": 3, "color": "#1d4ed8"}``
        """
        if item is None or item == "":
            return None

        key: Any = None
        title: Any = None

        if isinstance(item, Mapping):
            key = item.get("id", item.get("key"))
            label = item.get("label", label)
            color = item.get("color")
            background = item.get("background")
            title = item.get("title")
        else:
            if isinstance(item, models.Model):
                key = item.pk
            else:
                key = item

            color = read(item, self.color)
            background = read(item, self.background)
            title = read(item, self.title)
            label = read(item, self.label) or label

        if label is None or label == "":
            label = item if not isinstance(item, Mapping) else key

        text = force_str(label)

        if not (color or background):
            fixed = self.mapped(key, text)

            if fixed is None:
                fixed = self.default

            if isinstance(fixed, Mapping):
                color = fixed.get("color")
                background = fixed.get("background")
            else:
                color = fixed

        tag: dict[str, Any] = {"label": text}

        if isinstance(item, models.Model) or (
            isinstance(item, Mapping) and key is not None
        ):
            tag["id"] = json_key(key)

        color = clean_color(color)
        background = clean_color(background)

        if color:
            tag["color"] = color

        if background:
            tag["background"] = background

        if title:
            tag["title"] = force_str(title)

        return tag

    def describe_all(
        self,
        items: Iterable[Any],
        labels: Mapping[Any, Any] | None = None,
    ) -> list[dict[str, Any]]:
        tags = []

        for item in items:
            label = None

            if labels and not isinstance(item, (models.Model, Mapping)):
                label = labels.get(item, labels.get(force_str(item)))

            tag = self.describe(item, label)

            if tag is None:
                continue

            # A choice keeps its key beside its label: a grid starts its
            # control from it, and the label alone is the translated
            # word, not the value.
            if labels and not isinstance(item, (models.Model, Mapping)):
                tag["value"] = json_key(item)

            tags.append(tag)

        return tags


def tag_items(value: Any) -> list[Any]:
    """The values a tag column draws: a manager, a list, or one value."""
    if value is None:
        return []

    if hasattr(value, "all") and callable(value.all):
        return list(value.all())

    if isinstance(value, (list, tuple, set, frozenset, models.QuerySet)):
        return list(value)

    return [value]


def tags_text(tags: Iterable[Mapping[str, Any]]) -> str:
    """Tags as plain text, for an export or a copy."""
    return ", ".join(force_str(tag.get("label", "")) for tag in tags)

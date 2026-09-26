"""The dashboard's hub: the few places worth going first.

A shortcut is a card at the top of the dashboard pointing at whatever
matters most - a filtered list, a page of the project's own, or
something outside the application entirely::

    site.add_shortcut(
        _("Open tickets"),
        route="site:example_ticket_list",
        icon="confirmation_number",
        description=_("Everything the desk has not answered yet."),
        count=lambda request: Ticket.objects.filter(status="open").count(),
    )

    site.add_shortcut(
        _("Weekly report"),
        url="https://reports.example.test/weekly",
        icon="bar_chart",
        group=_("Elsewhere"),
    )

Three things a link list does not do, and the reason this is a
declaration rather than HTML in a template:

* **It obeys permissions.** Same rule as a navigation link: a
  permission string, several of them, a callable, or nothing for any
  signed-in user. What a reader may not open does not appear.
* **It can carry a figure.** ``count`` is a value or a
  ``callable(request)``, shown as a badge - which is what makes the
  hub worth reading rather than merely clicking.
* **The address is checked.** A shortcut's URL comes from a
  declaration, and a declaration is written by hand: one that is not a
  page or a plain web address raises rather than reaching the browser
  as a link.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch, reverse
from django.utils.encoding import force_str

#: Schemes a shortcut may point at. Everything else - ``javascript:``
#: above all - is refused: these end up in an href.
SAFE_SCHEMES = frozenset({"http", "https", "mailto", "tel"})

#: Characters a browser ignores inside a scheme, and an attacker uses
#: to hide one. Removed before the address is read.
_IGNORED = re.compile(r"[\x00-\x20\x7f]")


def clean_url(value: Any, label: Any = "") -> str:
    """The address of a shortcut, or a refusal naming it.

    Relative addresses pass - they are this application's own pages.
    An absolute one has to be something a browser opens as a document.
    """
    url = _IGNORED.sub("", force_str(value or ""))

    if not url:
        return ""

    scheme = urlparse(url).scheme.lower()

    if scheme and scheme not in SAFE_SCHEMES:
        raise ImproperlyConfigured(
            f"The shortcut {force_str(label)!r} points at "
            f"'{scheme}:', which is not an address a browser opens. "
            f"Use a path of this site, or "
            f"{', '.join(sorted(SAFE_SCHEMES))}."
        )

    return url


@dataclasses.dataclass
class Shortcut:
    """One card of the dashboard's hub."""

    label: Any
    url: str = ""
    route: str = ""
    route_args: tuple[Any, ...] = ()
    icon: str = "arrow_forward"
    description: Any = ""
    #: Heading this shortcut is filed under. Empty is the first block,
    #: which has no heading of its own.
    group: Any = ""
    order: int = 0
    #: A permission string, an iterable of them, ``callable(user)``, or
    #: ``None`` for any signed-in user.
    permission: Any = None
    #: A figure beside the label: a value, or ``callable(request)``.
    count: Any = None
    #: Opens in a new tab. ``None`` decides from the address, which is
    #: what a reader expects: this application's pages here, the rest
    #: over there.
    external: bool | None = None

    def resolve_url(self) -> str:
        if self.url:
            return clean_url(self.url, self.label)

        if not self.route:
            return ""

        try:
            return reverse(self.route, args=self.route_args or None)
        except NoReverseMatch:
            # A route of an application that is not installed here.
            # The shortcut goes quiet rather than taking the page down.
            return ""

    def is_external(self, url: str) -> bool:
        if self.external is not None:
            return bool(self.external)

        return bool(urlparse(url).scheme or url.startswith("//"))

    def is_visible(self, user: Any) -> bool:
        if user is None or not user.is_authenticated:
            return False

        if self.permission is None or self.permission is True:
            return True

        if callable(self.permission):
            return bool(self.permission(user))

        if isinstance(self.permission, str):
            return user.has_perm(self.permission)

        return all(user.has_perm(item) for item in self.permission)

    def resolve_count(self, request: Any) -> str:
        """The badge, as text. A figure nobody can compute is no badge."""
        if self.count is None:
            return ""

        value = self.count

        if callable(value):
            try:
                value = value(request)
            except Exception:  # pragma: no cover - a project's callable
                return ""

        return "" if value is None else force_str(value)

    def as_entry(self, request: Any) -> dict[str, Any]:
        url = self.resolve_url()

        return {
            "label": force_str(self.label),
            "description": force_str(self.description or ""),
            "icon": self.icon or "arrow_forward",
            "url": url,
            "external": self.is_external(url),
            "count": self.resolve_count(request),
            "group": force_str(self.group or ""),
            "order": self.order,
        }


#: What a shortcut declared in ``GENERIC["SHORTCUTS"]`` may say. The
#: same names as the dataclass, because the two are the same thing
#: written in two places.
SETTING_KEYS = frozenset(
    {
        "label",
        "url",
        "route",
        "route_args",
        "icon",
        "description",
        "group",
        "order",
        "permission",
        "count",
        "external",
    }
)


def from_setting(entries: Any) -> list[Shortcut]:
    """``GENERIC["SHORTCUTS"]`` as shortcuts.

    A typo here would otherwise be a card that silently never appears,
    so an unknown key is an error rather than a shrug.
    """
    shortcuts = []

    for entry in entries or ():
        if not isinstance(entry, dict):
            raise ImproperlyConfigured(
                "GENERIC['SHORTCUTS'] holds entries that are not "
                "objects. Each one is a dict with at least a label."
            )

        unknown = set(entry) - SETTING_KEYS

        if unknown:
            raise ImproperlyConfigured(
                f"GENERIC['SHORTCUTS'] entry "
                f"{entry.get('label', '?')!r} has no key "
                f"{', '.join(sorted(unknown))}. Known keys: "
                f"{', '.join(sorted(SETTING_KEYS))}."
            )

        if not entry.get("label"):
            raise ImproperlyConfigured(
                "Every entry of GENERIC['SHORTCUTS'] needs a label."
            )

        shortcuts.append(Shortcut(**entry))

    return shortcuts


def group_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cards, in blocks, in the order their headings first appear.

    The ungrouped ones come first: a hub with one block is the common
    case, and it should not need a heading to say so.
    """
    blocks: dict[str, dict[str, Any]] = {}

    for entry in sorted(
        entries, key=lambda item: (item["order"], item["label"])
    ):
        block = blocks.setdefault(
            entry["group"],
            {"title": entry["group"], "items": []},
        )
        block["items"].append(entry)

    ordered = sorted(blocks, key=lambda title: (title != "",))

    return [blocks[title] for title in ordered]


__all__ = [
    "SAFE_SCHEMES",
    "Shortcut",
    "clean_url",
    "from_setting",
    "group_entries",
]

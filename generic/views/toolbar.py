"""Page chrome primitives: toolbar buttons and breadcrumbs.

Both are plain dataclasses rather than template fragments, so a view can
build them in Python, test them without rendering, and a project can
subclass a view and adjust one entry without copying a template.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from django.urls import NoReverseMatch, reverse
from django.utils.encoding import force_str

#: Visual variants understood by the stylesheet.
VARIANTS = frozenset(
    {"default", "primary", "danger", "danger-ghost", "ghost", "link"}
)

#: Where a button goes when the toolbar runs out of room.
#:
#: ``auto``  in the bar while there is room, in the *More* menu after -
#:           the default, except for a primary button;
#: ``bar``   always in the bar - the default of a primary button;
#: ``menu``  always in the *More* menu, whatever the room.
PLACEMENTS = frozenset({"auto", "bar", "menu"})


@dataclasses.dataclass(frozen=True)
class Breadcrumb:
    """One step in the trail above the page title."""

    label: str
    url: str = ""

    @property
    def is_link(self) -> bool:
        return bool(self.url)


@dataclasses.dataclass(frozen=True)
class ToolbarItem:
    """A button in the page toolbar.

    ``permission`` may be a permission string, an iterable of them, or a
    boolean. It is evaluated against the user by :meth:`is_visible`, so a
    view can list every possible action and let the user's rights decide
    what actually shows.
    """

    url: str
    label: str
    icon: str = ""
    variant: str = "default"
    target: str = "_self"
    permission: Any = True
    disabled: bool = False
    title: str = ""
    #: Extra CSS classes, for a project-specific button.
    css_class: str = ""
    #: One of :data:`PLACEMENTS`.
    placement: str = "auto"

    def __post_init__(self) -> None:
        if self.variant not in VARIANTS:
            raise ValueError(
                f"Unknown toolbar variant '{self.variant}'. "
                f"Expected one of: {', '.join(sorted(VARIANTS))}."
            )

        if self.placement not in PLACEMENTS:
            raise ValueError(
                f"Unknown toolbar placement '{self.placement}'. "
                f"Expected one of: {', '.join(sorted(PLACEMENTS))}."
            )

    @property
    def pinned(self) -> bool:
        """Whether the button stays in the bar however narrow it gets.

        A primary button is the page's main action: folding it away to
        make room for a secondary link would be the wrong way round.
        """
        if self.placement == "auto":
            return self.variant == "primary"

        return self.placement == "bar"

    @property
    def is_danger(self) -> bool:
        return self.variant in ("danger", "danger-ghost")

    def is_visible(self, user: Any) -> bool:
        """Whether ``user`` may see this button."""
        if self.permission is True:
            return True

        if self.permission is False or self.permission is None:
            return False

        if user is None or not user.is_authenticated:
            return False

        if isinstance(self.permission, str):
            return user.has_perm(self.permission)

        return all(user.has_perm(permission) for permission in self.permission)

    @property
    def css_classes(self) -> str:
        classes = ["toolbar-item", f"toolbar-item--{self.variant}"]

        if self.icon:
            classes.append(f"toolbar-item--icon-{self.icon}")

        if self.disabled:
            classes.append("is-disabled")

        if self.css_class:
            classes.append(self.css_class)

        return " ".join(classes)


@dataclasses.dataclass(frozen=True)
class ToolbarSlot:
    """A button and its place in the list, which pairs it with its
    copy in the *More* menu."""

    index: int
    item: ToolbarItem


@dataclasses.dataclass(frozen=True)
class ToolbarLayout:
    """A toolbar split around its *More* menu.

    ``lead`` is drawn before the menu's button and ``trail`` after it:
    the pinned buttons that end the list, the primary one above all,
    keep the end of the bar however many buttons fold before them.
    ``menu`` holds every button that may end up in the menu, in the
    order of the list.
    """

    lead: tuple[ToolbarSlot, ...]
    trail: tuple[ToolbarSlot, ...]
    menu: tuple[ToolbarSlot, ...]

    @property
    def folds(self) -> bool:
        """Whether there is anything a *More* menu could hold."""
        return bool(self.menu)

    @property
    def menu_only(self) -> bool:
        """Whether the menu holds something whatever the room."""
        return any(slot.item.placement == "menu" for slot in self.menu)


def layout_toolbar(items: Any) -> ToolbarLayout:
    """Split toolbar items into the bar, the *More* menu and the end.

    Which of the foldable buttons actually fold is decided in the
    browser, by measuring: only it knows how wide the bar is. This
    decides everything that does not depend on the width.
    """
    slots = [ToolbarSlot(index, item) for index, item in enumerate(items)]
    cut = len(slots)

    while cut and slots[cut - 1].item.pinned:
        cut -= 1

    return ToolbarLayout(
        lead=tuple(
            slot for slot in slots[:cut] if slot.item.placement != "menu"
        ),
        trail=tuple(slots[cut:]),
        menu=tuple(slot for slot in slots if not slot.item.pinned),
    )


def toolbar_item_for_route(
    route: str,
    label: str,
    *,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    fallback: str = "",
    **options: Any,
) -> ToolbarItem | None:
    """Build a toolbar item from a named route.

    Returns ``None`` when the route cannot be reversed, so a view can
    offer an optional action without the page failing on a project that
    never registered it.
    """
    try:
        url = reverse(route, args=args, kwargs=kwargs or None)
    except NoReverseMatch:
        if not fallback:
            return None

        url = fallback

    return ToolbarItem(url=url, label=force_str(label), **options)

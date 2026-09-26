"""Toolbar items and their permission rules."""

from __future__ import annotations

import pytest

from generic.views import ToolbarItem, toolbar_item_for_route

pytestmark = pytest.mark.django_db


class AnonymousUser:
    is_authenticated = False

    def has_perm(self, permission):  # pragma: no cover - never reached
        return True


class TestVisibility:
    def test_an_item_without_a_rule_is_always_visible(self, user):
        item = ToolbarItem(url="/x/", label="X")

        assert item.is_visible(user) is True
        assert item.is_visible(AnonymousUser()) is True

    def test_permission_false_hides_it(self, user):
        item = ToolbarItem(url="/x/", label="X", permission=False)

        assert item.is_visible(user) is False

    def test_a_permission_string_is_checked(self, user):
        from django.contrib.auth.models import Permission

        item = ToolbarItem(
            url="/x/",
            label="X",
            permission="testapp.add_book",
        )

        assert item.is_visible(user) is False

        user.user_permissions.add(Permission.objects.get(codename="add_book"))
        user = type(user).objects.get(pk=user.pk)

        assert item.is_visible(user) is True

    def test_several_permissions_must_all_hold(self, user):
        from django.contrib.auth.models import Permission

        item = ToolbarItem(
            url="/x/",
            label="X",
            permission=["testapp.add_book", "testapp.delete_book"],
        )

        user.user_permissions.add(Permission.objects.get(codename="add_book"))
        user = type(user).objects.get(pk=user.pk)

        assert item.is_visible(user) is False

    def test_an_anonymous_user_fails_any_permission(self):
        item = ToolbarItem(
            url="/x/",
            label="X",
            permission="testapp.add_book",
        )

        assert item.is_visible(AnonymousUser()) is False


class TestCssClasses:
    def test_the_variant_becomes_a_class(self):
        item = ToolbarItem(url="/x/", label="X", variant="danger")

        assert "toolbar-item--danger" in item.css_classes

    def test_a_disabled_item_says_so(self):
        item = ToolbarItem(url="/x/", label="X", disabled=True)

        assert "is-disabled" in item.css_classes

    def test_an_unknown_variant_is_refused(self):
        """A typo here would silently render an unstyled button."""
        with pytest.raises(ValueError, match="Unknown toolbar variant"):
            ToolbarItem(url="/x/", label="X", variant="fancy")


def items(*specs):
    """``("Label", variant, placement)`` tuples, as toolbar items."""
    return [
        ToolbarItem(
            url=f"/{label.lower()}/",
            label=label,
            variant=variant,
            placement=placement,
        )
        for label, variant, placement in specs
    ]


def labels(slots):
    return [slot.item.label for slot in slots]


class TestPlacement:
    def test_a_button_folds_by_default(self):
        assert ToolbarItem(url="/x/", label="X").pinned is False

    def test_the_primary_button_does_not(self):
        """The page's main action is the last thing to fold away."""
        item = ToolbarItem(url="/x/", label="X", variant="primary")

        assert item.pinned is True

    def test_placement_overrides_the_variant(self):
        primary = ToolbarItem(
            url="/x/",
            label="X",
            variant="primary",
            placement="menu",
        )
        ghost = ToolbarItem(url="/x/", label="X", placement="bar")

        assert primary.pinned is False
        assert ghost.pinned is True

    def test_an_unknown_placement_is_refused(self):
        with pytest.raises(ValueError, match="Unknown toolbar placement"):
            ToolbarItem(url="/x/", label="X", placement="sidebar")


class TestLayout:
    def test_the_pinned_end_of_the_list_comes_after_the_menu(self):
        from generic.views.toolbar import layout_toolbar

        layout = layout_toolbar(
            items(
                ("Hours", "ghost", "auto"),
                ("Delete", "danger-ghost", "auto"),
                ("Edit", "primary", "auto"),
            )
        )

        assert labels(layout.lead) == ["Hours", "Delete"]
        assert labels(layout.trail) == ["Edit"]
        assert labels(layout.menu) == ["Hours", "Delete"]

    def test_a_pinned_button_in_the_middle_keeps_its_place(self):
        """Only the pinned buttons that *end* the list move past the
        menu's button: one in the middle stays where it was put."""
        from generic.views.toolbar import layout_toolbar

        layout = layout_toolbar(
            items(
                ("Hours", "ghost", "auto"),
                ("Board", "ghost", "bar"),
                ("Status", "ghost", "auto"),
            )
        )

        assert labels(layout.lead) == ["Hours", "Board", "Status"]
        assert labels(layout.trail) == []
        assert labels(layout.menu) == ["Hours", "Status"]

    def test_a_menu_only_button_is_never_in_the_bar(self):
        from generic.views.toolbar import layout_toolbar

        layout = layout_toolbar(
            items(
                ("Hours", "ghost", "auto"),
                ("Audit", "ghost", "menu"),
                ("Edit", "primary", "auto"),
            )
        )

        assert labels(layout.lead) == ["Hours"]
        assert labels(layout.menu) == ["Hours", "Audit"]
        assert layout.menu_only is True

    def test_a_toolbar_of_pinned_buttons_has_nothing_to_fold(self):
        from generic.views.toolbar import layout_toolbar

        layout = layout_toolbar(items(("Add", "primary", "auto")))

        assert layout.folds is False
        assert labels(layout.trail) == ["Add"]

    def test_slots_keep_their_place_in_the_list(self):
        """The index pairs a button with its copy in the menu."""
        from generic.views.toolbar import layout_toolbar

        layout = layout_toolbar(
            items(
                ("Hours", "ghost", "auto"),
                ("Audit", "ghost", "menu"),
                ("Status", "ghost", "auto"),
            )
        )

        assert [slot.index for slot in layout.lead] == [0, 2]
        assert [slot.index for slot in layout.menu] == [0, 1, 2]


class TestRouteHelper:
    def test_it_reverses_a_known_route(self):
        item = toolbar_item_for_route("book-list-page", "Books")

        assert item is not None
        assert item.url == "/books/"

    def test_an_unknown_route_yields_nothing(self):
        """An optional action must not break a page that lacks it."""
        assert toolbar_item_for_route("nope", "Nope") is None

    def test_a_fallback_is_used_when_given(self):
        item = toolbar_item_for_route("nope", "Nope", fallback="/x/")

        assert item is not None
        assert item.url == "/x/"

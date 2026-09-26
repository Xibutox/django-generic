"""Template helpers."""

from __future__ import annotations

import re

import pytest
from django.template import Context, Template

from generic.templatetags.generic_tags import (
    message_icon,
    ordering_url,
    query_replace,
)
from generic.views import Breadcrumb, ToolbarItem


def render(template: str, context: dict) -> str:
    return Template("{% load generic_tags %}" + template).render(
        Context(context)
    )


class TestQueryReplace:
    def test_it_keeps_the_other_parameters(self, rf):
        context = {"request": rf.get("/?q=emma&page=2")}
        result = query_replace(context, page=3)

        assert "q=emma" in result
        assert "page=3" in result

    def test_none_removes_a_parameter(self, rf):
        context = {"request": rf.get("/?q=emma&page=2")}
        result = query_replace(context, page=None)

        assert "page" not in result

    def test_it_survives_a_missing_request(self):
        assert query_replace({}, page=2) == "page=2"


class TestOrderingUrl:
    def test_an_unsorted_column_sorts_ascending(self, rf):
        context = {"request": rf.get("/"), "ordering_state": {}}

        assert "o=title" in ordering_url(context, "title")

    def test_an_ascending_column_flips_to_descending(self, rf):
        context = {
            "request": rf.get("/?o=title"),
            "ordering_state": {"title": "asc"},
        }

        assert "o=-title" in ordering_url(context, "title")

    def test_a_descending_column_clears_the_ordering(self, rf):
        context = {
            "request": rf.get("/?o=-title"),
            "ordering_state": {"title": "desc"},
        }

        assert "o=" not in ordering_url(context, "title")

    def test_changing_the_sort_returns_to_the_first_page(self, rf):
        """Page 7 of a differently ordered list is meaningless."""
        context = {
            "request": rf.get("/?page=7"),
            "ordering_state": {},
        }

        assert "page" not in ordering_url(context, "title")


class TestOrderingIndicator:
    def test_an_unsorted_column_has_no_arrow(self, rf):
        rendered = render(
            "{% ordering_indicator 'title' %}",
            {"ordering_state": {}},
        )

        assert "\u2191" not in rendered
        assert "\u2193" not in rendered

    def test_an_ascending_column_shows_an_up_arrow(self):
        rendered = render(
            "{% ordering_indicator 'title' %}",
            {"ordering_state": {"title": "asc"}},
        )

        assert "\u2191" in rendered

    def test_a_descending_column_shows_a_down_arrow(self):
        rendered = render(
            "{% ordering_indicator 'title' %}",
            {"ordering_state": {"title": "desc"}},
        )

        assert "\u2193" in rendered


class TestMessageIcon:
    @pytest.mark.parametrize(
        "tags,expected",
        [
            ("error", "error"),
            ("warning", "warning"),
            ("success", "success"),
            ("debug", "info"),
            ("", "info"),
            (None, "info"),
        ],
    )
    def test_it_maps_django_levels(self, tags, expected):
        assert message_icon(tags) == expected


class TestFieldValue:
    def test_it_reads_a_mapping(self):
        rendered = render(
            "{{ row|field_value:'name' }}",
            {"row": {"name": "value"}},
        )

        assert rendered.strip() == "value"

    def test_it_reads_an_attribute(self):
        rendered = render(
            "{{ crumb|field_value:'label' }}",
            {"crumb": Breadcrumb(label="Books", url="/books/")},
        )

        assert rendered.strip() == "Books"


class TestToolbarRendering:
    def test_a_toolbar_item_renders_as_a_link(self):
        item = ToolbarItem(url="/add/", label="Add", variant="primary")
        rendered = render(
            '{% include "generic/components/toolbar.html" %}',
            {"toolbar_items": [item]},
        )

        assert 'href="/add/"' in rendered
        assert "toolbar-item--primary" in rendered

    def test_a_disabled_item_is_not_a_link(self):
        item = ToolbarItem(url="/add/", label="Add", disabled=True)
        rendered = render(
            '{% include "generic/components/toolbar.html" %}',
            {"toolbar_items": [item]},
        )

        assert 'href="/add/"' not in rendered
        assert 'aria-disabled="true"' in rendered

    def test_an_external_item_gets_rel_noopener(self):
        item = ToolbarItem(
            url="https://example.test",
            label="Docs",
            target="_blank",
        )
        rendered = render(
            '{% include "generic/components/toolbar.html" %}',
            {"toolbar_items": [item]},
        )

        assert 'rel="noopener"' in rendered


class TestFoldingToolbar:
    """What the server draws; which buttons fold is the browser's."""

    def toolbar(self, *items):
        return render(
            '{% include "generic/components/toolbar.html" %}',
            {"toolbar_items": list(items)},
        )

    def test_a_foldable_button_is_drawn_twice(self):
        """In the bar, and hidden in the menu until the bar is short of
        room: the browser swaps the two, it never builds either."""
        rendered = self.toolbar(
            ToolbarItem(url="/hours/", label="Hours"),
            ToolbarItem(url="/edit/", label="Edit", variant="primary"),
        )

        assert rendered.count('href="/hours/"') == 2
        assert 'data-toolbar-slot="0" data-foldable' in rendered
        assert 'data-toolbar-copy="0"' in rendered
        assert 'x-data="pageToolbar"' in rendered

    def test_the_primary_button_is_never_in_the_menu(self):
        rendered = self.toolbar(
            ToolbarItem(url="/hours/", label="Hours"),
            ToolbarItem(url="/edit/", label="Edit", variant="primary"),
        )

        assert rendered.count('href="/edit/"') == 1
        # After the menu's button, so it keeps the end of the bar.
        assert rendered.index("data-toolbar-more") < rendered.index(
            'href="/edit/"'
        )

    def test_the_menu_button_is_hidden_until_something_folds(self):
        rendered = self.toolbar(ToolbarItem(url="/hours/", label="Hours"))

        assert re.search(r"data-toolbar-more\s+hidden", rendered)

    def test_a_menu_only_button_shows_the_menu_from_the_start(self):
        rendered = self.toolbar(
            ToolbarItem(url="/audit/", label="Audit", placement="menu"),
        )

        assert rendered.count('href="/audit/"') == 1
        assert "data-menu-only" in rendered
        assert "data-toolbar-slot" not in rendered

    def test_a_danger_button_stays_one_in_the_menu(self):
        rendered = self.toolbar(
            ToolbarItem(
                url="/delete/", label="Delete", variant="danger-ghost"
            ),
        )

        assert "menu-item menu-item--danger" in rendered

    def test_nothing_to_fold_is_a_plain_toolbar(self):
        """A list page's Add button: no menu, no component."""
        rendered = self.toolbar(
            ToolbarItem(url="/add/", label="Add", variant="primary"),
        )

        assert "data-toolbar-more" not in rendered
        assert "x-data" not in rendered

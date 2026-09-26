"""Column declaration: what the client is told, and what it may filter."""

from __future__ import annotations

import pytest

from generic.api.columns import (
    CharColumn,
    ColumnOptions,
    DateColumn,
    IntegerColumn,
    prettify_field_name,
)
from generic.api.serializers import DataTableSerializer
from tests.testapp.serializers import (
    BookTableSerializer,
    HiddenPriceBookSerializer,
)


def columns_by_name(serializer_class) -> dict:
    return {
        column["data"]: column
        for column in serializer_class.get_datatable_columns()
    }


class TestColumnConfiguration:
    def test_title_falls_back_to_a_readable_field_name(self):
        class Serializer(DataTableSerializer):
            time_spent = IntegerColumn()

        columns = columns_by_name(Serializer)

        assert columns["time_spent"]["title"] == "Time spent"

    def test_declared_title_wins(self):
        columns = columns_by_name(BookTableSerializer)

        assert columns["pages"]["title"] == "Pages"

    def test_order_field_drives_the_column_name(self):
        columns = columns_by_name(BookTableSerializer)

        # ``data`` stays the public name the payload uses, ``name`` is
        # what ordering resolves against.
        assert columns["author"]["data"] == "author"
        assert columns["author"]["name"] == "author__name"

    def test_hidden_columns_are_still_sent(self):
        """A hidden column must reach the client to be revealable."""
        columns = columns_by_name(HiddenPriceBookSerializer)

        assert columns["price"]["visible"] is False

    def test_visible_columns_omit_the_flag(self):
        columns = columns_by_name(BookTableSerializer)

        assert "visible" not in columns["title"]

    def test_forced_filter_type_is_advertised(self):
        columns = columns_by_name(BookTableSerializer)

        assert columns["genre"]["filterType"] == "multiselect"

    def test_a_column_drawn_differently_says_how_it_filters(self):
        # A date column drawn as a link - the first column of a resource
        # opens its record - used to reach the client as a text filter,
        # whose "contains" the date engine refuses.
        class Serializer(DataTableSerializer):
            spent_on = DateColumn(display_type="link")

        columns = columns_by_name(Serializer)

        assert columns["spent_on"]["type"] == "link"
        assert columns["spent_on"]["filterType"] == "date"

    def test_the_filter_type_is_left_to_the_display_type_when_they_agree(
        self,
    ):
        columns = columns_by_name(BookTableSerializer)

        assert "filterType" not in columns["title"]
        assert "filterType" not in columns["pages"]

    def test_unset_options_are_omitted(self):
        columns = columns_by_name(BookTableSerializer)

        assert "linkUrl" not in columns["title"]
        assert "autocompleteUrl" not in columns["title"]

    def test_a_choice_column_sends_its_choices(self):
        """A fixed list needs no autocomplete route to be filterable."""
        columns = columns_by_name(BookTableSerializer)
        choices = columns["genre"]["choices"]

        assert {choice["value"] for choice in choices} == {
            "fiction",
            "essay",
            "poetry",
        }
        assert {choice["label"] for choice in choices} == {
            "Fiction",
            "Essay",
            "Poetry",
        }

    def test_a_plain_column_sends_no_choices(self):
        columns = columns_by_name(BookTableSerializer)

        assert "choices" not in columns["title"]


class TestColumnOrdering:
    def test_columns_keep_declaration_order_by_default(self):
        names = [
            column["data"]
            for column in BookTableSerializer.get_datatable_columns()
        ]

        assert names.index("title") < names.index("pages")

    def test_position_moves_a_column_without_redeclaring_it(self):
        names = [
            column["data"]
            for column in (HiddenPriceBookSerializer.get_datatable_columns())
        ]

        # ``pages`` was pushed to position -10 by the subclass.
        assert names[0] == "pages"


class TestOverrides:
    def test_overrides_merge_along_the_mro(self):
        overrides = HiddenPriceBookSerializer.get_merged_datatable_overrides()

        assert overrides["price"] == {"visible": False}
        assert overrides["pages"] == {"position": -10}

    def test_unknown_option_raises_instead_of_being_ignored(self):
        class Broken(BookTableSerializer):
            datatable_overrides = {"title": {"visibl": False}}

        with pytest.raises(TypeError, match="Known options"):
            Broken.get_datatable_columns()


class TestFilterSpecs:
    def test_only_filterable_columns_are_whitelisted(self):
        specs = BookTableSerializer.get_filter_specs()

        assert "title" in specs
        # A computed column has nothing to filter on.
        assert "slug" not in specs

    def test_filter_field_maps_to_the_orm_path(self):
        specs = BookTableSerializer.get_filter_specs()

        assert specs["author"].field == "author__name"

    def test_datetime_and_date_share_the_engine_not_the_value_type(self):
        specs = BookTableSerializer.get_filter_specs()

        assert specs["published_on"].type == "date"
        assert specs["published_on"].value_type == "date"

        assert specs["released_at"].type == "date"
        assert specs["released_at"].value_type == "datetime"


class TestOrderingFields:
    def test_orderable_columns_expose_their_orm_path(self):
        ordering = BookTableSerializer.get_ordering_fields()

        assert ordering["title"] == "title"
        assert ordering["author"] == "author__name"

    def test_non_orderable_columns_are_excluded(self):
        assert "slug" not in BookTableSerializer.get_ordering_fields()


class TestSearchFields:
    def test_only_text_columns_take_part_in_the_global_search(self):
        fields = BookTableSerializer.get_search_fields()

        assert "title" in fields
        assert "author__name" in fields
        # Searching a numeric column with icontains errors on Postgres.
        assert "pages" not in fields
        assert "published_on" not in fields

    def test_opting_out_removes_a_column_from_the_search(self):
        class Serializer(DataTableSerializer):
            title = CharColumn()
            secret = CharColumn(searchable=False)

        assert Serializer.get_search_fields() == ["title"]


class TestColumnOptions:
    def test_replace_rejects_unknown_options(self):
        with pytest.raises(TypeError, match="Known options"):
            ColumnOptions().replace(nope=True)

    def test_replace_returns_a_new_frozen_instance(self):
        options = ColumnOptions(title="A")
        updated = options.replace(title="B")

        assert options.title == "A"
        assert updated.title == "B"


def test_prettify_field_name():
    assert prettify_field_name("time_spent") == "Time spent"
    assert prettify_field_name("title") == "Title"

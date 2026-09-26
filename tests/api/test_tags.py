"""Tags: values drawn as coloured labels, and the column showing them."""

from __future__ import annotations

import pytest
from rest_framework import serializers

from generic.api import DataTableModelSerializer, TagsColumn, TagStyle
from generic.api.tags import clean_color, tags_text
from tests.testapp.models import Book


class TestCleanColor:
    @pytest.mark.parametrize(
        "value",
        [
            "#fff",
            "#1D4ED8",
            "#1d4ed880",
            "rebeccapurple",
            "rgb(20, 30, 40)",
            "rgba(20 30 40 / 50%)",
            "oklch(0.6 0.15 250)",
            "hsl(210deg 40% 50%)",
        ],
    )
    def test_a_css_colour_is_kept(self, value):
        assert clean_color(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "#12",
            "#12345",
            "red; background: url(https://evil.test/)",
            "url(javascript:alert(1))",
            "var(--x)",
            'red" onmouseover="alert(1)',
            "expression(alert(1))",
            "rgb(1,2,3);color:red",
        ],
    )
    def test_anything_else_is_dropped(self, value):
        # A colour ends up in a style attribute: only a colour gets there.
        assert clean_color(value) is None


class Label:
    """A stand-in for a record holding its own colours."""

    def __init__(self, name, color="", background="", pk=1):
        self.name = name
        self.color = color
        self.background = background
        self.pk = pk

    def __str__(self):
        return self.name


class TestTagStyle:
    def test_one_colour_read_from_the_value(self):
        style = TagStyle(color="color")

        assert style.describe(Label("billing", color="#1d4ed8")) == {
            "label": "billing",
            "color": "#1d4ed8",
        }

    def test_a_background_and_its_text(self):
        style = TagStyle(color="color", background="background")
        tag = style.describe(Label("vip", "#fff", "#7c3aed"))

        assert (tag["color"], tag["background"]) == ("#fff", "#7c3aed")

    def test_fixed_colours_by_value(self):
        style = TagStyle(
            colors={"urgent": {"background": "#dc2626", "color": "#fff"}}
        )

        assert style.describe("urgent", "Urgent") == {
            "label": "Urgent",
            "color": "#fff",
            "background": "#dc2626",
        }
        assert style.describe("low", "Low") == {"label": "Low"}

    def test_the_default_colours_what_nothing_else_does(self):
        style = TagStyle(color="color", default="#64748b")

        assert style.describe(Label("plain"))["color"] == "#64748b"

    def test_a_callable_reads_anything(self):
        style = TagStyle(
            label=lambda item: item.name.upper(),
            color=lambda item: "green",
            title="name",
        )

        assert style.describe(Label("ok")) == {
            "label": "OK",
            "color": "green",
            "title": "ok",
        }

    def test_a_dict_brings_its_own_colours(self):
        tag = TagStyle().describe(
            {"id": 4, "label": "Late", "color": "#b45309"}
        )

        assert tag == {"label": "Late", "id": 4, "color": "#b45309"}

    def test_an_unsafe_colour_is_left_out(self):
        tag = TagStyle(color="color").describe(
            Label("bad", color="red;position:fixed")
        )

        assert tag == {"label": "bad"}

    def test_no_value_no_tag(self):
        assert TagStyle().describe(None) is None
        assert TagStyle().describe("") is None


class BookTagsSerializer(DataTableModelSerializer):
    genre = TagsColumn(
        tag_style=TagStyle(colors={"essay": "#0891b2"}),
        choices=Book.Genre.choices,
        filter_type="multiselect",
    )
    flags = TagsColumn(
        source="*",
        reader=lambda book: [
            (
                {"label": "Available", "color": "#16a34a"}
                if book.is_available
                else None
            ),
            {"label": f"{book.pages} pages"},
        ],
        filterable=False,
        orderable=False,
    )
    title = serializers.CharField()

    class Meta:
        model = Book
        fields = ("id", "title", "genre", "flags")


@pytest.mark.django_db
class TestTagsColumn:
    def test_the_column_is_drawn_as_tags(self):
        columns = {
            column["data"]: column
            for column in BookTagsSerializer.get_datatable_columns()
        }

        assert columns["genre"]["type"] == "tags"
        assert columns["genre"]["filterType"] == "multiselect"
        # The choices feed the filter, as a choice column's do.
        assert {"value": "essay", "label": "Essay"} in columns["genre"][
            "choices"
        ]

    def test_a_choice_becomes_its_label_and_colour(self, library):
        data = BookTagsSerializer(library["essays"]).data

        # And keeps its value: the label is a translated word, and a
        # grid editing the choice starts its control from the value.
        assert data["genre"] == [
            {"label": "Essay", "color": "#0891b2", "value": "essay"}
        ]

    def test_a_reader_computes_the_tags_from_the_row(self, library):
        data = BookTagsSerializer(library["persuasion"]).data

        # The unavailable flag is None, and drawn as nothing. A computed
        # tag is no choice: it has no value beside its label.
        assert data["flags"] == [{"label": "249 pages"}]

    def test_an_export_gets_the_labels(self, library):
        field = BookTagsSerializer().fields["flags"]

        assert field.to_export(library["emma"]) == "Available, 474 pages"

    def test_a_copy_keeps_the_reader(self):
        # DRF copies fields per serializer; the reader must survive it.
        first = BookTagsSerializer().fields["flags"]
        second = BookTagsSerializer().fields["flags"]

        assert first is not second
        assert first.reader is second.reader


def test_tags_as_text():
    assert tags_text([{"label": "a"}, {"label": "b"}]) == "a, b"

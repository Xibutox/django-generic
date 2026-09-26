"""Fieldset layout, exercised without going through a view."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django import forms

from generic.forms import (
    FieldsetForm,
    build_default_fieldsets,
    render_readonly_value,
)
from tests.testapp.models import Book

pytestmark = pytest.mark.django_db


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ("title", "author", "pages", "is_available")


@pytest.fixture
def form(library) -> BookForm:
    return BookForm(instance=library["emma"])


class TestLayout:
    def test_a_string_entry_makes_a_single_field_row(self, form):
        layout = FieldsetForm(
            form,
            ((None, {"fields": ("title", "pages")}),),
        )
        rows = list(list(layout)[0])

        assert len(rows) == 2
        assert rows[0].is_multiline is False

    def test_a_tuple_entry_puts_fields_side_by_side(self, form):
        layout = FieldsetForm(
            form,
            ((None, {"fields": (("title", "pages"),)}),),
        )
        row = list(list(layout)[0])[0]

        assert len(row.fields) == 2
        assert row.is_multiline is True

    def test_named_fieldsets_keep_their_title(self, form):
        layout = FieldsetForm(
            form,
            (
                ("First", {"fields": ("title",)}),
                ("Second", {"fields": ("pages",)}),
            ),
        )

        assert [fieldset.title for fieldset in layout] == [
            "First",
            "Second",
        ]

    def test_collapse_is_detected_from_the_classes(self, form):
        layout = FieldsetForm(
            form,
            (
                (
                    "Advanced",
                    {"fields": ("pages",), "classes": ("collapse",)},
                ),
            ),
        )

        assert list(layout)[0].is_collapsible is True

    def test_the_default_layout_holds_every_visible_field(self, form):
        layout = FieldsetForm(form, build_default_fieldsets(form))
        names = [
            field.name
            for fieldset in layout
            for row in fieldset
            for field in row
        ]

        assert names == ["title", "author", "pages", "is_available"]


class TestRowState:
    def test_a_row_reports_its_errors(self, library):
        form = BookForm(
            data={"title": "", "pages": "10"},
            instance=library["emma"],
        )
        form.is_valid()

        layout = FieldsetForm(
            form,
            ((None, {"fields": ("title",)}),),
        )
        row = list(list(layout)[0])[0]

        assert row.has_errors is True
        assert "form-row--errors" in row.css_classes

    def test_a_row_carries_its_field_classes(self, form):
        layout = FieldsetForm(
            form,
            ((None, {"fields": ("title",)}),),
        )
        row = list(list(layout)[0])[0]

        assert "field-title" in row.css_classes

    def test_a_checkbox_is_flagged(self, form):
        layout = FieldsetForm(
            form,
            ((None, {"fields": ("is_available",)}),),
        )
        field = list(list(layout)[0])[0].fields[0]

        assert field.is_checkbox is True


class TestReadonlyFields:
    def test_a_readonly_field_is_not_an_input(self, form, library):
        layout = FieldsetForm(
            form,
            ((None, {"fields": ("title",)}),),
            readonly_fields=("title",),
        )
        field = list(list(layout)[0])[0].fields[0]

        assert field.is_readonly is True
        assert "Emma" in str(field.contents)

    def test_a_field_absent_from_the_form_is_readonly(
        self,
        form,
        library,
    ):
        layout = FieldsetForm(
            form,
            ((None, {"fields": ("genre",)}),),
        )
        field = list(list(layout)[0])[0].fields[0]

        assert field.is_readonly is True
        # ``get_genre_display`` wins over the raw value.
        assert "Fiction" in str(field.contents)

    def test_a_source_method_supplies_the_value(self, form, library):
        class Source:
            def computed(self, instance):
                return f"computed for {instance.title}"

            computed.short_description = "Computed"

        layout = FieldsetForm(
            form,
            ((None, {"fields": ("computed",)}),),
            source=Source(),
        )
        field = list(list(layout)[0])[0].fields[0]

        assert field.label == "Computed"
        assert "computed for Emma" in str(field.contents)


class TestValueRendering:
    def test_none_becomes_a_dash(self):
        assert render_readonly_value(None) == "—"

    def test_an_empty_string_becomes_a_dash(self):
        assert render_readonly_value("") == "—"

    def test_booleans_become_words(self):
        assert "Yes" in render_readonly_value(True)
        assert "No" in render_readonly_value(False)

    def test_zero_is_not_treated_as_empty(self):
        """0 is a value; only None and "" are absent."""
        assert render_readonly_value(0) == "0"

    def test_a_model_renders_as_its_string(self, library):
        assert render_readonly_value(library["austen"]) == ("Jane Austen")

    def test_a_related_manager_is_joined(self, library):
        rendered = render_readonly_value(library["emma"].chapters)

        assert "Volume I" in rendered
        assert "Volume II" in rendered

    def test_a_list_is_joined(self):
        assert render_readonly_value(["a", "b"]) == "a, b"

    def test_an_empty_list_becomes_a_dash(self):
        assert render_readonly_value([]) == "—"

    def test_a_date_is_localised(self):
        rendered = render_readonly_value(datetime.date(2020, 3, 15))

        assert "2020" in rendered

    def test_a_decimal_renders(self):
        assert "12.5" in render_readonly_value(Decimal("12.50"))

    def test_html_in_a_value_is_escaped(self):
        rendered = render_readonly_value("<script>alert(1)</script>")

        assert "<script>" not in rendered
        assert "&lt;script&gt;" in rendered

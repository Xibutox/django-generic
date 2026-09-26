from __future__ import annotations

from rest_framework import serializers

from generic.api import (
    BooleanColumn,
    CharColumn,
    ChoiceColumn,
    DataTableModelSerializer,
    DataTableSerializer,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    FloatColumn,
    FormModelSerializer,
    IntegerColumn,
    MethodColumn,
)
from tests.testapp.models import Author, Book, Chapter, Publisher


class BookTableSerializer(DataTableModelSerializer):
    title = CharColumn(title="Title")
    author = CharColumn(
        source="author.name",
        title="Author",
        read_only=True,
        filter_field="author__name",
        order_field="author__name",
    )
    genre = ChoiceColumn(
        choices=Book.Genre.choices,
        title="Genre",
        filter_type="multiselect",
    )
    pages = IntegerColumn(title="Pages")
    price = DecimalColumn(
        max_digits=8,
        decimal_places=2,
        title="Price",
    )
    rating = FloatColumn(title="Rating", allow_null=True)
    published_on = DateColumn(title="Published", allow_null=True)
    released_at = DateTimeColumn(title="Released", allow_null=True)
    is_available = BooleanColumn(title="Available")
    slug = MethodColumn(title="Slug")

    class Meta:
        model = Book
        fields = (
            "id",
            "title",
            "author",
            "genre",
            "pages",
            "price",
            "rating",
            "published_on",
            "released_at",
            "is_available",
            "slug",
        )

    def get_slug(self, instance: Book) -> str:
        return instance.title.lower().replace(" ", "-")


class HiddenPriceBookSerializer(BookTableSerializer):
    """Subclass adjusting an inherited column without redeclaring it."""

    datatable_overrides = {
        "price": {"visible": False},
        "pages": {"position": -10},
    }


class AuthorSummarySerializer(DataTableSerializer):
    """Table over an aggregated queryset, where a row is a dict."""

    author = CharColumn(title="Author", read_only=True)
    book_count = IntegerColumn(title="Books", read_only=True)
    total_pages = IntegerColumn(
        title="Total pages",
        read_only=True,
        allow_null=True,
    )


# -- forms ------------------------------------------------------------


class ChapterFormSerializer(FormModelSerializer):
    class Meta:
        model = Chapter
        fields = ("id", "book", "title", "position")

    form_overrides = {
        "title": {"label": "Chapter title", "position": 0},
        "position": {"label": "Order", "position": 1},
    }


class BookFormSerializer(FormModelSerializer):
    class Meta:
        model = Book
        fields = (
            "id",
            "title",
            "author",
            "publisher",
            "genre",
            "pages",
            "price",
            "is_available",
        )

    form_sections = (
        {
            "name": "general",
            "title": "General",
            "description": "",
            "position": 0,
        },
        {
            "name": "commercial",
            "title": "Commercial",
            "description": "Pricing and availability.",
            "position": 1,
        },
    )

    form_overrides = {
        "title": {"placeholder": "Book title", "position": 0},
        "author": {"position": 1},
        "price": {"section": "commercial", "position": 0},
        "is_available": {"section": "commercial", "position": 1},
    }


class PublisherFormSerializer(FormModelSerializer):
    class Meta:
        model = Publisher
        fields = ("id", "name", "country")


class AuthorFormSerializer(FormModelSerializer):
    book_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Author
        fields = (
            "id",
            "name",
            "email",
            "birth_date",
            "is_active",
            "book_count",
        )

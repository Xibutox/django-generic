from __future__ import annotations

from typing import Any

from django.db.models import Count, F, QuerySet, Sum
from rest_framework.permissions import AllowAny

from generic.api import (
    AggregatedDataTableViewSet,
    AutocompleteView,
    DataTableViewSet,
    InlineFormDefinition,
    ModelFormViewSet,
)
from tests.testapp.models import Author, Book, Publisher
from tests.testapp.serializers import (
    AuthorSummarySerializer,
    BookFormSerializer,
    BookTableSerializer,
    ChapterFormSerializer,
    HiddenPriceBookSerializer,
    PublisherFormSerializer,
)


class BookTableViewSet(DataTableViewSet):
    serializer_class = BookTableSerializer
    permission_classes = (AllowAny,)
    export_file_name = "books"

    def get_queryset(self) -> QuerySet:
        return Book.objects.select_related("author").all()


class ProtectedBookTableViewSet(BookTableViewSet):
    """Same table, but requiring authentication."""

    permission_classes = DataTableViewSet.permission_classes


class NoTotalCountBookViewSet(BookTableViewSet):
    table_total_count = False


class HiddenPriceBookViewSet(BookTableViewSet):
    serializer_class = HiddenPriceBookSerializer


class AuthorSummaryViewSet(AggregatedDataTableViewSet):
    serializer_class = AuthorSummarySerializer
    permission_classes = (AllowAny,)
    model = Author
    export_file_name = "authors"
    base_exclusions = {"is_active": False}
    filter_parameters = {"name": "name__icontains"}
    ordering = ("author",)

    def get_values(self) -> dict[str, Any]:
        return {"author": F("name")}

    def get_aggregations(self) -> dict[str, Any]:
        return {
            "book_count": Count("books"),
            "total_pages": Sum("books__pages"),
        }


class BookFormViewSet(ModelFormViewSet):
    serializer_class = BookFormSerializer
    permission_classes = (AllowAny,)
    queryset = Book.objects.all()

    inline_form_definitions = (
        InlineFormDefinition(
            name="chapters",
            serializer_class=ChapterFormSerializer,
            related_name="chapters",
            parent_field="book",
            title="Chapters",
            max_rows=5,
        ),
    )


class RequiredChapterBookFormViewSet(BookFormViewSet):
    inline_form_definitions = (
        InlineFormDefinition(
            name="chapters",
            serializer_class=ChapterFormSerializer,
            related_name="chapters",
            parent_field="book",
            title="Chapters",
            min_rows=1,
            can_delete=False,
        ),
    )


class PublisherFormViewSet(ModelFormViewSet):
    serializer_class = PublisherFormSerializer
    permission_classes = (AllowAny,)
    queryset = Publisher.objects.all()


class AuthorAutocomplete(AutocompleteView):
    permission_classes = (AllowAny,)
    queryset = Author.objects.all()
    search_fields = ("name", "email")
    label_field = "name"

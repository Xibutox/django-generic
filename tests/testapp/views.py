"""Views exercising the generic UI layer."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from generic.views import (
    DataTableView,
    GenericCreateView,
    GenericDeleteView,
    GenericDetailView,
    GenericListView,
    GenericUpdateView,
)
from tests.testapp.models import Author, Book, Publisher
from tests.testapp.viewsets import BookTableViewSet


class BookListView(GenericListView):
    model = Book
    require_permission = False
    paginate_by = 5

    list_display = ("title", "author", "pages", "is_available", "age")
    search_fields = ("title", "author__name")
    ordering = ("title",)
    detail_url_name = "book-detail-page"
    create_url_name = "book-create-page"

    bulk_actions = (("mark_unavailable", _("Mark as unavailable")),)

    def get_queryset(self) -> QuerySet:
        return super().get_queryset().select_related("author")

    def age(self, instance: Book) -> str:
        """A column computed by the view rather than stored."""
        if instance.published_on is None:
            return ""

        return str(instance.published_on.year)

    age.short_description = _("Published year")

    def bulk_action_mark_unavailable(
        self,
        request: Any,
        queryset: QuerySet,
    ) -> None:
        queryset.update(is_available=False)


class ProtectedBookListView(BookListView):
    """Same listing, but requiring the model permission."""

    require_permission = True


class BookDetailView(GenericDetailView):
    model = Book
    require_permission = False
    display_fields = ("title", "author", "genre", "pages", "price")
    list_url_name = "book-list-page"
    update_url_name = "book-update-page"
    delete_url_name = "book-delete-page"


class BookCreateView(GenericCreateView):
    model = Book
    require_permission = False
    fields = ("title", "author", "publisher", "genre", "pages", "price")
    list_url_name = "book-list-page"
    detail_url_name = "book-detail-page"


class BookUpdateView(GenericUpdateView):
    model = Book
    require_permission = False
    fields = ("title", "author", "publisher", "genre", "pages", "price")
    list_url_name = "book-list-page"
    detail_url_name = "book-detail-page"
    delete_url_name = "book-delete-page"


class FieldsetBookUpdateView(BookUpdateView):
    """The same form, laid out in named fieldsets."""

    readonly_fields = ("created_display",)

    fieldsets = (
        (None, {"fields": ("title", ("author", "publisher"))}),
        (
            "Commercial",
            {
                "fields": ("genre", "pages", "price"),
                "description": "Pricing and classification.",
                "classes": ("collapse",),
            },
        ),
        ("Meta", {"fields": ("created_display",)}),
    )

    def created_display(self, instance: Book) -> str:
        return "read-only value"

    created_display.short_description = _("Created")


class BookDeleteView(GenericDeleteView):
    model = Book
    require_permission = False
    list_url_name = "book-list-page"
    detail_url_name = "book-detail-page"


class PublisherDeleteView(GenericDeleteView):
    """Deleting this is blocked by a PROTECT relation."""

    model = Publisher
    require_permission = False
    list_url_name = "book-list-page"


class AuthorListView(GenericListView):
    """A listing that falls back to ``__str__`` for its only column."""

    model = Author
    require_permission = False


class BookTablePage(DataTableView):
    model = Book
    require_permission = False
    viewset = BookTableViewSet
    api_url_name = "book-list"
    create_url_name = "book-create-page"

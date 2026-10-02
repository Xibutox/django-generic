from django.urls import include, path
from django.views.i18n import JavaScriptCatalog
from rest_framework.routers import DefaultRouter

from generic.sites import site
from tests.testapp.views import (
    AuthorListView,
    BookCreateView,
    BookDeleteView,
    BookDetailView,
    BookListView,
    BookTablePage,
    BookUpdateView,
    FieldsetBookUpdateView,
    ProtectedBookListView,
    PublisherDeleteView,
)
from tests.testapp.viewsets import (
    AuthorAutocomplete,
    AuthorSummaryViewSet,
    BookFormViewSet,
    BookTableViewSet,
    HiddenPriceBookViewSet,
    NoTotalCountBookViewSet,
    ProtectedBookTableViewSet,
    PublisherFormViewSet,
    RequiredChapterBookFormViewSet,
)

router = DefaultRouter()
router.register("books", BookTableViewSet, basename="book")
router.register(
    "books-protected",
    ProtectedBookTableViewSet,
    basename="book-protected",
)
router.register(
    "books-no-total",
    NoTotalCountBookViewSet,
    basename="book-no-total",
)
router.register(
    "books-hidden-price",
    HiddenPriceBookViewSet,
    basename="book-hidden-price",
)
router.register(
    "authors-summary",
    AuthorSummaryViewSet,
    basename="author-summary",
)
router.register("book-forms", BookFormViewSet, basename="book-form")
router.register(
    "book-forms-required",
    RequiredChapterBookFormViewSet,
    basename="book-form-required",
)
router.register(
    "publishers",
    PublisherFormViewSet,
    basename="publisher",
)

ui_urlpatterns = [
    path("books/", BookListView.as_view(), name="book-list-page"),
    path(
        "books/protected/",
        ProtectedBookListView.as_view(),
        name="book-list-protected",
    ),
    path(
        "books/table/",
        BookTablePage.as_view(),
        name="book-table-page",
    ),
    path(
        "books/add/",
        BookCreateView.as_view(),
        name="book-create-page",
    ),
    path(
        "books/<int:pk>/",
        BookDetailView.as_view(),
        name="book-detail-page",
    ),
    path(
        "books/<int:pk>/change/",
        BookUpdateView.as_view(),
        name="book-update-page",
    ),
    path(
        "books/<int:pk>/fieldsets/",
        FieldsetBookUpdateView.as_view(),
        name="book-fieldsets-page",
    ),
    path(
        "books/<int:pk>/delete/",
        BookDeleteView.as_view(),
        name="book-delete-page",
    ),
    path(
        "publishers/<int:pk>/delete/",
        PublisherDeleteView.as_view(),
        name="publisher-delete-page",
    ),
    path("authors/", AuthorListView.as_view(), name="author-list-page"),
]

urlpatterns = [
    # The example's table template loads it, and so would a project.
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic"]),
        name="javascript-catalog",
    ),
    path("", include(ui_urlpatterns)),
    # The example project's own routes, under a prefix so they cannot
    # collide with the fixtures above.
    path(
        "example/api/",
        include("example.api_urls", namespace="example_api"),
    ),
    path("example/", include("example.urls", namespace="example")),
    path("api/", include("generic.openapi.urls")),
    path("api/", include(router.urls)),
    path(
        "api/author-autocomplete/",
        AuthorAutocomplete.as_view(),
        name="author-autocomplete",
    ),
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("wiki/", include("generic.wiki.urls")),
    path("docx/", include("generic.docx.urls")),
    # The registry: every model the example's resources.py declares.
    # Last, so the fixtures above keep their paths.
    path("", site.urls),
]

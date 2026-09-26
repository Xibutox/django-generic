"""The old import paths keep working.

``kanboard`` imports ``generic.api.datatables``; that module moved, and
this is the shim that keeps existing project code compiling.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


class TestDataTablesShim:
    def test_the_columns_are_importable_from_the_old_path(self):
        from generic.api.datatables import (  # noqa: F401
            CharColumn,
            DataTableSerializer,
            DateColumn,
            DateTimeColumn,
            IntegerColumn,
        )

    def test_the_export_mixin_kept_its_old_name(self):
        from generic.api.datatables import ExcelExportMixin
        from generic.api.exports import ExportMixin

        assert ExcelExportMixin is ExportMixin

    def test_the_old_column_helper_still_answers(self):
        from generic.api.datatables import AdvancedFilterMixin
        from tests.testapp.serializers import BookTableSerializer

        class Legacy(AdvancedFilterMixin):
            serializer_class = BookTableSerializer

        columns = Legacy.get_datatable_columns()

        assert any(column["data"] == "title" for column in columns)

    def test_the_old_filter_whitelist_still_answers(self):
        from generic.api.datatables import AdvancedFilterMixin
        from tests.testapp.serializers import BookTableSerializer

        class Legacy(AdvancedFilterMixin):
            serializer_class = BookTableSerializer

        fields = Legacy().get_advanced_filter_fields()

        assert fields["author"]["field"] == "author__name"
        assert fields["author"]["type"] == "text"

    def test_apply_advanced_filters_still_filters(self, rf, library):
        import json

        from generic.api.datatables import AdvancedFilterMixin
        from tests.testapp.models import Book
        from tests.testapp.serializers import BookTableSerializer

        class Legacy(AdvancedFilterMixin):
            serializer_class = BookTableSerializer

        request = rf.get(
            "/",
            {
                "advanced_filters": json.dumps(
                    {
                        "title": {
                            "operator": "contains",
                            "value": "Emma",
                        }
                    }
                )
            },
        )
        # DRF's query_params is a plain alias for GET.
        request.query_params = request.GET

        queryset = Legacy().apply_advanced_filters(
            Book.objects.all(),
            request,
        )

        assert [book.title for book in queryset] == ["Emma"]


class TestRouting:
    def test_the_websocket_route_is_registered(self):
        from generic.events.routing import websocket_urlpatterns

        assert len(websocket_urlpatterns) == 1
        assert "ws/events/" in str(websocket_urlpatterns[0].pattern)

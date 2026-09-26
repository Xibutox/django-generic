"""Compatibility shim for the previous module layout.

``generic.api.datatables`` used to hold the columns, the serializer, the
filtering mixin and the Excel export in one file. They now live in
focused modules; this re-exports them so existing project code keeps
importing::

    from generic.api.datatables import CharColumn, DataTableSerializer

New code should import from :mod:`generic.api` instead.

One behavioural note for anything still using ``AdvancedFilterMixin``:
filtering is now a DRF filter backend rather than a method the viewset
calls by hand. The mixin below keeps ``apply_advanced_filters()``
working, but a viewset inheriting :class:`generic.api.DataTableViewSet`
gets filtering, searching and ordering already wired up and should not
call it.
"""

from typing import Any

from django.db.models import QuerySet

from generic.api.columns import (
    BooleanColumn,
    CharColumn,
    ChoiceColumn,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    FloatColumn,
    IntegerColumn,
    MethodColumn,
)
from generic.api.exports import ExcelExportMixin, ExportMixin
from generic.api.filters import AdvancedFilterBackend
from generic.api.serializers import (
    DataTableModelSerializer,
    DataTableSerializer,
)


class AdvancedFilterMixin:
    """Deprecated: use :data:`generic.api.DATATABLE_FILTER_BACKENDS`."""

    @classmethod
    def get_datatable_columns(cls) -> list[dict[str, Any]]:
        return cls.serializer_class.get_datatable_columns()

    def get_advanced_filter_fields(self) -> dict[str, Any]:
        return {
            name: spec.as_dict()
            for name, spec in (
                self.serializer_class.get_filter_specs().items()
            )
        }

    def apply_advanced_filters(
        self,
        queryset: QuerySet,
        request: Any,
    ) -> QuerySet:
        return AdvancedFilterBackend().filter_queryset(
            request,
            queryset,
            self,
        )


__all__ = [
    "AdvancedFilterMixin",
    "BooleanColumn",
    "CharColumn",
    "ChoiceColumn",
    "DataTableModelSerializer",
    "DataTableSerializer",
    "DateColumn",
    "DateTimeColumn",
    "DecimalColumn",
    "ExcelExportMixin",
    "ExportMixin",
    "FloatColumn",
    "IntegerColumn",
    "MethodColumn",
]

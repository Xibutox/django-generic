"""DataTables server side pagination.

The client sends ``draw``, ``start`` and ``length``; the response carries
``draw``, ``recordsTotal``, ``recordsFiltered`` and ``data``. That is the
protocol DataTables expects in ``serverSide`` mode.

``recordsTotal`` is the size of the table before filtering. Computing it
costs a second ``COUNT`` on every draw, which is wasted work on a table
that is never displayed unfiltered, so a view can switch it off with
``table_total_count = False`` and the two counts then coincide.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from django.db.models import QuerySet
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from generic.conf import generic_settings


class DataTablesPagination(LimitOffsetPagination):
    """Translate ``start``/``length`` into limit/offset pagination."""

    draw_param = "draw"
    start_param = "start"
    length_param = "length"

    def __init__(self) -> None:
        super().__init__()
        self.draw = 0
        self.total_count: int | None = None

    # -- request ------------------------------------------------------

    @property
    def default_limit(self) -> int:  # type: ignore[override]
        return generic_settings.TABLE_PAGE_SIZE

    @property
    def max_limit(self) -> int:  # type: ignore[override]
        return generic_settings.TABLE_MAX_PAGE_SIZE

    def get_limit(self, request: Any) -> int:
        raw_limit = request.query_params.get(self.length_param)

        if raw_limit is None:
            return self.default_limit

        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return self.default_limit

        # DataTables asks for every row with length=-1.
        if limit < 0:
            if generic_settings.TABLE_ALLOW_UNLIMITED_PAGE_SIZE:
                return self.max_limit
            return self.default_limit

        if limit == 0:
            return self.default_limit

        return min(limit, self.max_limit)

    def get_offset(self, request: Any) -> int:
        try:
            return max(0, int(request.query_params.get(self.start_param, 0)))
        except (TypeError, ValueError):
            return 0

    def get_draw(self, request: Any) -> int:
        """Echo the draw counter back, as an integer.

        DataTables requires the value to be cast rather than echoed
        verbatim, precisely so a crafted ``draw`` cannot be reflected
        into the page.
        """
        try:
            return int(request.query_params.get(self.draw_param, 0))
        except (TypeError, ValueError):
            return 0

    # -- pagination ---------------------------------------------------

    def paginate_queryset(
        self,
        queryset: QuerySet,
        request: Any,
        view: Any = None,
    ) -> list[Any] | None:
        self.draw = self.get_draw(request)
        self.total_count = self.get_total_count(queryset, view)

        return super().paginate_queryset(queryset, request, view)

    def get_total_count(
        self,
        queryset: QuerySet,
        view: Any,
    ) -> int | None:
        """Row count before any filtering was applied.

        ``None`` means "same as the filtered count", which is what the
        response falls back to.
        """
        if view is None or not getattr(view, "table_total_count", True):
            return None

        # Set by DataTableViewSet before the filter backends run.
        cached = getattr(view, "_table_total_count", None)

        if cached is not None:
            return int(cached)

        return None

    def get_paginated_response(self, data: Any) -> Response:
        filtered_count = self.count
        total_count = (
            self.total_count
            if self.total_count is not None
            else filtered_count
        )

        return Response(
            OrderedDict(
                [
                    ("draw", self.draw),
                    ("recordsTotal", total_count),
                    ("recordsFiltered", filtered_count),
                    ("data", data),
                ]
            )
        )

    def get_paginated_response_schema(
        self,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "type": "object",
            "required": [
                "draw",
                "recordsTotal",
                "recordsFiltered",
                "data",
            ],
            "properties": {
                "draw": {"type": "integer", "example": 1},
                "recordsTotal": {"type": "integer", "example": 1200},
                "recordsFiltered": {"type": "integer", "example": 42},
                "data": schema,
            },
        }

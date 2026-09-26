"""Select2 compatible autocomplete endpoints.

Multiselect column filters populate their dropdown from one of these.
The response shape is the one Select2 expects::

    {
        "results": [{"id": 1, "text": "Label"}],
        "pagination": {"more": true}
    }
"""

from __future__ import annotations

from typing import Any, Iterable

from django.db.models import Q, QuerySet
from django.utils.encoding import force_str
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from generic.conf import generic_settings


class AutocompleteView(APIView):
    """Paginated, searchable option list.

    Minimal configuration::

        class ProjectAutocomplete(AutocompleteView):
            queryset = Project.objects.all()
            search_fields = ("name",)

    ``search_fields`` is a fixed whitelist: the client only ever sends a
    search term, never a field to search in.
    """

    permission_classes = (IsAuthenticated,)

    queryset: QuerySet | None = None
    #: ORM paths the term is matched against, with ``icontains``.
    search_fields: tuple[str, ...] = ()
    #: Field used as the option value.
    value_field: str = "pk"
    #: Field used as the option label; ``None`` falls back to ``str()``.
    label_field: str | None = None
    ordering: tuple[str, ...] = ()

    search_param = "q"
    page_param = "page"

    @property
    def page_size(self) -> int:
        return generic_settings.AUTOCOMPLETE_PAGE_SIZE

    @property
    def minimum_input_length(self) -> int:
        return generic_settings.AUTOCOMPLETE_MIN_INPUT_LENGTH

    # -- data ---------------------------------------------------------

    def get_queryset(self) -> QuerySet:
        if self.queryset is None:
            raise NotImplementedError(
                f"{type(self).__name__} must define 'queryset' or "
                f"override get_queryset()."
            )

        return self.queryset.all()

    def filter_queryset(
        self,
        queryset: QuerySet,
        term: str,
    ) -> QuerySet:
        if not term or not self.search_fields:
            return queryset

        condition = Q()

        for field in self.search_fields:
            condition |= Q(**{f"{field}__icontains": term})

        return queryset.filter(condition)

    def order_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.ordering:
            return queryset.order_by(*self.ordering)

        if self.label_field:
            return queryset.order_by(self.label_field)

        return queryset

    # -- serialization ------------------------------------------------

    def get_result_value(self, item: Any) -> Any:
        value = getattr(item, self.value_field)

        return value

    def get_result_label(self, item: Any) -> str:
        if self.label_field:
            return force_str(getattr(item, self.label_field))

        return force_str(item)

    def serialize_results(
        self,
        items: Iterable[Any],
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": self.get_result_value(item),
                "text": self.get_result_label(item),
            }
            for item in items
        ]

    # -- request ------------------------------------------------------

    def get_page(self, request: Any) -> int:
        try:
            return max(1, int(request.query_params.get(self.page_param, 1)))
        except (TypeError, ValueError):
            return 1

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        term = (request.query_params.get(self.search_param) or "").strip()

        if len(term) < self.minimum_input_length:
            return Response({"results": [], "pagination": {"more": False}})

        page = self.get_page(request)
        offset = (page - 1) * self.page_size

        queryset = self.order_queryset(
            self.filter_queryset(self.get_queryset(), term)
        )

        # One extra row is what tells Select2 whether to keep scrolling,
        # without paying for a COUNT.
        items = list(queryset[offset : offset + self.page_size + 1])
        has_more = len(items) > self.page_size

        return Response(
            {
                "results": self.serialize_results(items[: self.page_size]),
                "pagination": {"more": has_more},
            }
        )

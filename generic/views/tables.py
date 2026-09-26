"""Server-rendered object tables.

The admin's ``list_display`` idea, kept because it is the shortest path
from a model to a usable listing::

    class BookListView(GenericListView):
        model = Book
        list_display = ("title", "author", "pages", "is_available")

An entry may name a model field, a method on the view, or a callable.
For the interactive, filterable table backed by the REST API, see
:class:`generic.views.DataTableView` instead.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator, Sequence

from django.db import models
from django.utils.encoding import force_str
from django.utils.safestring import SafeString

from generic.forms.fieldsets import render_readonly_value


def resolve_column_label(
    name: str,
    accessor: Any,
    model: type[models.Model] | None,
) -> str:
    """Work out a header label the way the admin does."""
    label = getattr(accessor, "short_description", None)

    if label:
        return force_str(label)

    if name == "__str__":
        if model is not None:
            return force_str(model._meta.verbose_name).capitalize()

        return ""

    if model is not None:
        try:
            field = model._meta.get_field(name)
        except Exception:
            field = None

        if field is not None:
            return force_str(getattr(field, "verbose_name", name)).capitalize()

    return name.replace("_", " ").capitalize()


class ObjectColumn:
    """One column of a server-rendered table."""

    def __init__(
        self,
        name: str,
        *,
        view: Any = None,
        model: type[models.Model] | None = None,
        label: str | None = None,
        ordering_field: str | None = None,
        css_class: str = "",
        is_link: bool = False,
    ) -> None:
        self.name = name
        self.view = view
        self.model = model
        self.css_class = css_class
        self.is_link = is_link

        # A method on the view, or a plain attribute resolved per row.
        # ``__str__`` is the admin's idiom for "the object itself".
        self.accessor: Callable[[Any], Any] | None = None

        if name == "__str__":
            self.accessor = force_str
        elif view is not None and hasattr(view, name):
            self.accessor = getattr(view, name)

        self.label = label or resolve_column_label(
            name,
            self.accessor,
            model,
        )
        self.ordering_field = ordering_field

    @property
    def is_sortable(self) -> bool:
        return bool(self.ordering_field)

    def value(self, instance: Any) -> SafeString:
        if self.accessor is not None:
            return render_readonly_value(self.accessor(instance))

        display = getattr(instance, f"get_{self.name}_display", None)

        if callable(display):
            return render_readonly_value(display())

        return render_readonly_value(getattr(instance, self.name, None))


class ObjectRow:
    """One row, plus the link and identity the template needs."""

    def __init__(
        self,
        instance: Any,
        columns: Sequence[ObjectColumn],
        url: str = "",
    ) -> None:
        self.instance = instance
        self.columns = columns
        self.url = url

    @property
    def pk(self) -> Any:
        return self.instance.pk

    @property
    def cells(self) -> list[dict[str, Any]]:
        return [
            {
                "column": column,
                "value": column.value(self.instance),
                "is_link": column.is_link and bool(self.url),
            }
            for column in self.columns
        ]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.cells)


class ObjectTable:
    """Columns and rows, ready for the template."""

    def __init__(
        self,
        columns: Sequence[ObjectColumn],
        instances: Sequence[Any],
        *,
        url_for: Callable[[Any], str] | None = None,
    ) -> None:
        self.columns = list(columns)
        self.rows = [
            ObjectRow(
                instance,
                self.columns,
                url_for(instance) if url_for else "",
            )
            for instance in instances
        ]

    @property
    def is_empty(self) -> bool:
        return not self.rows

    def __iter__(self) -> Iterator[ObjectRow]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

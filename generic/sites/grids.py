"""Grids: tables built for correcting many records at once.

A grid is a resource's own table - its columns, filters, search,
exports and bulk actions - asked to be editable, over rows the project
chooses. Three things ask for one:

* a table of one record's related rows, on a page built for them:
  ``RelatedTable(editable=True)``, or ``bound.get_table_config(request,
  obj, editable=True)``;
* the resource's own rows, on a page of the project's:
  ``resource.get_table_config(request, editable=True)``;
* **any other set**, declared here and shown by :class:`GridView`::

    class TicketResource(ModelResource):
        editable_fields = ("team", "assignee", "priority", "status")
        grids = (
            Grid(
                "triage",
                title=_("Triage"),
                columns=("reference", "title", "team", "assignee",
                         "priority", "status"),
                scope="triage_rows",
                add_fields=("reference", "title"),
                add_values="new_triage_ticket",
            ),
        )

        def triage_rows(self, request, queryset, argument):
            return queryset.filter(status__in=("open", "pending"))

The browser names a grid - ``_grid=example.ticket.triage``, with an
argument after a colon when the grid takes one - and never a path: which
rows, which columns and what a new row starts from are the
declaration's. The scope says which rows are *shown*; which may be
written is still the permissions', checked on every write.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, Sequence
from urllib.parse import urlencode

from django.core.exceptions import (
    ImproperlyConfigured,
    ObjectDoesNotExist,
    ValidationError,
)
from django.utils.encoding import force_str

#: Query parameter naming the grid a table shows:
#: ``<app>.<model>.<grid>`` or ``<app>.<model>.<grid>:<argument>``.
GRID_PARAM = "_grid"

#: What a scope raises on an argument it cannot read - ``int("x")``, a
#: record that is not there. The endpoint and the page answer 404: the
#: argument names nothing.
ARGUMENT_ERRORS = (
    TypeError,
    ValueError,
    LookupError,
    ObjectDoesNotExist,
    ValidationError,
)


@dataclasses.dataclass(frozen=True)
class Grid:
    """Declare one grid: rows of a resource, corrected many at once."""

    #: Identifies the grid within its resource, and in ``_grid``.
    name: str
    title: Any = None
    description: Any = ""
    icon: str | None = None
    #: The columns shown at first, by name; the resource's others stay
    #: in the column picker. None shows the resource's own choice.
    columns: Sequence[str] | None = None
    #: Which of the resource's ``editable_fields`` this grid writes.
    #: None: all of them. The endpoint refuses the others.
    editable: Sequence[str] | None = None
    #: The rows: a method name of the resource, or a function, taking
    #: ``(request, queryset, argument)`` and returning the queryset.
    #: None: every row the reader may see.
    scope: Any = None
    #: Whether rows may be added from the grid - to readers who may add.
    allow_add: bool = True
    #: Fields a new row writes although the grid never changes them
    #: afterwards: a reference, a title.
    add_fields: Sequence[str] = ()
    #: What a new row starts from: a method name of the resource, or a
    #: function, taking ``(request, argument)`` and returning
    #: ``{field: value}``. The value of a column the new row writes is
    #: where its control starts; any other is set on the record,
    #: whatever the reader does.
    add_values: Any = None
    page_length: int | None = None
    #: The grid needs an argument - a team, a day - after the colon.
    #: The scope receives it as the browser sent it: a string to check.
    requires_argument: bool = False


@dataclasses.dataclass(frozen=True)
class RowContext:
    """What a grid's request allows, worked out by the server.

    Built from the table's own parameter - ``_grid`` or ``_related`` -
    never from what the browser says it may do.
    """

    #: The columns this grid writes; None: all the resource's.
    editable: frozenset[str] | None = None
    #: The columns a new row writes.
    creatable: tuple[str, ...] = ()
    #: What a new row starts from, by field name.
    values: dict[str, Any] = dataclasses.field(default_factory=dict)
    allow_add: bool = True
    #: The rows of this grid, from a queryset of the resource's.
    narrow: Callable[[Any], Any] | None = None
    #: The parameter to send back with every write.
    query: dict[str, str] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class BoundGrid:
    """A grid resolved against the resource declaring it."""

    definition: Grid
    resource: Any

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def key(self) -> str:
        """What ``_grid`` names: the resource, then the grid."""
        return f"{self.resource.label_lower}.{self.name}"

    def token(self, argument: Any = None) -> str:
        if argument is None or argument == "":
            return self.key

        return f"{self.key}:{argument}"

    def get_title(self) -> str:
        if self.definition.title:
            return force_str(self.definition.title)

        return self.resource.get_label_plural()

    def get_description(self) -> str:
        return force_str(self.definition.description or "")

    def get_icon(self) -> str:
        return self.definition.icon or self.resource.get_icon()

    def is_visible(self, request: Any) -> bool:
        return bool(self.resource.has_view_permission(request))

    def _call(self, spec: Any, *args: Any) -> Any:
        if isinstance(spec, str):
            return getattr(self.resource, spec)(*args)

        return spec(*args)

    def filter(self, request: Any, queryset: Any, argument: Any) -> Any:
        """The grid's rows. Raises what the scope raises on a bad
        argument; the endpoint answers that with a 404."""
        if self.definition.requires_argument and not argument:
            raise ValueError("This grid needs an argument.")

        if self.definition.scope is None:
            return queryset

        return self._call(self.definition.scope, request, queryset, argument)

    def get_values(self, request: Any, argument: Any) -> dict[str, Any]:
        if self.definition.add_values is None:
            return {}

        return dict(
            self._call(self.definition.add_values, request, argument) or {}
        )

    def editable_names(self) -> frozenset[str] | None:
        if self.definition.editable is None:
            return None

        return frozenset(str(name) for name in self.definition.editable)

    def creatable(self) -> tuple[str, ...]:
        """What a new row writes: this grid's editable columns of the
        model itself, then the fields only a new row writes."""
        from generic.sites.editable import own_columns

        allowed = self.editable_names()
        names = [
            name
            for name in own_columns(self.resource)
            if allowed is None or name in allowed
        ]

        return tuple(
            names + [n for n in self.definition.add_fields if n not in names]
        )

    def context(self, request: Any, argument: Any = None) -> RowContext:
        return RowContext(
            editable=self.editable_names(),
            creatable=self.creatable(),
            values=self.get_values(request, argument),
            allow_add=self.definition.allow_add,
            narrow=lambda queryset: self.filter(request, queryset, argument),
            query={GRID_PARAM: self.token(argument)},
        )

    def check(self, request: Any, argument: Any = None) -> None:
        """Raise if the grid refuses ``argument``.

        Both hooks read it - the scope, and what a new row starts from -
        and a record it names that is not there is as much a refusal as
        a word where a number was expected. The rows are not read.
        """
        self.filter(request, self.resource.get_queryset(request), argument)

        if self.definition.allow_add:
            self.get_values(request, argument)

    def get_table_config(
        self,
        request: Any,
        argument: Any = None,
    ) -> dict[str, Any]:
        """The resource's table, as this grid: its rows, its columns."""
        resource = self.resource
        context = self.context(request, argument)
        config = resource.get_table_config(request, editable=True)
        columns = list(config["columns"])

        if self.definition.columns is not None:
            shown = set(self.definition.columns)
            columns = [
                {**column, "visible": column.get("data") in shown}
                for column in columns
            ]

        options = with_context(resource, request, config["options"], context)
        options.update(
            stateKey=f"{resource.state_key}.grid.{self.name}",
            extraParams=dict(context.query),
            exportName=f"{resource.model_name}-{self.name}",
        )

        if self.definition.page_length:
            options["pageLength"] = self.definition.page_length

        return {**config, "columns": columns, "options": options}


def with_context(
    resource: Any,
    request: Any,
    options: dict[str, Any],
    context: RowContext,
) -> dict[str, Any]:
    """A grid's options, narrowed to what its context allows.

    The cells it may write, the address they are written to - carrying
    the context, which the endpoint reads back - and how it adds rows.
    """
    from generic.sites.editable import add_options

    options = dict(options)
    described = dict(options.get("editable") or {})

    if context.editable is not None:
        described = {
            name: schema
            for name, schema in described.items()
            if name in context.editable
        }

    if described:
        options["editable"] = described
        options["editableUrl"] = with_query(
            resource.get_cells_url_template(), context.query
        )
    else:
        options.pop("editable", None)
        options.pop("editableUrl", None)

    added = add_options(resource, request, context)

    if added:
        options["gridAdd"] = added
    else:
        options.pop("gridAdd", None)

    return options


def with_query(url: str, query: dict[str, str]) -> str:
    if not url or not query:
        return url

    return f"{url}{'&' if '?' in url else '?'}{urlencode(query)}"


def bind_grid(definition: Grid, resource: Any) -> BoundGrid:
    """Resolve ``definition`` against the resource declaring it.

    Checked once, at the first use: a column the table does not have, a
    field that is not editable or a scope that is not there is an error
    at start-up rather than an empty grid.
    """
    owner = type(resource).__name__
    shown = set(resource.get_list_display())
    where = f"{owner}.grids['{definition.name}']"

    for name in definition.columns or ():
        if name not in shown:
            raise ImproperlyConfigured(
                f"{where} shows '{name}', which is not in list_display."
            )

    declared = {str(name) for name in resource.editable_fields}

    for name in definition.editable or ():
        if name not in declared:
            raise ImproperlyConfigured(
                f"{where} edits '{name}', which is not in the resource's "
                f"editable_fields."
            )

    from generic.sites.editable import resolve

    for name in definition.add_fields:
        if name not in shown:
            raise ImproperlyConfigured(
                f"{where} adds '{name}', which is not in list_display: a "
                f"new row writes it in its own cell."
            )

        if not resolve(resource, name).is_own:
            raise ImproperlyConfigured(
                f"{where} adds '{name}', a field of another record: a new "
                f"row writes its own fields only."
            )

    for spec in (definition.scope, definition.add_values):
        if isinstance(spec, str) and not callable(
            getattr(resource, spec, None)
        ):
            raise ImproperlyConfigured(
                f"{where} names '{spec}', which is not a method of {owner}."
            )

    return BoundGrid(definition=definition, resource=resource)


__all__ = [
    "ARGUMENT_ERRORS",
    "GRID_PARAM",
    "BoundGrid",
    "Grid",
    "RowContext",
    "bind_grid",
    "with_context",
    "with_query",
]

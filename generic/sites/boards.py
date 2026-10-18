"""Records on a board: one column per value of a field, a card each.

Declared on the resource of the records, naming the field whose values
are the columns - a choice, a yes or no, or a relation::

    @register(Ticket)
    class TicketResource(ModelResource):
        editable_fields = ("priority", "team", ...)
        boards = (
            Board(
                "by-priority",
                field="priority",
                title=_("Priorities"),
                color="team",
                fields=("customer", "assignee", "due_on"),
                editable=True,
            ),
        )

Each board is a page of the resource, ``<model>/<name>/``, with a button
on the list. The resource's own table sits above it, rows hidden: its
search box and filter editor choose the cards, exactly as they would
choose the rows of the list.

The endpoint, ``GET api/<app>/<model>/boards/<name>/``, answers every
column with its count and its first cards, through the resource's list
queryset and the table's filter backends: a reader never sees a card
the list would not show them.

With ``editable``, a card dragged to another column takes that column's
value, written through the table's own cell writer (``save_editable``):
the field must be one of the resource's ``editable_fields``, and the
change permission, the per-row ``can_edit_column`` and the form's
validation all apply. A state field (``transitions``) moves through its
transitions, never here: a board on one is read only.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Sequence

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.utils.encoding import force_str
from django.utils.translation import gettext, gettext_lazy
from rest_framework.exceptions import PermissionDenied, ValidationError

from generic.sites.dashboard import check_entry
from generic.sites.pages import ResourcePage, ResourcePageView

#: A board's name is a piece of its endpoint's address and its page's.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: The most columns a relation gives a board: past it, filter the
#: related records with ``columns``.
MAX_COLUMNS = 30

#: The cards one column answers; its count says how many there are.
MAX_CARDS = 100

#: The value of the column of records without one.
EMPTY = None


@dataclasses.dataclass(frozen=True)
class Board:
    """Declare one board of the resource's records."""

    #: Lower case letters, digits and dashes: the page is ``<name>/``.
    name: str
    #: The field whose values are the columns: a field with choices, a
    #: boolean, or a foreign key.
    field: str
    title: Any = None
    icon: str = "view_kanban"
    description: Any = ""
    #: The values shown, in this order: choices' values, or a relation's
    #: primary keys. None: every choice, every related record.
    columns: Sequence[Any] | None = None
    #: A column for the records without a value, when the field allows
    #: none.
    show_empty: bool = True
    #: The card's text: a field, a resource method or a model
    #: attribute. Default: the record's label.
    label: str | None = None
    #: Where the card's colour comes from: a field (or a ``tags=``
    #: method) the resource draws as coloured tags.
    color: str | None = None
    #: Values shown on the card, as a summary page shows them.
    fields: Sequence[str] = ()
    #: Cards dragged to another column are written - see the module.
    editable: bool = False
    #: An entry of the navigation, in the resource's group.
    navigation: bool = False
    #: Needed besides the resource's view permission (as a page's).
    permission: Any = None


@dataclasses.dataclass
class Column:
    """One column: the value its cards hold, as JSON and as stored."""

    key: Any
    value: Any
    label: str
    color: str = ""
    background: str = ""


def json_key(value: Any) -> Any:
    """A value as the browser sends it back: a number, a boolean, a
    string, or null."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    return force_str(value)


class BoundBoard:
    """A board resolved against its resource."""

    def __init__(self, definition: Board, resource: Any) -> None:
        self.definition = definition
        self.resource = resource
        self.field = board_field(resource, definition)

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def relation(self) -> bool:
        return bool(self.field.many_to_one)

    def get_title(self) -> str:
        return force_str(self.definition.title or gettext("Board"))

    # -- the columns -----------------------------------------------------

    def style(self) -> Any:
        """How the resource draws the field as tags, if it does."""
        from generic.sites.serializers import tag_style_of

        style = (self.resource.tag_fields or {}).get(self.definition.field)

        return tag_style_of(style) if style is not None else None

    def get_columns(self, request: Any) -> list[Column]:
        """Every column, in order, the empty one last."""
        field = self.field
        wanted = self.definition.columns
        columns: list[Column] = []

        if self.relation:
            columns = self.related_columns(request, wanted)
        elif isinstance(field, models.BooleanField):
            columns = [
                Column(True, True, gettext("Yes")),
                Column(False, False, gettext("No")),
            ]
        else:
            columns = [
                Column(json_key(value), value, force_str(label))
                for value, label in field.flatchoices
                if value not in (None, "")
            ]

        if wanted is not None and not self.relation:
            by_value = {force_str(column.value): column for column in columns}
            columns = [
                by_value[force_str(value)]
                for value in wanted
                if force_str(value) in by_value
            ]

        if self.definition.show_empty and field.null:
            columns.append(Column(EMPTY, None, gettext("Not set")))

        style = self.style()

        for column in columns:
            if style is None or column.value is None:
                continue

            tag = style.describe(column.value, column.label) or {}
            column.color = force_str(tag.get("color") or "")
            column.background = force_str(tag.get("background") or "")

        return columns

    def related_columns(self, request: Any, wanted: Any) -> list[Column]:
        """A relation's records: those the reader may see, through the
        related resource when it is registered."""
        model = self.field.related_model
        related = self.resource.site.get_resource(model)

        if related is not None and related.has_view_permission(request):
            queryset = related.get_queryset(request)
        elif related is not None:
            queryset = model._default_manager.none()
        else:
            queryset = model._default_manager.all()

        if wanted is not None:
            queryset = queryset.filter(pk__in=list(wanted))
            order = {force_str(pk): index for index, pk in enumerate(wanted)}
            records = sorted(
                queryset[:MAX_COLUMNS],
                key=lambda record: order.get(force_str(record.pk), 0),
            )
        else:
            records = list(queryset[:MAX_COLUMNS])

        label = (
            related.get_object_label
            if related is not None
            else (lambda record: force_str(record))
        )

        return [
            Column(json_key(record.pk), record, force_str(label(record)))
            for record in records
        ]

    def column_filter(self, column: Column) -> dict[str, Any]:
        name = self.definition.field

        if column.value is None:
            return {f"{name}__isnull": True}

        return {name: column.value}

    # -- the cards ---------------------------------------------------------

    def answer(self, request: Any, queryset: Any) -> dict[str, Any]:
        """Every column with its count and first cards.

        ``queryset`` is the list's, the table's filters applied.
        """
        editable = self.can_move(request)
        columns = []

        if not queryset.ordered:
            queryset = queryset.order_by("pk")

        for column in self.get_columns(request):
            rows = queryset.filter(**self.column_filter(column))
            cards = list(rows[: MAX_CARDS + 1])
            count = len(cards) if len(cards) <= MAX_CARDS else rows.count()

            columns.append(
                {
                    "key": column.key,
                    "label": column.label,
                    "color": column.color,
                    "background": column.background,
                    "count": count,
                    "truncated": len(cards) > MAX_CARDS,
                    "cards": [
                        self.describe(request, card, editable)
                        for card in cards[:MAX_CARDS]
                    ],
                }
            )

        return {"editable": editable, "columns": columns}

    def describe(self, request: Any, obj: Any, editable: bool) -> dict:
        from generic.sites.summary import describe_entry, record_url

        definition = self.definition
        label = self.resource.get_object_label(obj)

        if definition.label:
            entry = describe_entry(
                self.resource, request, obj, definition.label
            )
            label = force_str(entry.get("display") or label)

        value = getattr(obj, self.field.attname)
        card = {
            "id": force_str(obj.pk),
            "label": label,
            "url": record_url(self.resource.site, request, obj),
            "column": json_key(value),
            "color": "",
            "background": "",
            "cells": [],
            "editable": editable,
        }

        if definition.color:
            entry = describe_entry(
                self.resource, request, obj, definition.color
            )
            items = entry.get("items") or []

            if items:
                card["color"] = force_str(items[0].get("color") or "")
                card["background"] = force_str(
                    items[0].get("background") or ""
                )

        for name in definition.fields:
            entry = describe_entry(self.resource, request, obj, name)
            entry.pop("wide", None)
            card["cells"].append(entry)

        return card

    # -- moving a card -----------------------------------------------------

    def can_move(self, request: Any) -> bool:
        return bool(
            self.definition.editable
            and self.resource.has_change_permission(request)
        )

    def move(self, request: Any, obj: Any, data: Any) -> None:
        """Put ``obj`` in another column, through the cell writer."""
        if not self.can_move(request):
            raise PermissionDenied(
                gettext("Cards of this board are not moved here.")
            )

        if not isinstance(data, dict) or "column" not in data:
            raise ValidationError(gettext("Send the column to move it to."))

        sent = data.get("column")
        column = next(
            (
                column
                for column in self.get_columns(request)
                if (column.key is None and sent is None)
                or (
                    column.key is not None
                    and sent is not None
                    and force_str(column.key) == force_str(sent)
                )
            ),
            None,
        )

        if column is None:
            raise ValidationError(
                {"column": [gettext("This board has no such column.")]}
            )

        value = column.key if self.relation else column.value

        self.resource.save_editable(
            request, obj, {self.definition.field: value}
        )

    # -- where it shows ----------------------------------------------------

    def get_api_url(self) -> str:
        return self.resource._reverse(
            self.resource.api_url_name("board"), board=self.name
        )

    def get_move_url_template(self) -> str:
        from generic.sites.resources import PK_PLACEHOLDER

        url = self.resource._reverse(
            self.resource.api_url_name("board-move"),
            pk=PK_PLACEHOLDER,
            board=self.name,
        )

        return url.replace(PK_PLACEHOLDER, "{id}") if url else ""

    def get_page_url(self) -> str:
        return self.resource.get_page_url(self.name)

    def get_config(self, request: Any) -> dict[str, Any]:
        """What the browser needs to draw the board."""
        resource = self.resource

        return {
            "name": self.name,
            "title": self.get_title(),
            "url": self.get_api_url(),
            "moveUrl": (
                self.get_move_url_template() if self.can_move(request) else ""
            ),
            "maxCards": MAX_CARDS,
            # The id of a table whose filters choose the cards.
            "filterTable": None,
            "label": resource.get_label(),
            "labelPlural": resource.get_label_plural(),
            "addUrl": (
                resource.get_add_url()
                if resource.has_add_permission(request)
                else ""
            ),
            "field": self.definition.field,
            "topics": [resource.topic_name] if resource.realtime else [],
            "resource": resource.label_lower,
        }

    def get_filter_table_config(self, request: Any) -> dict[str, Any]:
        """The resource's own table, for its filter editor and search
        box: the board shows the records they select. Its rows are not
        shown."""
        return self.resource.get_page_table_config(
            request,
            f"board-{self.name}",
            pageLength=10,
            lengthMenu=[10],
            stateSave=False,
            columnSelector=False,
            filterRow=False,
            excel=False,
            csv=False,
            copy=False,
            print=False,
            rowActions=[],
            bulkActions=[],
            bulkEdit={},
            presets={},
            mailingUrl="",
            savedViewsUrl="",
            realtimeTopic="",
        )


def board_field(resource: Any, definition: Board) -> Any:
    """The field of the columns, or a refusal naming the declaration."""
    owner = type(resource).__name__
    model = resource.model

    try:
        field = model._meta.get_field(definition.field)
    except FieldDoesNotExist:
        field = None

    if field is None or not getattr(field, "concrete", False):
        raise ImproperlyConfigured(
            f"{owner}.boards: the field of '{definition.name}', "
            f"'{definition.field}', is not a field of {model.__name__}."
        )

    if not (
        field.many_to_one
        or isinstance(field, models.BooleanField)
        or field.choices
    ):
        raise ImproperlyConfigured(
            f"{owner}.boards: '{definition.name}' makes a column of each "
            f"value of '{definition.field}', which needs choices, a yes "
            f"or no, or a foreign key - not any value."
        )

    return field


def bind_board(definition: Any, resource: Any) -> BoundBoard:
    name = type(resource).__name__

    if not isinstance(definition, Board):
        raise ImproperlyConfigured(
            f"{name}.boards holds {definition!r}, which is not a "
            f"Board(...)."
        )

    if not isinstance(definition.name, str) or not NAME_PATTERN.match(
        definition.name
    ):
        raise ImproperlyConfigured(
            f"{name}.boards: board name {definition.name!r} must be lower "
            f"case letters, digits and dashes - it is part of an address."
        )

    bound = BoundBoard(definition, resource)

    if isinstance(definition.fields, str) or isinstance(
        definition.columns, str
    ):
        raise ImproperlyConfigured(
            f"{name}.boards: the fields and columns of '{definition.name}' "
            f"are tuples, not one string."
        )

    for entry in (
        *([definition.label] if definition.label else ()),
        *([definition.color] if definition.color else ()),
        *definition.fields,
    ):
        check_entry(resource, "boards", entry)

    if definition.editable:
        from generic.sites.transitions import state_fields

        if definition.field in state_fields(resource):
            raise ImproperlyConfigured(
                f"{name}.boards: '{definition.name}' moves cards "
                f"(editable=True) by '{definition.field}', a state field: "
                f"it changes through its transitions only."
            )

        if definition.field not in set(resource.editable_fields or ()):
            raise ImproperlyConfigured(
                f"{name}.boards: '{definition.name}' moves cards "
                f"(editable=True), so '{definition.field}' must be in "
                f"{name}.editable_fields - the writer it goes through."
            )

    return bound


def board_permission(bound: BoundBoard) -> Any:
    """The board's own permission, and the one its field asks to be
    seen (``field_permissions``): its columns would tell the field's
    value of every card."""
    required = bound.definition.permission
    rules = bound.resource.get_field_permissions()
    view = rules.get(bound.field.name, (None, None))[0]

    if not view:
        return required

    if required is None:
        return view

    if callable(required):
        return lambda user: required(user) and user.has_perm(view)

    names = [required] if isinstance(required, str) else list(required)

    return [*names, view]


def board_page(bound: BoundBoard) -> ResourcePage:
    return ResourcePage(
        bound.name,
        view=BoardPageView,
        title=bound.definition.title or gettext_lazy("Board"),
        icon=bound.definition.icon,
        description=bound.definition.description,
        navigation=bound.definition.navigation,
        permission=board_permission(bound),
    )


class BoardPageView(ResourcePageView):
    """The page of a board, its filters above it."""

    template_name = "generic/resource/board.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        bound = self.resource.get_board(self.page.name)
        context["board"] = bound
        context["board_config"] = bound.get_config(self.request)
        context["board_config"]["filterTable"] = "board-filter-table"
        context["filter_table"] = bound.get_filter_table_config(self.request)

        return context


__all__ = [
    "Board",
    "BoardPageView",
    "BoundBoard",
    "MAX_CARDS",
    "MAX_COLUMNS",
    "bind_board",
]

"""A list unfolding into its related records, edited where they stand.

A supplier, the equipment bought from it, the maintenance visits of
each piece: three tables, three pages - or one view, where each
supplier has an arrow to its equipment and each piece of equipment an
arrow to its visits. Declared on the resource of the top level, by the
relations to walk down::

    auto(Supplier, related=("equipment",),
         outline=("equipment", "maintenances"))

    @register(Customer)
    class CustomerResource(ModelResource):
        outline = Outline(
            Level("tickets", columns=("reference", "title", "status")),
            "time_entries",
            title=_("Tickets and time"),
        )

Each name is a relation of the level above - a reverse foreign key's
related name, or a many-to-many - exactly as ``related`` takes it. The
list page gets an *Outline* button in its table's toolbar: the rows
make way for the outline, which follows the table's filters, search and
order for its first level.

Each level is drawn with its own resource's columns - its own table's,
the same renderers - and the cells its resource lets this reader edit
(``editable_fields``) are their controls, written as a grid writes them
(``PATCH .../<pk>/cells/``, the level resource's ``save_editable``).
Nothing is loaded before it is unfolded: one request a level, a page
at a time, from ``GET api/<app>/<model>/outline/``.

Below the top, a level whose records are kept in an order of their own
- an integer field its ordering starts with, ``position`` say - has
them dragged into another order (``POST .../outline/move/``), and in
edit mode a record opens in a dialog for the fields its row does not
show.

The browser names a level by its number and a record by its key; the
endpoint resolves both through the declaration and the resources' own
querysets, so a reader never sees a record a resource would not list,
nor a level whose model they may not view.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Sequence
from urllib.parse import urlencode

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.db.models import Count, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils.encoding import force_str
from django.utils.translation import gettext
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
    ValidationError,
)

#: The most levels below the top an outline walks.
MAX_LEVELS = 5

#: The most records one request may ask for.
MAX_LIMIT = 200

#: Long texts a level shows besides its visible columns, when it names
#: none.
MAX_TEXT_COLUMNS = 2

#: The annotation carrying how many records of the next level a record
#: has.
CHILDREN = "_outline_children"

#: Where the parent's key goes in a level's *Add* address.
PARENT_TOKEN = "{parent}"


@dataclasses.dataclass(frozen=True)
class Level:
    """One level below the top: the relation reaching it."""

    #: The relation of the level above, by the name it is reached by:
    #: a reverse foreign key's related name, a many-to-many.
    name: str
    #: The columns shown, by their names in the level resource's
    #: ``list_display``; the first one beside the arrow. Default: the
    #: resource's visible columns, without the one pointing back up.
    columns: Sequence[str] | None = None
    #: The heading of the level. Default: the model's plural name.
    title: Any = None
    #: Whether this level's cells are edited in place, where the
    #: resource allows it.
    editable: bool = True
    #: The integer field keeping the records in their order among their
    #: parent's, dragged to change it. Default: the field the level's
    #: ordering starts with (its key back up aside), when it is an
    #: ascending integer field. ``False``: never dragged.
    position: Any = None


class Outline:
    """Declare the levels a list unfolds into.

    ``Outline("equipment", "maintenances")``: each level a relation
    name, or a ``Level`` to say more about it.
    """

    def __init__(
        self,
        *levels: Any,
        title: Any = None,
        columns: Sequence[str] | None = None,
        page_size: int = 25,
        editable: bool = True,
        max_columns: int = 6,
        icon: str = "account_tree",
    ) -> None:
        #: The levels below the top, in order.
        self.levels = tuple(
            level if isinstance(level, Level) else Level(name=level)
            for level in levels
        )
        #: The button's tip and the outline's label. Default:
        #: "Outline".
        self.title = title
        #: The top level's columns, as ``Level.columns``.
        self.columns = (
            columns
            if columns is None or isinstance(columns, str)
            else tuple(columns)
        )
        #: Records per request when a level unfolds; "Show more" asks
        #: for the next ones.
        self.page_size = page_size
        #: Nothing edited at any level when False.
        self.editable = editable
        #: Columns a level shows at most, when none are declared.
        self.max_columns = max_columns
        self.icon = icon

    def __repr__(self) -> str:
        names = ", ".join(repr(level.name) for level in self.levels)

        return f"Outline({names})"


def as_outline(value: Any, owner: str) -> Outline | None:
    """What a resource's ``outline`` says, as an ``Outline``."""
    if value in (None, False, (), ""):
        return None

    if isinstance(value, Outline):
        return value

    if isinstance(value, (str, Level)):
        return Outline(value)

    if isinstance(value, (list, tuple)):
        return Outline(*value)

    raise ImproperlyConfigured(
        f"{owner}.outline is {value!r}: relation names, or "
        f"Outline(...), are expected."
    )


def relation_of(model: Any, name: Any, where: str) -> tuple[Any, str]:
    """The model ``name`` reaches from ``model``, and the name leading
    back from it - what its rows are filtered on."""
    if not isinstance(name, str) or not name:
        raise ImproperlyConfigured(
            f"{where} holds {name!r}: a relation's name is expected."
        )

    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        choices = sorted(
            field.name
            for field in model._meta.get_fields()
            if field.is_relation and (field.one_to_many or field.many_to_many)
        )
        raise ImproperlyConfigured(
            f"{where} names '{name}', which is not a relation of "
            f"{model.__name__}. It takes the name a relation is reached "
            f"by from {model.__name__}: {', '.join(choices) or 'none'}."
        ) from None

    if not (field.is_relation and (field.one_to_many or field.many_to_many)):
        raise ImproperlyConfigured(
            f"{where} names '{name}', which holds one record, not rows: "
            f"an outline unfolds a record into several."
        )

    if field.auto_created:
        # A reverse relation: the field on the other side points here.
        back = field.field.name
    else:
        # A many-to-many declared on this model.
        back = field.related_query_name()

    return field.related_model, back


@dataclasses.dataclass
class OutlineLevel:
    """One level, resolved: its model and the way back to its parent."""

    index: int
    #: The relation reaching it; "" for the top.
    name: str
    model: Any
    #: The lookup from this level's records to their parent's key.
    back: str
    declared: Level | None

    def is_foreign_key(self) -> bool:
        """Whether each record has one parent, by a field of its own:
        it can then be added with its parent filled in."""
        try:
            field = self.model._meta.get_field(self.back)
        except FieldDoesNotExist:
            return False

        return bool(field.many_to_one and not field.auto_created)


def check(resource: Any) -> Any:
    """Resolve the declaration against the models, at registration.

    The resources of the levels may be registered after this one: they
    are found when the outline is first drawn.
    """
    where = f"{type(resource).__name__}.outline"
    resolved = resolve(
        resource.model, getattr(resource, "outline", None), where
    )

    if resolved is None:
        return None

    outline, levels = resolved

    return BoundOutline(
        outline=outline, resource=resource, levels=levels, where=where
    )


def resolve(
    model: Any, value: Any, where: str, top_back: str = ""
) -> tuple[Outline, list[OutlineLevel]] | None:
    """The outline ``value`` declares from ``model``, its levels
    resolved; None when it declares none.

    ``top_back`` is the field of the top level's records pointing at a
    record they all belong to (a related table's): its column is left
    out, saying the same thing on every row.
    """
    outline = as_outline(value, where.rpartition(".")[0] or where)

    if outline is None:
        return None

    if not outline.levels:
        raise ImproperlyConfigured(
            f"{where} names no level: give it the relations to unfold, "
            f"Outline('equipment', 'maintenances')."
        )

    if len(outline.levels) > MAX_LEVELS:
        raise ImproperlyConfigured(
            f"{where} has {len(outline.levels)} levels below the top; "
            f"{MAX_LEVELS} at most."
        )

    if not 1 <= outline.page_size <= MAX_LIMIT:
        raise ImproperlyConfigured(
            f"{where}: page_size must be between 1 and {MAX_LIMIT}."
        )

    if outline.max_columns < 1:
        raise ImproperlyConfigured(f"{where}: max_columns must be 1 or more.")

    levels = [
        OutlineLevel(
            index=0, name="", model=model, back=top_back, declared=None
        )
    ]

    for index, declared in enumerate(outline.levels, start=1):
        model, back = relation_of(model, declared.name, where)
        levels.append(
            OutlineLevel(
                index=index,
                name=declared.name,
                model=model,
                back=back,
                declared=declared,
            )
        )

    for level in levels:
        columns = (
            outline.columns
            if level.declared is None
            else level.declared.columns
        )

        if columns is not None and (
            isinstance(columns, str)
            or not all(isinstance(name, str) for name in columns)
        ):
            raise ImproperlyConfigured(
                f"{where}: the columns of '{level.name or 'the top'}' are "
                f"column names, in a tuple."
            )

    for level in levels[1:]:
        position = level.declared.position if level.declared else None

        if position in (None, False):
            continue

        if not level.is_foreign_key():
            raise ImproperlyConfigured(
                f"{where}: '{level.name}' is not reached by a foreign key: "
                f"its records have no order of their own among a parent's."
            )

        if not is_position_field(level.model, position):
            raise ImproperlyConfigured(
                f"{where}: the position of '{level.name}' is {position!r}, "
                f"which is not an integer field of {level.model.__name__}."
            )

    return outline, levels


def is_text_field(model: Any, name: Any) -> bool:
    try:
        field = model._meta.get_field(name)
    except (FieldDoesNotExist, TypeError):
        return False

    return isinstance(field, models.TextField)


def is_position_field(model: Any, name: Any) -> bool:
    """Whether ``name`` is a field a record's place can be written in."""
    if not isinstance(name, str) or "__" in name:
        return False

    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return False

    return bool(
        isinstance(field, models.IntegerField)
        and field.concrete
        and field.editable
        and not field.primary_key
        and not isinstance(field, models.AutoField)
    )


def tail(outline: Outline, levels: list[OutlineLevel]) -> Outline | None:
    """The outline below its first level, drawn from that level: what a
    record's table of those rows unfolds into. None when nothing is
    left to unfold."""
    if len(levels) < 3:
        return None

    first = outline.levels[0]

    return Outline(
        *outline.levels[1:],
        title=outline.title,
        columns=first.columns,
        page_size=outline.page_size,
        editable=outline.editable and first.editable,
        max_columns=outline.max_columns,
        icon=outline.icon,
    )


def read_number(value: Any, name: str, default: int) -> int:
    if value in (None, ""):
        return default

    try:
        number = int(value)
    except (TypeError, ValueError):
        number = -1

    if number < 0:
        raise ValidationError({name: [gettext("A whole number is expected.")]})

    return number


@dataclasses.dataclass
class BoundOutline:
    """An outline resolved against the resource of its top level."""

    outline: Outline
    resource: Any
    levels: list[OutlineLevel]
    #: The declaration, as errors name it.
    where: str = ""

    @property
    def site(self) -> Any:
        return self.resource.site

    def get_title(self) -> str:
        if self.outline.title:
            return force_str(self.outline.title)

        return gettext("Outline")

    def resource_of(self, level: OutlineLevel) -> Any:
        if level.index == 0:
            return self.resource

        resource = self.site.get_resource(level.model)

        if resource is None:
            raise ImproperlyConfigured(
                f"{self.where} unfolds into "
                f"{level.model.__name__} ('{level.name}'), which is not "
                f"registered: register it, show_in_navigation=False if "
                f"it is only reached from here."
            )

        return resource

    def get_levels(self, request: Any) -> list[OutlineLevel]:
        """The levels this reader may see: down to the first whose
        records they may not view."""
        shown = []

        for level in self.levels:
            if not self.resource_of(level).has_view_permission(request):
                break

            shown.append(level)

        return shown

    def is_visible(self, request: Any) -> bool:
        """Something to unfold: the top and at least one level."""
        return len(self.get_levels(request)) > 1

    def is_editable(self, level: OutlineLevel) -> bool:
        """What the declaration says about writing the level."""
        return self.outline.editable and (
            level.declared is None or level.declared.editable
        )

    # -- the order of a level -----------------------------------------

    def position_of(self, level: OutlineLevel) -> str | None:
        """The field keeping the level's records in order, if any."""
        if level.index == 0 or not level.is_foreign_key():
            return None

        declared = level.declared.position if level.declared else None

        if declared is False:
            return None

        if isinstance(declared, str):
            return declared

        resource = self.resource_of(level)
        back = level.back.split("__")[0]
        ordering = [
            name
            for name in (resource.ordering or level.model._meta.ordering or ())
            if isinstance(name, str) and name not in (back, f"{back}_id")
        ]

        if ordering and is_position_field(level.model, ordering[0]):
            return ordering[0]

        return None

    def may_move(self, request: Any, level: OutlineLevel) -> bool:
        """Whether this reader may drag the level's records."""
        position = self.position_of(level)

        if position is None or not self.is_editable(level):
            return False

        resource = self.resource_of(level)

        return bool(
            resource.has_change_permission(request)
            and position not in resource.get_readonly_fields(request)
            and resource.may_write_column(request, position)
        )

    # -- columns ------------------------------------------------------

    def declared_columns(self, level: OutlineLevel) -> Sequence[str] | None:
        if level.declared is None:
            return self.outline.columns

        return level.declared.columns

    def get_columns(
        self, request: Any, level: OutlineLevel
    ) -> list[dict[str, Any]]:
        """The level's columns, as its own table describes them."""
        resource = self.resource_of(level)
        table = resource.get_table_config(request, editable=False)
        known = {
            column.get("data"): column
            for column in table["columns"]
            if column.get("data")
        }
        declared = self.declared_columns(level)

        if declared is not None:
            missing = [name for name in declared if name not in known]
            hidden = set(resource.get_hidden_fields(request) or ())
            unknown = [name for name in missing if name not in hidden]

            if unknown:
                raise ImproperlyConfigured(
                    f"{self.where} shows "
                    f"'{unknown[0]}' of {level.model.__name__}, which is "
                    f"not a column of its list."
                )

            names = [name for name in declared if name in known]
        else:
            back = level.back.split("__")[0]
            names = [
                name
                for name, column in known.items()
                if column.get("visible", True) is not False and name != back
            ][: self.outline.max_columns]
            # A long text the list starts without - a comment's body -
            # is what an outline of such records is read for.
            names += [
                name
                for name, column in known.items()
                if column.get("visible", True) is False
                and is_text_field(level.model, name)
            ][:MAX_TEXT_COLUMNS]

        return [dict(known[name]) for name in names]

    def get_editing(
        self,
        request: Any,
        level: OutlineLevel,
        columns: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        """What this reader may write in the level: its cells' schemas,
        the form its records open in, whether they are dragged."""
        if not self.is_editable(level):
            return {}

        resource = self.resource_of(level)
        editing: dict[str, Any] = {}

        if resource.has_change_permission(request):
            editing["changeUrl"] = resource.get_change_url_template()

        if self.may_move(request, level):
            editing["movable"] = True

        options = resource.get_editable_options(request)
        shown = {column.get("data") for column in columns}
        described = {
            name: schema
            for name, schema in (options.get("editable") or {}).items()
            if name in shown
        }

        if described:
            editing["editable"] = described
            editing["editableUrl"] = options["editableUrl"]

        return editing

    def get_add_url(
        self, request: Any, level: OutlineLevel, back: str | None = None
    ) -> str:
        """A new record of the level, its parent filled in, back to
        ``back`` once saved (default: the list); ``{parent}`` stands for
        the parent's key."""
        from generic.sites.related import NEXT_PARAM

        if level.index == 0 or not level.is_foreign_key():
            return ""

        resource = self.resource_of(level)

        if not resource.has_add_permission(request):
            return ""

        url = resource.get_add_url()

        if not url:
            return ""

        query = {level.back: "__parent__"}

        if back is None:
            back = self.resource.get_list_url()

        if back:
            query[NEXT_PARAM] = back

        return f"{url}?{urlencode(query)}".replace("__parent__", PARENT_TOKEN)

    def get_title_of(self, level: OutlineLevel) -> str:
        if level.declared is not None and level.declared.title:
            return force_str(level.declared.title)

        return self.resource_of(level).get_label_plural()

    # -- the browser's configuration ----------------------------------

    def get_url(self) -> str:
        return self.resource._reverse(self.resource.api_url_name("outline"))

    def get_move_url(self) -> str:
        return self.resource._reverse(
            self.resource.api_url_name("outline-move")
        )

    def get_config(
        self, request: Any, back: str | None = None
    ) -> dict[str, Any] | None:
        """What the list page needs to draw the outline, or None when
        there is nothing for this reader to unfold. ``back``: where an
        *Add* returns, default the list."""
        levels = self.get_levels(request)

        if len(levels) < 2:
            return None

        described = []
        topics = []

        for level in levels:
            resource = self.resource_of(level)
            columns = self.get_columns(request, level)
            entry = {
                "name": level.name,
                "resource": resource.label_lower,
                "title": self.get_title_of(level),
                "label": resource.get_label(),
                "columns": columns,
                "addUrl": self.get_add_url(request, level, back),
                "rowKey": "_pk",
            }
            entry.update(self.get_editing(request, level, columns))
            described.append(entry)

            if resource.realtime and resource.topic_name not in topics:
                topics.append(resource.topic_name)

        return {
            "url": self.get_url(),
            "moveUrl": self.get_move_url(),
            "title": self.get_title(),
            "icon": self.outline.icon,
            "pageSize": self.outline.page_size,
            "levels": described,
            "topics": topics,
        }

    # -- the endpoint -------------------------------------------------

    def count_of(self, request: Any, level: OutlineLevel) -> Any:
        """How many records of ``level`` each record above has, as an
        annotation of the level above."""
        resource = self.resource_of(level)
        counted = (
            resource.get_queryset(request)
            .filter(**{level.back: OuterRef("pk")})
            .order_by()
            .values(level.back)
            .annotate(total=Count("pk", distinct=True))
            .values("total")[:1]
        )

        return Coalesce(Subquery(counted), 0)

    def get_ordering(self, request: Any, level: OutlineLevel) -> list[str]:
        position = self.position_of(level)

        if position is not None:
            return [position, "pk"]

        resource = self.resource_of(level)
        ordering = resource.get_ordering(request) or (
            level.model._meta.ordering
        )

        return [*(ordering or ()), "pk"]

    def find_parent(
        self, request: Any, level: OutlineLevel, value: Any
    ) -> Any:
        """The record of ``level`` a parameter names, if the reader may
        see it."""
        if value in (None, ""):
            raise ValidationError(
                {"parent": [gettext("Name the record to unfold.")]}
            )

        resource = self.resource_of(level)

        try:
            return resource.get_queryset(request).get(pk=value)
        except (
            level.model.DoesNotExist,
            ValueError,
            TypeError,
            DjangoValidationError,
        ):
            raise NotFound(gettext("There is no such record.")) from None

    def answer(
        self,
        request: Any,
        params: Any,
        top: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """One page of one level: the top's rows (``top``, the table's
        rows, filtered and ordered), or a record's children.

        ``level`` is the level's number (0: the top); ``parent`` the key
        of the record unfolded, from the level above; ``offset``,
        ``limit``.
        """
        from generic.sites.summary import record_url

        levels = self.get_levels(request)
        number = read_number(params.get("level"), "level", 0)

        if number >= len(levels):
            raise NotFound(gettext("There is no such level."))

        offset = read_number(params.get("offset"), "offset", 0)
        limit = read_number(
            params.get("limit"), "limit", self.outline.page_size
        )
        limit = max(1, min(limit, MAX_LIMIT))
        level = levels[number]
        resource = self.resource_of(level)

        if number == 0:
            rows = top
        else:
            parent = self.find_parent(
                request, levels[number - 1], params.get("parent")
            )
            rows = (
                resource.get_list_queryset(request)
                .filter(**{level.back: parent.pk})
                .order_by(*self.get_ordering(request, level))
            )

        total = rows.count()
        below = levels[number + 1] if number + 1 < len(levels) else None

        if below is not None:
            rows = rows.annotate(**{CHILDREN: self.count_of(request, below)})

        page = list(rows[offset : offset + limit])
        serializer = resource.get_rows_serializer_class(request)(
            page, many=True, context=context
        )

        return {
            "level": number,
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": [
                {
                    "id": force_str(obj.pk),
                    "url": record_url(self.site, request, obj),
                    "children": getattr(obj, CHILDREN, 0) or 0,
                    "row": data,
                }
                for obj, data in zip(page, serializer.data)
            ],
        }

    def move(self, request: Any, data: Any) -> dict[str, Any]:
        """Put one record of a level before another of the same parent
        (``before``), after one (``after``), or last (neither):
        ``{level, parent, id, before | after}``.

        The parent's records this reader may see keep the positions
        they had between them, given out again in the new order; only
        the ones whose place changed are written, each one saved -
        history and live updates follow - and each one asked for.
        """
        levels = self.get_levels(request)
        number = read_number(data.get("level"), "level", 0)

        if not 0 < number < len(levels):
            raise NotFound(gettext("There is no such level."))

        level = levels[number]

        if not self.may_move(request, level):
            raise PermissionDenied(
                gettext("These records are not put in order here.")
            )

        position = self.position_of(level) or ""
        resource = self.resource_of(level)
        parent = self.find_parent(
            request, levels[number - 1], data.get("parent")
        )
        siblings = list(
            resource.get_queryset(request)
            .filter(**{level.back: parent.pk})
            .order_by(*self.get_ordering(request, level))
        )
        keys = [force_str(obj.pk) for obj in siblings]
        moved = force_str(data.get("id", ""))

        if moved not in keys:
            raise NotFound(gettext("There is no such record."))

        record = siblings.pop(keys.index(moved))
        keys.remove(moved)
        place = len(siblings)

        for name, shift in (("before", 0), ("after", 1)):
            other = data.get(name)

            if other in (None, ""):
                continue

            other = force_str(other)

            if other not in keys:
                raise ValidationError(
                    {name: [gettext("Name another record of this level.")]}
                )

            place = keys.index(other) + shift
            break

        siblings.insert(place, record)

        places = sorted(getattr(obj, position) or 0 for obj in siblings)

        # Every record somewhere else: the order is given anew.
        if len(set(places)) < len(places):
            places = list(range(1, len(siblings) + 1))

        changed = [
            (obj, place)
            for obj, place in zip(siblings, places)
            if getattr(obj, position) != place
        ]

        for obj, _place in changed:
            if not (
                resource.has_change_permission(request, obj)
                and resource.may_write_column(request, position, obj)
            ):
                raise PermissionDenied

        if changed:
            with transaction.atomic():
                # Out of the way first: a position may be unique among a
                # parent's records, and two of them would meet midway.
                top = (
                    level.model._default_manager.aggregate(
                        highest=Max(position)
                    )["highest"]
                    or 0
                )
                for offset, (obj, _place) in enumerate(changed, start=1):
                    level.model._default_manager.filter(pk=obj.pk).update(
                        **{position: top + offset}
                    )

                for obj, place in changed:
                    setattr(obj, position, place)
                    obj.save(update_fields=[position])

        return {
            "level": number,
            "moved": len(changed),
            "order": [force_str(obj.pk) for obj in siblings],
        }

    def models(self) -> list[Any]:
        """The models below the top, in order."""
        return [level.model for level in self.levels[1:]]


__all__ = ["Level", "Outline", "as_outline", "check", "resolve", "tail"]

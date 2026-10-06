"""Records holding other records, as a tree that unfolds.

Two shapes of hierarchy, declared on the resource of the records the
tree is made of::

    # A model pointing at its parent: a category inside a category.
    @register(Family)
    class FamilyResource(ModelResource):
        trees = (Tree("families", parent="parent", title=_("Families")),)

    # A link model between two records of the same model, carrying what
    # the link says - a bill of materials, where a part goes into many
    # assemblies, each time in its own quantity.
    @register(Article)
    class ArticleResource(ModelResource):
        trees = (
            Tree(
                "bom",
                through=BomLine,
                parent="parent",
                child="child",
                title=_("Bill of materials"),
                columns=("kind", "unit_cost"),
                link_columns=("position", "quantity"),
                ordering=("position", "child__reference"),
                where_used=True,
            ),
        )

Each tree is a tab on a record's summary page (what it holds, and with
``where_used`` what holds it) and a page of the whole tree, from the
records nothing holds. Nothing is loaded before it is unfolded: a
level is one request, served a page at a time, so an assembly of
several thousand parts opens as fast as one of three, and can be
searched without loading the rest.

The browser names the tree and a record; the endpoint - ``GET
api/<app>/<model>/trees/<name>/`` - resolves both through the
declaration and the resources' own querysets, so a reader never sees a
record, or a link, the resources would not list.

A link that would make a record part of itself is refused by every
form, table cell and import of the model holding the links: a tree
unfolded by hand would never end. The tree is drawn defensively too: a
record met again below itself - data written some other way - is shown
once, and not unfolded.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Sequence

from django.core.exceptions import (
    FieldDoesNotExist,
    ImproperlyConfigured,
)
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils.encoding import force_str
from django.utils.text import capfirst
from django.utils.translation import gettext, gettext_lazy
from rest_framework.exceptions import NotFound, ValidationError

from generic.api.filters import apply_search
from generic.sites.pages import ResourcePage, ResourcePageView

#: A tree's name is a piece of its endpoint's address and of its page's.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: The most records one request may ask for.
MAX_LIMIT = 500

#: The most ancestors a request may name to mark a record met twice.
MAX_PATH = 200

#: Unfolding upwards - what holds a record - rather than downwards.
DOWN = "down"
UP = "up"

#: The annotation carrying how many records a record holds.
CHILDREN = "_tree_children"

#: How many records a cycle check walks before giving up: past it, the
#: link is let through rather than the save taking forever.
MAX_WALK = 200_000

#: Keys looked up per query while walking down a tree.
WALK_CHUNK = 500


@dataclasses.dataclass(frozen=True)
class Tree:
    """Declare one tree of the resource's records."""

    #: Lower case letters, digits and dashes: the tree's endpoint is
    #: ``trees/<name>/``, its page ``<name>/``.
    name: str
    #: The foreign key to the record holding this one - on the model
    #: itself, or on ``through``.
    parent: str = "parent"
    #: A model linking two records - parent, child, and whatever the
    #: link says (a quantity). None: the model points at its parent.
    through: Any = None
    #: With ``through``: its foreign key to the record held.
    child: str | None = None
    title: Any = None
    icon: str = "account_tree"
    description: Any = ""
    #: Values of each record beside its name: fields, resource methods,
    #: model attributes - what a summary page section may show.
    columns: Sequence[str] = ()
    #: Values of each link, the same way: ``("quantity",)``.
    link_columns: Sequence[str] = ()
    #: The order of a record's children: fields of the link (or of the
    #: model, without ``through``). Default: the model's own.
    ordering: Sequence[str] | None = None
    #: What a level's search box looks through. Default: the
    #: resource's ``search_fields``.
    search_fields: Sequence[str] | None = None
    #: Records per request when a level unfolds; "Show more" asks for
    #: the next ones.
    page_size: int = 50
    #: The records the page of the whole tree starts from: a callable
    #: ``(request, queryset) -> queryset``, or the name of a resource
    #: method. Default: the records nothing holds.
    roots: Any = None
    #: A tab on each record's summary page.
    tab: bool = True
    #: A page of the whole tree, a button on the list.
    page: bool = True
    #: A second tab: what holds the record, unfolding upwards.
    where_used: bool = False
    where_used_title: Any = None
    #: An "Add" on the tab, creating a link (a child, without
    #: ``through``) with this record as its parent.
    allow_add: bool = True


def entry_label(resource: Any, model: Any, name: str) -> str:
    """The heading of a column: the field's name, or the method's."""
    from generic.sites.serializers import resolve_display_callable

    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        field = None

    if field is not None:
        label = getattr(field, "verbose_name", None) or name
    else:
        function = resolve_display_callable(name, resource, model)
        label = getattr(function, "short_description", None) or (
            name.replace("_", " ")
        )

    return capfirst(force_str(label))


def foreign_key(model: Any, name: str, target: Any, where: str) -> Any:
    """``model.<name>``, checked to be a foreign key to ``target``."""
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        raise ImproperlyConfigured(
            f"{where} names '{name}', which is not a field of "
            f"{model.__name__}."
        ) from None

    if not (
        field.is_relation
        and field.many_to_one
        and issubclass(target, field.related_model)
    ):
        raise ImproperlyConfigured(
            f"{where}: {model.__name__}.{name} must be a foreign key to "
            f"{target.__name__}."
        )

    return field


@dataclasses.dataclass
class BoundTree:
    """A tree resolved against the resource it belongs to."""

    definition: Tree
    resource: Any
    #: The model holding the links: ``through``, or the model itself.
    link_model: Any
    parent_field: Any
    #: The link's key to the record held; None when the model points at
    #: its parent (the link is then the record itself).
    child_field: Any

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def model(self) -> Any:
        return self.resource.model

    @property
    def linked(self) -> bool:
        """Whether a link model sits between parent and child."""
        return self.child_field is not None

    # -- naming --------------------------------------------------------

    def get_title(self) -> str:
        if self.definition.title:
            return force_str(self.definition.title)

        return capfirst(self.name.replace("-", " "))

    def get_where_used_title(self) -> str:
        if self.definition.where_used_title:
            return force_str(self.definition.where_used_title)

        return gettext("Where used")

    def tab_name(self, direction: str = DOWN) -> str:
        """The tab's name on a summary page, apart from related tables'."""
        return f"tree-{self.name}" + ("-up" if direction == UP else "")

    def get_link_resource(self) -> Any:
        if not self.linked:
            return None

        return self.resource.site.get_resource(self.link_model)

    def get_columns(self, request: Any) -> list[dict[str, str]]:
        """The headings beside the records' names, in order."""
        columns = [
            {
                "key": f"link.{name}",
                "label": entry_label(
                    self.get_link_resource(), self.link_model, name
                ),
            }
            for name in self.get_link_columns(request)
        ]
        columns += [
            {
                "key": f"node.{name}",
                "label": entry_label(self.resource, self.model, name),
            }
            for name in self.definition.columns
        ]

        return columns

    def get_link_columns(self, request: Any) -> Sequence[str]:
        """The link's values, for whoever may read the links."""
        if not self.linked or not self.definition.link_columns:
            return ()

        link_resource = self.get_link_resource()

        if link_resource is not None and not (
            link_resource.has_view_permission(request)
        ):
            return ()

        return tuple(self.definition.link_columns)

    # -- what a reader sees --------------------------------------------

    def visible(self, request: Any) -> Any:
        """The records this reader may see."""
        return self.resource.get_queryset(request)

    def links(self, request: Any) -> Any:
        """The links this reader may see: the link resource's own rows,
        between records they may see."""
        link_resource = self.get_link_resource()
        queryset = (
            link_resource.get_queryset(request)
            if link_resource is not None
            else self.link_model._default_manager.all()
        )
        pks = self.visible(request).values("pk")

        return queryset.filter(
            **{
                f"{self.parent_field.name}__in": pks,
                f"{self.child_field.name}__in": pks,
            }
        )

    def fields(self, direction: str) -> tuple[str, str]:
        """The link's key to the record unfolded, and to those listed."""
        parent = self.parent_field.name
        child = self.child_field.name

        return (parent, child) if direction == DOWN else (child, parent)

    def children_count(self, request: Any, direction: str, outer: str) -> Any:
        """How many records the record at ``outer`` holds (or, upwards,
        is held by), as an annotation."""
        if self.linked:
            near, _far = self.fields(direction)
            queryset = self.links(request).filter(**{near: OuterRef(outer)})
        elif direction == DOWN:
            near = self.parent_field.name
            queryset = self.visible(request).filter(**{near: OuterRef(outer)})
        else:
            # Upwards, a record pointing at its parent is held by one.
            near = "pk"
            queryset = self.visible(request).filter(
                pk=OuterRef(self.parent_field.attname)
            )

        counted = (
            queryset.order_by()
            .values(near)
            .annotate(total=Count("pk"))
            .values("total")[:1]
        )

        return Coalesce(Subquery(counted), 0)

    def count(self, request: Any, obj: Any, direction: str = DOWN) -> int:
        """How many records ``obj`` holds - or, upwards, is held by."""
        return self.rows(request, obj, direction).count()

    def rows(self, request: Any, obj: Any, direction: str) -> Any:
        """The rows listing what ``obj`` holds: links, or records."""
        if self.linked:
            near, _far = self.fields(direction)

            return self.links(request).filter(**{near: obj.pk})

        if direction == DOWN:
            return self.visible(request).filter(
                **{self.parent_field.name: obj.pk}
            )

        parent_pk = getattr(obj, self.parent_field.attname)

        return self.visible(request).filter(pk=parent_pk)

    def get_roots(self, request: Any) -> Any:
        """The records the page of the whole tree starts from."""
        queryset = self.visible(request)
        roots = self.definition.roots

        if isinstance(roots, str):
            return getattr(self.resource, roots)(request, queryset)

        if callable(roots):
            return roots(request, queryset)

        if self.linked:
            # Held by a record this reader cannot see: a root, for them.
            held = self.links(request).values(self.child_field.name)

            return queryset.exclude(pk__in=held)

        return queryset.filter(**{f"{self.parent_field.name}__isnull": True})

    def get_search_fields(self, request: Any) -> Sequence[str]:
        if self.definition.search_fields is not None:
            return tuple(self.definition.search_fields)

        fields = self.resource.get_search_fields(request)

        if fields:
            return tuple(fields)

        return tuple(
            self.resource.get_table_serializer_class().get_search_fields()
        )

    def get_node_ordering(self, request: Any) -> list[str]:
        """How records are ordered where no link says otherwise."""
        ordering = self.resource.get_ordering(request) or (
            self.model._meta.ordering
        )

        return [*(ordering or ()), "pk"]

    def get_ordering(self, request: Any, direction: str) -> list[str]:
        """How the records a record holds are ordered: by the link, or -
        upwards, where links of many holders mix - by the holder."""
        if self.linked and direction == UP:
            _near, far = self.fields(UP)

            return [
                (
                    f"-{far}__{name[1:]}"
                    if name.startswith("-")
                    else f"{far}__{name}"
                )
                for name in self.get_node_ordering(request)
            ]

        if self.definition.ordering:
            return [*self.definition.ordering, "pk"]

        if self.linked:
            return [*(self.link_model._meta.ordering or ()), "pk"]

        return self.get_node_ordering(request)

    # -- the endpoint --------------------------------------------------

    def answer(self, request: Any, params: Any) -> dict[str, Any]:
        """One level of the tree, a page of it: what the endpoint says.

        ``node`` names the record unfolded - none, the roots; ``root``
        asks for one record alone, the top of a tree shown from it;
        ``direction`` is ``down`` or ``up``; ``offset``, ``limit``;
        ``q`` searches the level; ``path`` names the records above, so
        one met again is marked rather than unfolded.
        """
        direction = params.get("direction") or DOWN

        if direction not in (DOWN, UP) or (
            direction == UP and not self.definition.where_used
        ):
            raise ValidationError(
                {"direction": [gettext("This direction is not offered.")]}
            )

        offset = read_number(params.get("offset"), "offset", 0)
        limit = read_number(
            params.get("limit"), "limit", self.definition.page_size
        )
        limit = max(1, min(limit, MAX_LIMIT))
        term = (params.get("q") or "").strip()
        path = [
            value
            for value in (params.get("path") or "").split(",")[:MAX_PATH]
            if value
        ]
        node = self.find(request, params.get("node"))
        root = self.find(request, params.get("root"))
        visible = self.visible(request)

        if node is not None:
            path.append(force_str(node.pk))

        if root is not None:
            rows = visible.filter(pk=root.pk)
            listed = "pk"
        elif node is not None:
            rows = self.rows(request, node, direction)
            listed = self.fields(direction)[1] if self.linked else "pk"
        else:
            rows = self.get_roots(request)
            listed = "pk"

        if term:
            matching = apply_search(
                visible, self.get_search_fields(request), term
            ).values("pk")
            rows = rows.filter(**{f"{listed}__in": matching})

        total = rows.count()
        linking = self.linked and listed != "pk"

        if linking:
            rows = rows.select_related(listed).order_by(
                *self.get_ordering(request, direction)
            )
        elif self.linked or root is not None or node is None:
            # Records, not links: the roots, or the one record asked for.
            rows = rows.order_by(*self.get_node_ordering(request))
        else:
            rows = rows.order_by(*self.get_ordering(request, direction))

        rows = rows.annotate(
            **{CHILDREN: self.children_count(request, direction, listed)}
        )

        page = list(rows[offset : offset + limit])
        seen = set(path)

        return {
            "node": force_str(node.pk) if node is not None else None,
            "direction": direction,
            "total": total,
            "offset": offset,
            "limit": limit,
            "columns": self.get_columns(request),
            "items": [
                self.describe(
                    request,
                    getattr(row, listed) if linking else row,
                    row if linking else None,
                    getattr(row, CHILDREN),
                    seen,
                )
                for row in page
            ],
        }

    def find(self, request: Any, value: Any) -> Any:
        """The record a parameter names, if this reader may see it."""
        if value in (None, ""):
            return None

        try:
            return self.visible(request).get(pk=value)
        except (
            self.model.DoesNotExist,
            ValueError,
            TypeError,
            DjangoValidationError,
        ):
            raise NotFound(gettext("There is no such record.")) from None

    def describe(
        self,
        request: Any,
        obj: Any,
        link: Any,
        children: int,
        seen: set[str],
    ) -> dict[str, Any]:
        """One record of a level, with its link and its values."""
        from generic.sites.summary import describe_entry, record_url

        pk = force_str(obj.pk)
        cycle = pk in seen
        cells = [
            describe_link_entry(self, request, link, name)
            for name in self.get_link_columns(request)
        ]
        cells += [
            describe_entry(self.resource, request, obj, name)
            for name in self.definition.columns
        ]
        item = {
            "key": force_str(link.pk) if link is not None else pk,
            "id": pk,
            "label": self.resource.get_object_label(obj),
            "url": record_url(self.resource.site, request, obj),
            "children": 0 if cycle else children,
            "cycle": cycle,
            "cells": [
                {
                    key: value
                    for key, value in cell.items()
                    if key not in ("name", "label", "wide")
                }
                for cell in cells
            ],
            "linkUrl": "",
        }
        link_resource = self.get_link_resource()

        if link is not None and link_resource is not None:
            if link_resource.has_change_permission(request, link):
                item["linkUrl"] = link_resource.get_change_url(link.pk)

        return item

    # -- where it shows -------------------------------------------------

    def is_visible(self, request: Any) -> bool:
        return self.resource.has_view_permission(request)

    def get_api_url(self) -> str:
        return self.resource._reverse(
            self.resource.api_url_name("tree"), tree=self.name
        )

    def get_page_url(self) -> str:
        if not self.definition.page:
            return ""

        return self.resource.get_page_url(self.name)

    def get_config(
        self,
        request: Any,
        obj: Any = None,
        direction: str = DOWN,
        root: Any = None,
    ) -> dict[str, Any]:
        """What the browser needs to draw the tree.

        ``obj``: the record whose children are listed first (a tab);
        ``root``: one record shown at the top, unfolded (the page).
        """
        topics = [self.resource.topic_name] if self.resource.realtime else []
        link_resource = self.get_link_resource()

        if link_resource is not None and link_resource.realtime:
            topics.append(link_resource.topic_name)

        return {
            "name": self.name,
            "url": self.get_api_url(),
            "node": force_str(obj.pk) if obj is not None else None,
            "root": force_str(root.pk) if root is not None else None,
            "direction": direction,
            "pageSize": self.definition.page_size,
            "label": self.resource.get_label(),
            "columns": self.get_columns(request),
            "resources": [
                self.resource.label_lower,
                *([link_resource.label_lower] if link_resource else []),
            ],
            "topics": topics,
        }

    def get_add_url(self, request: Any, obj: Any) -> str:
        """A new link - a new child, without one - with ``obj`` as its
        parent, back to the tab once saved."""
        from urllib.parse import urlencode

        from generic.sites.related import NEXT_PARAM

        target = self.get_link_resource() if self.linked else self.resource

        if not (
            self.definition.allow_add
            and target is not None
            and target.has_add_permission(request)
        ):
            return ""

        url = target.get_add_url()

        if not url:
            return ""

        query = {self.parent_field.name: obj.pk}
        back = self.resource.get_object_url(obj.pk)

        if back:
            query[NEXT_PARAM] = f"{back}#related-{self.tab_name()}"

        return f"{url}?{urlencode(query)}"

    def get_tabs(self, request: Any, obj: Any) -> list[dict[str, Any]]:
        """The summary page's tabs of this tree, for ``obj``."""
        if not (self.definition.tab and self.is_visible(request)):
            return []

        tabs = [
            {
                "name": self.tab_name(DOWN),
                "kind": "tree",
                "title": self.get_title(),
                "icon": self.definition.icon,
                "description": force_str(self.definition.description),
                "count": self.count(request, obj, DOWN),
                "addUrl": self.get_add_url(request, obj),
                "pageUrl": self.get_record_page_url(obj),
            }
        ]

        if self.definition.where_used:
            tabs.append(
                {
                    "name": self.tab_name(UP),
                    "kind": "tree",
                    "title": self.get_where_used_title(),
                    "icon": "call_split",
                    "description": "",
                    "count": self.count(request, obj, UP),
                    "addUrl": "",
                    "pageUrl": "",
                }
            )

        return tabs

    def get_record_page_url(self, obj: Any) -> str:
        """The page of the whole tree, from ``obj``."""
        from urllib.parse import urlencode

        url = self.get_page_url()

        return f"{url}?{urlencode({'root': obj.pk})}" if url else ""

    def get_panels(self, request: Any, obj: Any) -> list[dict[str, Any]]:
        """What the summary page draws in each tab: its config."""
        if not (self.definition.tab and self.is_visible(request)):
            return []

        directions = [DOWN, UP] if self.definition.where_used else [DOWN]

        return [
            {
                "name": self.tab_name(direction),
                "config_id": f"related-{self.tab_name(direction)}-config",
                "config": self.get_config(request, obj, direction),
            }
            for direction in directions
        ]

    # -- writes ---------------------------------------------------------

    def check_write(self, instance: Any, attrs: dict[str, Any]) -> None:
        """Refuse a link making a record part of itself."""
        parent_name = self.parent_field.name

        def current(name: str) -> Any:
            if name in attrs:
                return attrs[name]

            return getattr(instance, name, None) if instance else None

        if self.linked:
            parent = current(parent_name)
            child = current(self.child_field.name)
            field = self.child_field.name
            ignore = instance.pk if instance is not None else None
        else:
            if instance is None or instance.pk is None:
                # A new record holds nothing yet.
                return

            parent = current(parent_name)
            child = instance
            field = parent_name
            ignore = None

        if parent is None or child is None:
            return

        if parent.pk == child.pk:
            raise ValidationError(
                {field: [gettext("A record cannot contain itself.")]}
            )

        if self.holds(child.pk, parent.pk, ignore):
            raise ValidationError(
                {
                    field: [
                        gettext(
                            "%(child)s already contains %(parent)s: this "
                            "would make it part of itself."
                        )
                        % {"child": child, "parent": parent}
                    ]
                }
            )

    def holds(self, top: Any, wanted: Any, ignore: Any = None) -> bool:
        """Whether ``wanted`` is somewhere below ``top``, over every
        link - not only the ones a reader sees: a cycle is one whoever
        made it."""
        if self.linked:
            parent, child = self.parent_field.name, self.child_field.name
            links = self.link_model._default_manager.all()

            if ignore is not None:
                links = links.exclude(pk=ignore)
        else:
            parent, child = self.parent_field.name, "pk"
            links = self.model._default_manager.all()

        frontier = [top]
        seen = {top}

        while frontier and len(seen) < MAX_WALK:
            found = []

            for start in range(0, len(frontier), WALK_CHUNK):
                chunk = frontier[start : start + WALK_CHUNK]
                found += links.filter(**{f"{parent}__in": chunk}).values_list(
                    child, flat=True
                )

            frontier = []

            for pk in found:
                if pk == wanted:
                    return True

                if pk not in seen:
                    seen.add(pk)
                    frontier.append(pk)

        return False


def describe_link_entry(
    tree: BoundTree,
    request: Any,
    link: Any,
    name: str,
) -> dict[str, Any]:
    """A value of the link, typed like a summary page's."""
    from generic.sites.summary import describe_entry, describe_value

    if link is None:
        return {"type": "text", "empty": True}

    link_resource = tree.get_link_resource()

    if link_resource is not None:
        return describe_entry(link_resource, request, link, name)

    return describe_value(tree.resource.site, request, getattr(link, name))


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


def bind_tree(definition: Tree, resource: Any) -> BoundTree:
    """Resolve ``definition`` against the resource declaring it."""
    owner = type(resource).__name__
    where = f"{owner}.trees: '{getattr(definition, 'name', definition)}'"

    if not isinstance(definition, Tree):
        raise ImproperlyConfigured(
            f"{owner}.trees holds {definition!r}: Tree(...) is expected."
        )

    if not NAME_PATTERN.match(definition.name):
        raise ImproperlyConfigured(
            f"{where} must be named with lower case letters, digits and "
            f"dashes."
        )

    if not 1 <= definition.page_size <= MAX_LIMIT:
        raise ImproperlyConfigured(
            f"{where}: page_size must be between 1 and {MAX_LIMIT}."
        )

    model = resource.model

    if definition.through is not None:
        if definition.child is None:
            raise ImproperlyConfigured(
                f"{where} has a 'through' model and so needs 'child': its "
                f"foreign key to the record held."
            )

        link_model = definition.through
        parent_field = foreign_key(link_model, definition.parent, model, where)
        child_field = foreign_key(link_model, definition.child, model, where)
    else:
        if definition.child is not None or definition.link_columns:
            raise ImproperlyConfigured(
                f"{where}: 'child' and 'link_columns' describe a 'through' "
                f"model, and none is given."
            )

        link_model = model
        parent_field = foreign_key(model, definition.parent, model, where)
        child_field = None

    from generic.sites.serializers import resolve_display_callable

    for name in definition.columns:
        try:
            model._meta.get_field(name)
        except FieldDoesNotExist:
            if resolve_display_callable(name, resource, model) is None:
                raise ImproperlyConfigured(
                    f"{where} shows '{name}', which is neither a field of "
                    f"{model.__name__}, a method of the resource, nor an "
                    f"attribute of the model."
                ) from None

    for name in definition.link_columns:
        try:
            link_model._meta.get_field(name)
        except FieldDoesNotExist:
            if not hasattr(link_model, name):
                raise ImproperlyConfigured(
                    f"{where} shows '{name}' of each link, which is not a "
                    f"field of {link_model.__name__}."
                ) from None

    roots = definition.roots

    if isinstance(roots, str) and not callable(getattr(resource, roots, None)):
        raise ImproperlyConfigured(
            f"{where}: roots names '{roots}', which is not a method of the "
            f"resource."
        )

    return BoundTree(
        definition=definition,
        resource=resource,
        link_model=link_model,
        parent_field=parent_field,
        child_field=child_field,
    )


# ---------------------------------------------------------------------
# Writes: no record inside itself
# ---------------------------------------------------------------------

#: The trees over each model holding links, filled in at registration.
_GUARDS: dict[Any, list[BoundTree]] = {}


def guard(resource: Any) -> None:
    """Have the forms of the links' model refuse a cycle."""
    for bound in resource.get_trees():
        entries = _GUARDS.setdefault(bound.link_model, [])
        entries[:] = [
            entry
            for entry in entries
            if not (entry.resource is resource and entry.name == bound.name)
        ]
        entries.append(bound)


def forget(resource: Any) -> None:
    """The resource is unregistered: its trees guard nothing any more."""
    for model, entries in list(_GUARDS.items()):
        entries[:] = [
            entry for entry in entries if entry.resource is not resource
        ]

        if not entries:
            del _GUARDS[model]


def check_links(model: Any, instance: Any, attrs: dict[str, Any]) -> None:
    """Called by every generated form serializer of ``model``."""
    for bound in _GUARDS.get(model, ()):
        bound.check_write(instance, attrs)


def tree_page(bound: BoundTree) -> ResourcePage:
    """The page of the whole tree, from the records nothing holds."""
    return ResourcePage(
        bound.name,
        view=TreePageView,
        title=bound.definition.title or gettext_lazy("Tree"),
        icon=bound.definition.icon,
        description=bound.definition.description,
    )


class TreePageView(ResourcePageView):
    """The page of a tree: its roots, or one record (``?root=<pk>``)."""

    template_name = "generic/resource/tree.html"

    def get_bound_tree(self) -> BoundTree:
        return self.resource.get_tree(self.page.name)

    def get_root(self) -> Any:
        value = self.request.GET.get("root")

        if not value:
            return None

        try:
            return self.get_bound_tree().find(self.request, value)
        except NotFound:
            from django.http import Http404

            raise Http404 from None

    def get_page_subtitle(self) -> str:
        root = getattr(self, "root", None)

        if root is not None:
            return self.resource.get_object_label(root)

        return super().get_page_subtitle()

    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        self.root = self.get_root()

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        bound = self.get_bound_tree()
        context["tree"] = bound
        context["tree_config"] = bound.get_config(self.request, root=self.root)
        context["root"] = self.root

        if self.root is not None:
            context["root_label"] = self.resource.get_object_label(self.root)
            context["root_url"] = self.resource.get_object_url(self.root.pk)
            context["whole_url"] = bound.get_page_url()

        return context


__all__ = [
    "BoundTree",
    "DOWN",
    "Tree",
    "TreePageView",
    "UP",
    "bind_tree",
    "check_links",
]

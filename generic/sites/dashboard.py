"""Key figures and record cards, declared on a resource, shown on the
dashboard.

Two declarations, both answered by the resource's own endpoint, both
drawn on the dashboard for whoever may read the resource::

    @register(Ticket)
    class TicketResource(ModelResource):
        kpis = (
            Kpi(
                "open",
                title=_("Open tickets"),
                icon="inbox",
                filters={"match": "all", "conditions": [
                    {"column": "status", "operator": "any_of",
                     "value": ["open", "pending"]},
                ]},
                warning=40,
                danger=60,
            ),
            Kpi("hours", title=_("Estimated hours"), value=Sum(
                "estimated_hours"), unit="h", decimals=1),
        )
        cards = (
            Cards(
                "urgent",
                title=_("Urgent tickets"),
                filters={...},
                ordering=("due_on",),
                subtitle="customer",
                fields=("priority", "status", "due_on"),
                limit=6,
            ),
        )

A **key figure** is one number - a count by default, any aggregate
with ``value`` - over the rows the list would show under ``filters``.
Its tile opens the list with those filters, so the number and the list
always agree: they are the same filter tree, read by the same
whitelist (``FilterTreeBuilder``), relative dates included ("opened in
the last 7 days" stays true tomorrow). ``warning`` and ``danger``
colour the tile.

**Cards** are a few records drawn as tiles - the latest, the most
urgent - with their label, a subtitle, a picture and a few values,
typed as on a summary page. *See all* opens the list, filtered alike.

The browser names a resource and a declaration, never a column or a
path: ``GET api/<app>/<model>/kpis/<name>/`` and ``.../cards/<name>/``
answer from the declaration, over ``get_list_queryset(request)``, so a
reader is never counted, or shown, a record the resource would not
list them.
"""

from __future__ import annotations

import dataclasses
import json
import posixpath
import re
from typing import Any, Sequence
from urllib.parse import urlencode

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import Count, F, FileField
from django.utils.encoding import force_str
from rest_framework.exceptions import ValidationError

from generic.api.filters import FilterTreeBuilder, legacy_to_tree

#: A declaration's name is a piece of its endpoint's address.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

#: The most cards one declaration may show: a dashboard is a glance.
MAX_CARDS = 24

#: Pictures a browser draws inline (generic.sites.files serves them so).
RASTER_IMAGES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})


def as_tree(filters: Any) -> dict[str, Any] | None:
    """A declared filter, as a tree: presets accept the older flat form
    (one condition per column) too, and so do these."""
    if not filters:
        return None

    if not isinstance(filters, dict):
        raise TypeError("filters must be a dict")

    if "conditions" in filters or "match" in filters:
        return filters

    return legacy_to_tree(filters)


def check_permission(permission: Any, request: Any) -> bool:
    """``permission``: None, a permission string, several (all needed),
    or ``callable(request)`` - as a chart's."""
    if permission is None:
        return True

    if callable(permission):
        return bool(permission(request))

    user = getattr(request, "user", None)

    if user is None:
        return False

    if isinstance(permission, str):
        return user.has_perm(permission)

    return all(user.has_perm(item) for item in permission)


def check_entry(resource: Any, owner: str, name: str) -> None:
    """``name`` is something a summary page could show, or a refusal
    naming the declaration."""
    from generic.sites.serializers import resolve_display_callable

    model = resource.model

    try:
        model._meta.get_field(name)
    except FieldDoesNotExist:
        if resolve_display_callable(name, resource, model) is None:
            raise ImproperlyConfigured(
                f"{type(resource).__name__}.{owner} shows '{name}', which "
                f"is neither a field of {model.__name__}, a method of the "
                f"resource, nor an attribute of the model."
            ) from None


@dataclasses.dataclass(frozen=True)
class Narrowed:
    """What a declared filter leaves: shared by key figures and cards."""

    #: Lower case letters, digits, dashes and underscores.
    name: str
    title: Any = None
    icon: str | None = None
    description: Any = ""
    #: A filter tree over the list's columns, as ``presets`` write it,
    #: or the older flat form. None: every row the reader may see.
    filters: Any = None
    #: Who sees it, beyond the resource's view permission: a permission
    #: string, several (all needed), or ``callable(request)``.
    permission: Any = None
    #: Its place on the dashboard, before the resource's own order.
    order: int = 0

    #: The attribute declaring it, for the messages.
    owner = ""

    def check(self, resource: Any) -> None:
        kind = type(self).__name__

        if not isinstance(self.name, str) or not NAME_PATTERN.match(self.name):
            raise ImproperlyConfigured(
                f"{type(resource).__name__}.{self.owner}: {kind} name "
                f"{self.name!r} must be lower case letters, digits, dashes "
                f"and underscores - it is part of an address."
            )

        try:
            as_tree(self.filters)
        except TypeError:
            raise ImproperlyConfigured(
                f"{type(resource).__name__}.{self.owner}: {kind} "
                f"'{self.name}' has filters that are not a filter tree "
                f"(a dict, as presets write it)."
            ) from None

    def key(self, resource: Any) -> str:
        return f"{resource.label_lower}.{self.name}"

    def get_title(self, resource: Any) -> str:
        return force_str(self.title or resource.get_label_plural())

    def get_icon(self, resource: Any) -> str:
        return self.icon or resource.get_icon()

    def is_visible(self, request: Any, resource: Any) -> bool:
        return resource.has_view_permission(request) and check_permission(
            self.permission, request
        )

    def narrow(self, resource: Any, request: Any) -> Any:
        """The list's rows under the declared filters.

        The filter is read through the table's own whitelist: a column
        the list does not offer is an error of the declaration, said as
        one rather than answered with every row.
        """
        queryset = resource.get_list_queryset(request)
        tree = as_tree(self.filters)

        if tree is None:
            return queryset

        specs = resource.get_table_serializer_class().get_filter_specs()

        try:
            condition = FilterTreeBuilder(specs, resource.model).build(tree)
        except ValidationError as error:
            raise ImproperlyConfigured(
                f"{type(resource).__name__}.{self.owner}: the filters of "
                f"'{self.name}' are refused by the list: {error.detail}"
            ) from None

        return queryset if condition is None else queryset.filter(condition)

    def get_list_url(self, resource: Any) -> str:
        """The list, already narrowed: the same tree in its address."""
        url = resource.get_list_url()
        tree = as_tree(self.filters)

        if not url or tree is None:
            return url

        return f"{url}?{urlencode({'filters': json.dumps(tree)})}"


@dataclasses.dataclass(frozen=True)
class Kpi(Narrowed):
    """One key figure: a number over the rows the list would show."""

    #: An aggregate - ``Sum("hours")``, ``Avg("satisfaction")`` - or a
    #: ``callable(request, queryset)`` returning a number. None: how
    #: many rows.
    value: Any = None
    #: Written after the number: ``"h"``, ``"EUR"``, ``"%"``.
    unit: Any = ""
    #: Decimal places shown. None: none for a count, two otherwise.
    decimals: int | None = None
    #: Thresholds colouring the tile. ``danger`` above ``warning`` (or
    #: alone): the higher, the worse; below it: the lower, the worse.
    warning: Any = None
    danger: Any = None

    owner = "kpis"

    def check(self, resource: Any) -> None:
        super().check(resource)

        if self.value is not None and not (
            callable(self.value) or hasattr(self.value, "resolve_expression")
        ):
            raise ImproperlyConfigured(
                f"{type(resource).__name__}.kpis: the value of "
                f"'{self.name}' must be an aggregate (Sum('hours')) or a "
                f"callable(request, queryset)."
            )

        for threshold in (self.warning, self.danger):
            if threshold is not None and not isinstance(
                threshold, (int, float)
            ):
                try:
                    float(threshold)
                except (TypeError, ValueError):
                    raise ImproperlyConfigured(
                        f"{type(resource).__name__}.kpis: the thresholds "
                        f"of '{self.name}' must be numbers."
                    ) from None

    def compute(self, resource: Any, request: Any) -> Any:
        """The figure, over the plain queryset selected by key: the
        list's annotations and joins would count rows twice."""
        matching = self.narrow(resource, request).values("pk")
        queryset = resource.get_queryset(request).filter(pk__in=matching)

        if self.value is not None and not hasattr(
            self.value, "resolve_expression"
        ):
            return self.value(request, queryset)

        expression = self.value or Count("pk", distinct=True)

        return queryset.aggregate(figure=expression)["figure"]

    def level(self, figure: Any) -> str:
        """``danger``, ``warning``, ``good`` - or nothing to say."""
        if figure is None or (self.warning is None and self.danger is None):
            return ""

        number = float(figure)
        warning = None if self.warning is None else float(self.warning)
        danger = None if self.danger is None else float(self.danger)
        lower_is_worse = (
            warning is not None and danger is not None and danger < warning
        )

        def reached(threshold: float | None) -> bool:
            if threshold is None:
                return False

            return (
                number <= threshold
                if lower_is_worse
                else (number >= threshold)
            )

        if reached(danger):
            return "danger"

        if reached(warning):
            return "warning"

        return "good"

    def get_decimals(self) -> int:
        if self.decimals is not None:
            return int(self.decimals)

        return 0 if self.value is None else 2

    def get_payload(self, resource: Any, request: Any) -> dict[str, Any]:
        from generic.sites.summary import format_number

        figure = self.compute(resource, request)
        decimals = self.get_decimals()

        return {
            "name": self.name,
            "title": self.get_title(resource),
            "value": None if figure is None else float(figure),
            "display": (
                "\u2014" if figure is None else format_number(figure, decimals)
            ),
            "unit": force_str(self.unit or ""),
            "level": self.level(figure),
            "url": self.get_list_url(resource),
        }

    def get_config(self, resource: Any) -> dict[str, Any]:
        """What the dashboard draws before the figure arrives."""
        return {
            "key": self.key(resource),
            "name": self.name,
            "title": self.get_title(resource),
            "icon": self.get_icon(resource),
            "description": force_str(self.description or ""),
            "group": resource.get_group(),
            "url": resource._reverse(
                resource.api_url_name("kpi"), kpi=self.name
            ),
            "listUrl": self.get_list_url(resource),
            "resource": resource.label_lower,
            "topic": resource.topic_name if resource.realtime else "",
        }


@dataclasses.dataclass(frozen=True)
class Cards(Narrowed):
    """A few records drawn as tiles on the dashboard."""

    #: The order they are picked in: fields of the model, ``-`` for
    #: descending; records without the value come last. Default: the
    #: resource's ordering.
    ordering: Sequence[str] = ()
    #: How many (at most 24).
    limit: int = 6
    #: Under the record's label: a field, a resource method or a model
    #: attribute, as a summary page shows it.
    subtitle: str | None = None
    #: Values shown on each card, the same way.
    fields: Sequence[str] = ()
    #: A file field holding a picture, drawn at the top of the card.
    image: str | None = None

    owner = "cards"

    def check(self, resource: Any) -> None:
        super().check(resource)
        name = type(resource).__name__

        if not isinstance(self.limit, int) or not (
            0 < self.limit <= MAX_CARDS
        ):
            raise ImproperlyConfigured(
                f"{name}.cards: '{self.name}' shows between 1 and "
                f"{MAX_CARDS} cards (limit)."
            )

        if isinstance(self.fields, str) or isinstance(self.ordering, str):
            raise ImproperlyConfigured(
                f"{name}.cards: the fields and ordering of '{self.name}' "
                f"are tuples of names, not one string."
            )

        for entry in (
            *([self.subtitle] if self.subtitle else ()),
            *self.fields,
        ):
            check_entry(resource, "cards", entry)

        for term in self.ordering:
            if term.lstrip("-") == "pk":
                continue

            try:
                resource.model._meta.get_field(term.lstrip("-").split("__")[0])
            except FieldDoesNotExist:
                raise ImproperlyConfigured(
                    f"{name}.cards: '{self.name}' is ordered by "
                    f"'{term}', which is not a field of "
                    f"{resource.model.__name__}."
                ) from None

        if self.image:
            try:
                field = resource.model._meta.get_field(self.image)
            except FieldDoesNotExist:
                field = None

            if not isinstance(field, FileField):
                raise ImproperlyConfigured(
                    f"{name}.cards: the image of '{self.name}', "
                    f"'{self.image}', is not a file field of "
                    f"{resource.model.__name__}."
                )

    def get_ordering(self, resource: Any) -> list[Any]:
        """The order, records without the value last whichever way:
        "due soonest" means the ones with a date, on every database."""
        ordering = list(self.ordering or resource.ordering or ())

        # A last key: cards of equal rank keep their place between draws.
        if not {"pk", "-pk"} & set(ordering):
            ordering.append("-pk")

        return [
            (
                (
                    F(term[1:]).desc(nulls_last=True)
                    if term.startswith("-")
                    else F(term).asc(nulls_last=True)
                )
                if isinstance(term, str)
                else term
            )
            for term in ordering
        ]

    def picture(self, resource: Any, request: Any, obj: Any) -> str:
        """The picture's address, when it is one a browser draws and the
        reader may download it."""
        from generic.sites.summary import describe_entry

        entry = describe_entry(resource, request, obj, self.image)
        name = force_str(entry.get("display") or "")

        if entry.get("empty") or not entry.get("url"):
            return ""

        if posixpath.splitext(name)[1].lower() not in RASTER_IMAGES:
            return ""

        return entry["url"]

    def describe(self, resource: Any, request: Any, obj: Any) -> dict:
        from generic.sites.summary import describe_entry, record_url

        def entry(name: str) -> dict[str, Any]:
            described = describe_entry(resource, request, obj, name)
            described.pop("wide", None)

            return described

        return {
            "id": force_str(obj.pk),
            "label": resource.get_object_label(obj),
            "url": record_url(resource.site, request, obj),
            "subtitle": entry(self.subtitle) if self.subtitle else None,
            "image": (
                self.picture(resource, request, obj) if self.image else ""
            ),
            "cells": [entry(name) for name in self.fields],
        }

    def get_payload(self, resource: Any, request: Any) -> dict[str, Any]:
        queryset = self.narrow(resource, request)
        rows = list(
            queryset.order_by(*self.get_ordering(resource))[: self.limit]
        )
        total = (
            len(rows)
            if len(rows) < self.limit
            else self.narrow(resource, request).values("pk").count()
        )

        return {
            "name": self.name,
            "title": self.get_title(resource),
            "items": [self.describe(resource, request, row) for row in rows],
            "total": total,
            "url": self.get_list_url(resource),
        }

    def get_config(self, resource: Any) -> dict[str, Any]:
        return {
            "key": self.key(resource),
            "name": self.name,
            "title": self.get_title(resource),
            "icon": self.get_icon(resource),
            "description": force_str(self.description or ""),
            "group": resource.get_group(),
            "url": resource._reverse(
                resource.api_url_name("cards"), cards=self.name
            ),
            "listUrl": self.get_list_url(resource),
            "resource": resource.label_lower,
            "topic": resource.topic_name if resource.realtime else "",
            "limit": self.limit,
        }


def check_declarations(resource: Any, attribute: str, kind: type) -> list:
    """The declarations of ``attribute``, checked: their type, their
    names (once each), their fields."""
    declared = list(getattr(resource, attribute, ()) or ())
    names = []

    for item in declared:
        if not isinstance(item, kind):
            raise ImproperlyConfigured(
                f"{type(resource).__name__}.{attribute} holds "
                f"{item!r}, which is not a {kind.__name__}(...)."
            )

        item.check(resource)
        names.append(item.name)

    if len(set(names)) != len(names):
        raise ImproperlyConfigured(
            f"{type(resource).__name__}.{attribute} declares the same "
            f"name twice."
        )

    return declared


def dashboard_entries(
    site: Any, request: Any, attribute: str
) -> list[dict[str, Any]]:
    """Every declaration of ``attribute`` this reader may see, across the
    site's resources, as the dashboard draws them."""
    found = []

    for resource in site.get_resources():
        for item in getattr(resource, f"get_{attribute}")():
            if item.is_visible(request, resource):
                found.append(
                    (
                        item.order,
                        resource.order,
                        resource.get_label_plural(),
                        item.get_config(resource),
                    )
                )

    found.sort(key=lambda entry: entry[:3])

    return [entry[3] for entry in found]


__all__ = ["Cards", "Kpi", "dashboard_entries"]

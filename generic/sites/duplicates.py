"""A record copied into a new one, its values edited before it is written.

Declared on the resource::

    @register(Ticket)
    class TicketResource(ModelResource):
        # The form's fields, its many-to-many values and its inlines:
        duplicate = True
        # or, with more to say:
        duplicate = Duplicate(
            exclude=("due_on",),             # left empty in the copy
            related=("time_entries",),       # copied on request, server side
            values={"status": "open"},       # or callable(request, obj)
        )

A record's page and its row menu then offer *Duplicate*. It opens the
add form at ``<model>/<pk>/duplicate/``, filled with the record's values
as the reader's form serializer reads them - fields they may not see or
change are not copied, the copy takes their default - and a *Copy with
it* section on top: one box per many-to-many field and per inline (ticked:
the form holds the record's values or rows, still editable; unticked:
empty), and one per declared ``related`` relation (ticked: its records are
copied once the new record is written, in the same transaction). Unique
fields and files are never copied: the copy would be refused, or would
share a stored file nobody chose.

Nothing is written until the form is saved, through the same endpoint as
any new record (``POST api/<app>/<model>/``), its body naming the source:
``"_duplicate": {"source": <pk>, "related": ["time_entries"]}``. The
endpoint finds the source in the resource's queryset, asks
``can_duplicate(request, source)``, refuses an undeclared relation, and
copies each related record through the related resource's own form
serializer and ``save_model`` - under its add permission - once the new
record is saved; any refusal rolls the whole copy back.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Callable, Mapping, Sequence

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.http import Http404
from django.utils.encoding import force_str
from django.utils.text import capfirst
from django.utils.translation import gettext
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from generic.api.files import FormFileField

#: The body key naming what a new record is a copy of.
PAYLOAD_KEY = "_duplicate"

#: The most records of one relation copied with a record: past it, the
#: relation is offered disabled, its count shown.
MAX_COPIED_ROWS = 500

#: The record page's name, and its address piece.
PAGE_NAME = "duplicate"


@dataclasses.dataclass(frozen=True)
class Duplicate:
    """What a copy of a record leaves out, adds, and changes.

    ``exclude`` - fields left to their default in the copy.
    ``related`` - reverse foreign keys (their related names) whose records
    may be copied too, ticked on the form; never an inline, which the
    form already carries. ``values`` - ``{field: value}`` the copy opens
    with, or ``callable(request, obj) -> dict``. ``permission`` - asked
    besides the add permission: a permission string, or
    ``callable(request, obj) -> bool``.
    """

    exclude: Sequence[str] = ()
    related: Sequence[str] = ()
    values: Mapping[str, Any] | Callable[[Any, Any], Mapping] | None = None
    permission: str | Callable[[Any, Any], bool] | None = None

    def __post_init__(self) -> None:
        for name in ("exclude", "related"):
            value = getattr(self, name)

            if isinstance(value, str):
                raise ImproperlyConfigured(
                    f"Duplicate({name}=...) is a tuple of names, not one "
                    f"string: ({value!r},)."
                )

            object.__setattr__(self, name, tuple(value))


@dataclasses.dataclass(frozen=True)
class CopiedRelation:
    """A relation whose records are copied with the record."""

    name: str
    field: Any  # the child model's foreign key to the record
    model: Any

    @property
    def label(self) -> str:
        return capfirst(force_str(self.model._meta.verbose_name_plural))


class BoundDuplicate:
    """A resource's ``duplicate``, resolved and checked against its
    model once per process."""

    def __init__(self, resource: Any, declaration: Duplicate) -> None:
        self.resource = resource
        self.declaration = declaration
        self.exclude = frozenset(declaration.exclude)
        self.related = {
            name: self.resolve_relation(name) for name in declaration.related
        }

    # -- checks --------------------------------------------------------

    def owner(self) -> str:
        return f"{type(self.resource).__name__}.duplicate"

    def check(self) -> None:
        model = self.resource.model
        names = {field.name for field in model._meta.get_fields()}

        for name in self.exclude:
            if name not in names:
                raise ImproperlyConfigured(
                    f"{self.owner()} excludes {name!r}, which is not a "
                    f"field of {model.__name__}."
                )

        inlines = {
            inline.name for inline in self.resource.get_inline_instances()
        }

        for name in self.related:
            if name in inlines:
                raise ImproperlyConfigured(
                    f"{self.owner()} copies {name!r}, an inline: its rows "
                    f"are on the form already, and copied from there."
                )

    def resolve_relation(self, name: str) -> CopiedRelation:
        model = self.resource.model

        for relation in model._meta.related_objects:
            if relation.one_to_many and relation.get_accessor_name() == name:
                return CopiedRelation(
                    name=name,
                    field=relation.field,
                    model=relation.related_model,
                )

        raise ImproperlyConfigured(
            f"{self.owner()} copies {name!r}, which is not the related "
            f"name of a foreign key pointing at {model.__name__}."
        )

    def related_resource(self, relation: CopiedRelation) -> Any:
        resource = self.resource.site.get_resource(relation.model)

        if resource is None:
            raise ImproperlyConfigured(
                f"{self.owner()} copies {relation.name!r}, but "
                f"{relation.model.__name__} is not registered: register "
                f"it (show_in_navigation = False for a child model)."
            )

        return resource

    # -- permissions -----------------------------------------------------

    def allows(self, request: Any, obj: Any = None) -> bool:
        """The declaration's own permission, besides the add one."""
        permission = self.declaration.permission

        if permission is None:
            return True

        if callable(permission):
            return bool(permission(request, obj))

        return bool(request.user.has_perm(permission))

    # -- the form ----------------------------------------------------------

    def serializer_context(self, request: Any) -> dict[str, Any]:
        from generic.api.files import FILE_URL
        from generic.sites.files import file_url_resolver

        return {
            "request": request,
            FILE_URL: file_url_resolver(self.resource.site, request),
        }

    def initial(self, request: Any, obj: Any) -> dict[str, Any]:
        """What the duplicate form opens with: ``values`` and their
        ``display`` labels by field, ``inlines`` rows by inline name,
        and the ``copies`` it offers to tick."""
        resource = self.resource
        context = self.serializer_context(request)
        serializer_class = resource.get_form_serializer_for(request)
        values, display = copy_values(
            serializer_class, context, obj, skip=self.exclude
        )

        overrides = self.declaration.values

        if callable(overrides):
            overrides = overrides(request, obj)

        for name, value in dict(overrides or {}).items():
            values[name] = value
            display.pop(name, None)

        copies: list[dict[str, Any]] = []
        fields = serializer_class(context=context).fields

        for name, field in fields.items():
            if (
                name in values
                and isinstance(field, serializers.ManyRelatedField)
                and values[name]
            ):
                copies.append(
                    {
                        "name": name,
                        "kind": "field",
                        "label": force_str(field.label or name),
                        "count": len(values[name]),
                        "checked": True,
                    }
                )

        inlines: dict[str, list[dict[str, Any]]] = {}

        for definition in resource.get_inline_definitions(request):
            if not definition.can_add:
                continue

            rows = inline_rows(definition, context, obj)

            if rows:
                inlines[definition.name] = rows
                copies.append(
                    {
                        "name": definition.name,
                        "kind": "inline",
                        "label": force_str(definition.title),
                        "count": len(rows),
                        "checked": True,
                    }
                )

        for name, relation in self.related.items():
            related = self.related_resource(relation)

            if not related.has_add_permission(request):
                continue

            count = self.children(request, relation, obj).count()

            if count:
                copies.append(
                    {
                        "name": name,
                        "kind": "related",
                        "label": relation.label,
                        "count": count,
                        "checked": False,
                        "disabled": count > MAX_COPIED_ROWS,
                    }
                )

        return {
            "values": values,
            "display": display,
            "inlines": inlines,
            "copies": copies,
        }

    # -- the copy ----------------------------------------------------------

    def children(self, request: Any, relation: CopiedRelation, obj: Any):
        """The records of ``relation`` this reader may see, oldest first."""
        related = self.related_resource(relation)

        return (
            related.get_queryset(request)
            .filter(**{relation.field.name: obj})
            .order_by("pk")
        )

    def copy_related(
        self,
        request: Any,
        source: Any,
        target: Any,
        names: Sequence[str],
    ) -> int:
        """Copy the records of ``names`` from ``source`` to ``target``,
        each through its own resource's form serializer and
        ``save_model``. Raises a ``ValidationError`` keyed by relation -
        to be rolled back - on the first refusal. Answers how many were
        written."""
        written = 0
        errors: dict[str, list[str]] = {}

        for name in names:
            relation = self.related[name]
            related = self.related_resource(relation)

            if not related.has_add_permission(request):
                raise PermissionDenied(
                    gettext("You may not add %(name)s.")
                    % {"name": relation.label}
                )

            children = self.children(request, relation, source)

            if children.count() > MAX_COPIED_ROWS:
                errors[name] = [
                    gettext(
                        "At most %(count)s %(name)s are copied with a "
                        "record."
                    )
                    % {"count": MAX_COPIED_ROWS, "name": relation.label}
                ]
                continue

            context = self.serializer_context(request)
            serializer_class = related.get_form_serializer_for(request)
            fk = relation.field.name
            writable = serializer_class(context=context).fields
            points = fk in writable and not writable[fk].read_only

            for child in children:
                values, _display = copy_values(
                    serializer_class, context, child, skip={fk}
                )

                if points:
                    values[fk] = target.pk

                serializer = serializer_class(data=values, context=context)

                if not serializer.is_valid():
                    errors.setdefault(name, []).extend(
                        describe_errors(child, serializer.errors)
                    )
                    continue

                if not points:
                    serializer.validated_data[fk] = target

                related.save_model(request, serializer, change=False)
                written += 1

        if errors:
            raise ValidationError({PAYLOAD_KEY: errors})

        return written


def resolve(resource: Any) -> BoundDuplicate | None:
    """``resource.duplicate`` resolved, or None when it offers nothing."""
    declared = resource.duplicate
    owner = type(resource).__name__

    if not declared:
        return None

    if declared is True:
        declared = Duplicate()

    if not isinstance(declared, Duplicate):
        raise ImproperlyConfigured(
            f"{owner}.duplicate is True, False or a Duplicate(...), not "
            f"{declared!r}."
        )

    bound = BoundDuplicate(resource, declared)
    bound.check()

    return bound


# -- values ------------------------------------------------------------


def is_unique(model: Any, name: str) -> bool:
    try:
        field = model._meta.get_field(name)
    except Exception:
        return False

    return bool(getattr(field, "unique", False) or field.primary_key)


def copy_values(
    serializer_class: Any,
    context: dict[str, Any],
    instance: Any,
    skip: Any = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The values a form would send to create a copy of ``instance``,
    and the labels of its relations: what ``serializer_class`` reads and
    may write, without keys, unique fields, files and ``skip``."""
    serializer = serializer_class(instance, context=context)
    data = serializer.data
    model = serializer_class.Meta.model
    values: dict[str, Any] = {}

    for name, field in serializer.fields.items():
        if (
            name.startswith("_")
            or name in skip
            or field.read_only
            or field.write_only
            or isinstance(field, (FormFileField, serializers.FileField))
            or is_unique(model, field.source or name)
            or name not in data
        ):
            continue

        values[name] = data[name]

    display = {
        name: label
        for name, label in dict(data.get("_display") or {}).items()
        if name in values
    }

    return values, display


def inline_rows(definition: Any, context: dict[str, Any], obj: Any) -> list:
    """An inline's rows as new rows of a copy: no key, no unique field,
    no file, no pointer at the record (the form adds it)."""
    rows = []
    skip = {definition.primary_key, definition.parent_field}

    for child in definition.get_queryset(obj):
        values, display = copy_values(
            definition.serializer_class, context, child, skip=skip
        )

        if display:
            values["_display"] = display

        rows.append(values)

    return rows


def describe_errors(obj: Any, errors: Any) -> list[str]:
    """``"<record>: <field>: <message>"``, one line per message."""
    lines = []

    for name, messages in dict(errors).items():
        if not isinstance(messages, (list, tuple)):
            messages = [messages]

        for message in messages:
            lines.append(f"{obj}: {name}: {force_str(message)}")

    return lines


# -- the request ---------------------------------------------------------


def read_request(resource: Any, request: Any) -> tuple[Any, list] | None:
    """What a create request is a copy of: ``(source, related names)``,
    or None for an ordinary new record. Refuses (404, 403, 400) a source
    the reader may not copy and a relation the declaration does not
    name."""
    data = request.data
    raw = data.get(PAYLOAD_KEY) if hasattr(data, "get") else None

    if raw in (None, ""):
        return None

    bound = resource.get_duplicate()

    if bound is None:
        raise ValidationError(
            {PAYLOAD_KEY: [gettext("These records are not duplicated.")]}
        )

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as error:
            raise ValidationError(
                {PAYLOAD_KEY: [gettext("Invalid JSON payload.")]}
            ) from error

    if not isinstance(raw, dict) or raw.get("source") in (None, ""):
        raise ValidationError(
            {PAYLOAD_KEY: [gettext("Name the record copied.")]}
        )

    try:
        source = resource.get_queryset(request).get(pk=raw["source"])
    except (resource.model.DoesNotExist, ValueError, TypeError) as error:
        raise Http404 from error
    except models.ObjectDoesNotExist as error:  # pragma: no cover
        raise Http404 from error

    if not resource.can_duplicate(request, source):
        raise PermissionDenied(gettext("You may not duplicate this record."))

    names = raw.get("related") or []

    if not isinstance(names, list) or not all(
        isinstance(name, str) for name in names
    ):
        raise ValidationError(
            {PAYLOAD_KEY: [gettext("A list of relations is expected.")]}
        )

    unknown = sorted(set(names) - set(bound.related))

    if unknown:
        raise ValidationError(
            {
                PAYLOAD_KEY: [
                    gettext("%(names)s cannot be copied.")
                    % {"names": ", ".join(unknown)}
                ]
            }
        )

    return source, list(dict.fromkeys(names))

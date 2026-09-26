"""Cells a reader may change without leaving the table.

A resource names the columns that can be edited and gets the rest: the
control to edit each one with, the validation, the permission, and the
write::

    class TicketResource(ModelResource):
        list_display = ("reference", "title", "customer", "status")
        editable_fields = ("status", "customer__name")

Three things this has to get right, and they are why it is a module
rather than a flag:

* **A column may belong to another model.** ``customer__name`` is a
  field of *Customer*, reached from the ticket in the row. It is
  resolved here, once, from the declaration - the browser sends the
  public column name and never a path of its own - and it is the
  **Customer's** change permission that decides, not the ticket's.
* **A cell is edited with the same control as a form field.** The
  schema handed to the browser is the one the form renderer already
  reads, built by the same code, so a choice is a select, a relation is
  an autocomplete, and a date is a date.
* **What finally happens is the project's.** Everything below is the
  default of one overridable method, ``ModelResource.save_editable``.
  A project that has to raise a workflow, write somewhere else or
  refuse on a rule of its own replaces it and keeps the rest.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import transaction
from django.utils.translation import gettext
from rest_framework import serializers


@dataclasses.dataclass(frozen=True)
class EditableColumn:
    """One editable column, resolved against the models behind it."""

    #: The public name, as the table and the browser call it.
    name: str
    #: Relations to walk from the row to the record that owns the
    #: field. Empty when the field is the row's own.
    path: tuple[str, ...]
    #: The field on that record.
    field_name: str
    model: type

    @property
    def is_own(self) -> bool:
        return not self.path


def resolve(resource: Any, name: str) -> EditableColumn:
    """Work out which record and field a column name stands for.

    Raises rather than guesses: an editable column that cannot be
    written is a cell that looks editable and is not, which a reader
    only finds out about after typing.
    """
    owner = type(resource).__name__
    parts = str(name).split("__")
    model = resource.model
    walked: list[str] = []

    for step in parts[:-1]:
        try:
            field = model._meta.get_field(step)
        except FieldDoesNotExist:
            raise ImproperlyConfigured(
                f"{owner}.editable_fields names '{name}', and "
                f"'{step}' is not a field of {model.__name__}."
            ) from None

        if not field.is_relation or field.many_to_many or field.one_to_many:
            raise ImproperlyConfigured(
                f"{owner}.editable_fields names '{name}', which goes "
                f"through '{step}'. Only a single-valued relation can "
                f"be walked: a row has one record to write to, and "
                f"many-valued paths have none in particular."
            )

        walked.append(step)
        model = field.related_model

    field_name = parts[-1]

    try:
        field = model._meta.get_field(field_name)
    except FieldDoesNotExist:
        raise ImproperlyConfigured(
            f"{owner}.editable_fields names '{name}', which is not a "
            f"field of {model.__name__}. A computed column cannot be "
            f"edited: write it through save_editable, or drop it."
        ) from None

    if not getattr(field, "editable", False) or field.auto_created:
        raise ImproperlyConfigured(
            f"{owner}.editable_fields names '{name}', which "
            f"{model.__name__} does not allow to be written."
        )

    return EditableColumn(
        name=str(name),
        path=tuple(walked),
        field_name=field_name,
        model=model,
    )


def columns_of(resource: Any) -> dict[str, EditableColumn]:
    """Every editable column of a resource, by public name.

    Resolved once per process, like the serializers: these are
    declarations, and a typo in one should be an error at start-up
    rather than a surprise on a Friday.
    """
    shown = set(resource.get_list_display())
    resolved = {}

    for name in resource.editable_fields:
        if name not in shown:
            raise ImproperlyConfigured(
                f"{type(resource).__name__}.editable_fields names "
                f"'{name}', which is not in list_display. A cell has "
                f"to be on the table before it can be edited."
            )

        resolved[str(name)] = resolve(resource, name)

    return resolved


def target_of(row: Any, column: EditableColumn) -> Any:
    """The record a column writes to, walking from the row."""
    instance = row

    for step in column.path:
        instance = getattr(instance, step, None)

        if instance is None:
            return None

    return instance


def resource_for(resource: Any, column: EditableColumn) -> Any:
    """The resource owning the record a column writes to."""
    if column.is_own:
        return resource

    return resource.site.get_resource(column.model)


def may_edit(
    resource: Any,
    request: Any,
    column: EditableColumn,
    obj: Any = None,
) -> bool:
    """Whether this user may write this column, on this record.

    The permission is the one of the model being written - a ticket's
    table showing a customer's name asks whether the reader may change
    *customers*.
    """
    if not resource.can_edit_column(request, column.name, obj):
        return False

    owner = resource_for(resource, column)

    if owner is not None:
        return bool(owner.has_change_permission(request, obj))

    opts = column.model._meta

    return bool(
        request.user.has_perm(f"{opts.app_label}.change_{opts.model_name}")
    )


def serializer_for(
    resource: Any,
    column: EditableColumn,
    fields: list[str],
) -> Any:
    """A form serializer for the fields of one record.

    The form serializer, not a new one: a cell must refuse exactly what
    the form refuses, or the table becomes a way round a rule.
    """
    from generic.sites.serializers import build_form_serializer

    owner = resource_for(resource, column)

    return build_form_serializer(
        column.model,
        fields=fields,
        overrides=getattr(owner, "form_overrides", {}),
        extra_kwargs=getattr(owner, "form_field_kwargs", {}),
        source=owner,
        name=f"{column.model.__name__}CellSerializer",
    )


def schema_for(
    resource: Any,
    request: Any,
    column: EditableColumn,
) -> dict[str, Any] | None:
    """How to edit this column, as the form renderer describes a field."""
    serializer_class = serializer_for(resource, column, [column.field_name])

    for entry in serializer_class.get_form_fields(request=request):
        if entry["name"] == column.field_name:
            # The browser knows the cell by its public name; the field
            # keeps its own for the write.
            return {**entry, "name": column.name, "field": column.field_name}

    return None


#: Display types a cell keeps once its link is taken away. Anything
#: else - a relation's label above all - is shown as the text it is.
PLAIN_TYPES = frozenset({"date", "datetime", "float", "integer", "boolean"})

#: What makes a column a way to somewhere else.
LINK_KEYS = ("linkUrl", "linkField", "linkTarget", "tagUrl")


def as_grid(config: dict[str, Any]) -> dict[str, Any]:
    """A table turned into a grid for correcting many rows at once.

    A table asked to be editable is not read on the way to a record: it
    is where the work happens, the whole set in view. So nothing in it
    leads anywhere - no cell is a link, no row opens on a double click,
    no row menu offers Open or Edit - and the cells that can be written
    are drawn as their controls from the start.

    Selection and bulk actions stay: they act on the set in view, which
    is what the page is for.
    """
    columns = []

    for column in config["columns"]:
        column = {
            key: value for key, value in column.items() if key not in LINK_KEYS
        }

        # A linked cell was a link *instead of* its own type; the type
        # it would have had is still what it filters as.
        if column.get("type") == "link":
            underlying = column.get("filterType")
            column["type"] = (
                underlying if underlying in PLAIN_TYPES else "text"
            )

        columns.append(column)

    options = dict(config["options"])
    options["rowActions"] = []
    options["grid"] = True

    # Its own saved layout: the columns worth seeing while correcting
    # rows are rarely the ones worth seeing while reading them.
    if options.get("stateKey"):
        options["stateKey"] = f"{options['stateKey']}.grid"

    return {**config, "columns": columns, "options": options}


def own_columns(resource: Any) -> list[str]:
    """The editable columns that are the row's own fields.

    Only these can be written on a row that does not exist yet: a
    column of another record - ``ticket__status`` - has no record to
    write to until the row points at one.
    """
    return [
        name
        for name, column in resource.get_editable_columns().items()
        if column.is_own
    ]


def schemas(resource: Any, request: Any) -> dict[str, Any]:
    """Every column this user may edit, with how to edit it.

    A column the reader may not write is simply not described, so the
    table draws it as text: the permission decides the interface, and
    the endpoint checks it again anyway.
    """
    described = {}

    for name, column in resource.get_editable_columns().items():
        if not may_edit(resource, request, column):
            continue

        schema = schema_for(resource, request, column)

        if schema is not None:
            described[name] = schema

    return described


# -- writing --------------------------------------------------------------


def group_changes(
    resource: Any,
    row: Any,
    changes: dict[str, Any],
) -> list[tuple[Any, EditableColumn, dict[str, Any], dict[str, str]]]:
    """The changes, gathered by the record each one writes to.

    Two cells of the same related record are one save, and one set of
    validation errors mapped back onto the two cells.
    """
    known = resource.get_editable_columns()
    grouped: dict[Any, dict[str, Any]] = {}
    naming: dict[Any, dict[str, str]] = {}
    targets: dict[Any, tuple[Any, EditableColumn]] = {}

    for name, value in changes.items():
        column = known.get(name)

        if column is None:
            raise serializers.ValidationError(
                {name: [gettext("This column cannot be edited here.")]}
            )

        target = target_of(row, column)

        if target is None:
            raise serializers.ValidationError(
                {
                    name: [
                        gettext(
                            "This row has nothing to write to: the "
                            "record it points at is missing."
                        )
                    ]
                }
            )

        key = (column.model, target.pk, column.path)
        grouped.setdefault(key, {})[column.field_name] = value
        naming.setdefault(key, {})[column.field_name] = name
        targets[key] = (target, column)

    return [
        (targets[key][0], targets[key][1], values, naming[key])
        for key, values in grouped.items()
    ]


def write(
    resource: Any,
    request: Any,
    row: Any,
    changes: dict[str, Any],
) -> None:
    """Validate and save one row's edited cells, all or nothing."""
    with transaction.atomic():
        for target, column, values, naming in group_changes(
            resource, row, changes
        ):
            if not may_edit(resource, request, column, target):
                raise serializers.ValidationError(
                    {
                        naming[name]: [
                            gettext("You may not change this column.")
                        ]
                        for name in values
                    }
                )

            serializer_class = serializer_for(
                resource,
                column,
                list(values),
            )
            serializer = serializer_class(
                target,
                data=values,
                partial=True,
                context={"request": request},
            )

            try:
                serializer.is_valid(raise_exception=True)
            except serializers.ValidationError as error:
                raise serializers.ValidationError(
                    {
                        naming.get(field, field): messages
                        for field, messages in (error.detail or {}).items()
                    }
                ) from error

            serializer.save()


# -- new rows -------------------------------------------------------------


def default_context(resource: Any) -> Any:
    """A grid over the resource's own rows: every own column is
    written on a new row, and nothing else is imposed."""
    from generic.sites.grids import RowContext

    return RowContext(creatable=tuple(own_columns(resource)))


def starting_value(model: Any, name: str) -> Any:
    """What a new record holds in ``name`` before anybody types.

    The model's default, called when it is a function: a draft row is
    drawn for this request, so today's date is the right one to show.
    """
    try:
        field = model._meta.get_field(name)
    except Exception:
        return None

    if not field.has_default():
        return None

    return field.get_default()


def plain(value: Any) -> Any:
    """A value as a form sends it: a record by its key."""
    from django.db import models

    if isinstance(value, models.Model):
        return value.pk

    return value


def label_of(resource: Any, model: Any, name: str, value: Any) -> str:
    """The label a relation's control shows for ``value``."""
    from django.db import models

    field = model._meta.get_field(name)
    record = value

    if not isinstance(record, models.Model):
        record = field.related_model._default_manager.filter(pk=value).first()

    if record is None:
        return ""

    owner = resource.site.get_resource(field.related_model)

    return owner.get_object_label(record) if owner else str(record)


def add_options(resource: Any, request: Any, context: Any) -> dict[str, Any]:
    """What a grid needs to add rows, or nothing when it may not.

    The controls of a new row - the columns it writes, described as the
    form describes them - where each one starts, and where the row is
    sent. A reader who may not add sees no button at all.
    """
    from generic.api.columns import json_safe
    from generic.sites.grids import with_query

    if not (context.allow_add and resource.has_add_permission(request)):
        return {}

    url = resource.get_rows_url()

    if not url:
        return {}

    described: dict[str, Any] = {}
    initial: dict[str, Any] = {}
    labels: dict[str, dict[str, str]] = {}

    for name in context.creatable:
        if not resource.can_edit_column(request, name, None):
            continue

        column = resolve(resource, name)
        schema = schema_for(resource, request, column)

        if schema is None or schema.get("readOnly"):
            continue

        described[name] = schema
        value = context.values.get(name, None)

        if value is None:
            value = starting_value(resource.model, name)

        if value is None:
            continue

        if schema.get("relation"):
            label = label_of(resource, resource.model, name, value)
            labels[name] = {str(plain(value)): label}

        initial[name] = json_safe(plain(value))

    if not described:
        return {}

    return {
        "url": with_query(url, context.query),
        "columns": described,
        "initial": initial,
        "labels": labels,
    }


def create(
    resource: Any,
    request: Any,
    values: dict[str, Any],
    fixed: dict[str, Any],
) -> Any:
    """Validate and save one new row, as the add form would.

    ``values`` are the row's cells, by column name; ``fixed`` what the
    grid imposes, by field name - the record the rows belong to. The
    resource's own form serializer decides, so a new row is refused
    exactly where the add form refuses one. Its errors are keyed by
    field, which for a row's own columns is the column's name.
    """
    data = {name: plain(value) for name, value in values.items()}

    for field, value in fixed.items():
        data.setdefault(field, plain(value))

    serializer = resource.get_form_serializer_class()(
        data=data,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        resource.save_model(request, serializer, change=False)

    return serializer.instance


def row_errors(
    resource: Any,
    detail: Any,
    shown: Any,
) -> dict[str, Any]:
    """Errors keyed by the cells that show them; the rest for the row.

    A field the row has no cell for - a required one the grid does not
    show - is named, so the message says what is missing.
    """
    if not isinstance(detail, dict):
        return {"detail": [str(item) for item in detail]}

    errors: dict[str, Any] = {}
    other: list[str] = []

    for field, messages in detail.items():
        messages = [str(message) for message in messages]

        if field in shown:
            errors[field] = messages
            continue

        try:
            label = str(resource.model._meta.get_field(field).verbose_name)
        except Exception:
            label = ""

        for message in messages:
            other.append(
                f"{label[:1].upper()}{label[1:]}: {message}"
                if label
                else message
            )

    if other:
        errors["detail"] = other

    return errors


__all__ = [
    "EditableColumn",
    "add_options",
    "as_grid",
    "columns_of",
    "create",
    "default_context",
    "may_edit",
    "own_columns",
    "resolve",
    "schemas",
    "target_of",
    "write",
]

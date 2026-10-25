"""Custom fields in a resource's serializers: columns and form fields.

A resource's serializers are built once per process, from what the code
declares. Custom fields change while it runs, so they are added on the
way out, per request, the way ``field_permissions`` takes fields away
(:func:`generic.sites.serializers.restricted`): the generated class is
extended with one field per definition, and every table and form reads
that class - the columns, the filters, the order, the search, the
exports, the form's schema, what is validated and saved.

The extended classes are kept per set of definitions (each definition's
key and last change), so a request builds nothing a previous one built.
"""

from __future__ import annotations

import datetime
from collections import OrderedDict
from types import MethodType
from typing import Any, Sequence

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from generic.api.columns import (
    FILTER_MULTISELECT,
    BooleanColumn,
    CharColumn,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    IntegerColumn,
    TagsColumn,
)
from generic.api.tags import TagStyle
from generic.customfields.models import (
    DECIMAL_DIGITS,
    DECIMAL_PLACES,
    LONG_TEXT_MAX_LENGTH,
    TEXT_MAX_LENGTH,
    CustomField,
)
from generic.customfields.values import load, write

#: The form's and the summary's section of custom fields.
SECTION = "custom-fields"

#: Places after the declared ones, in the form and in the table.
POSITION = 100_000

#: The extended classes kept, the oldest dropped first.
CACHE_SIZE = 256

_CLASSES: OrderedDict[tuple[Any, ...], Any] = OrderedDict()

#: The largest whole number a value may be (a 64-bit column).
INTEGER_LIMIT = 2**63 - 1


def _cached(key: tuple[Any, ...], build: Any) -> Any:
    found = _CLASSES.get(key)

    if found is not None:
        _CLASSES.move_to_end(key)

        return found

    found = build()
    _CLASSES[key] = found

    while len(_CLASSES) > CACHE_SIZE:
        _CLASSES.popitem(last=False)

    return found


def title_of(definition: CustomField) -> str:
    """A column's or a control's label, with its unit."""
    label = definition.label()

    return f"{label} ({definition.unit})" if definition.unit else label


# -- reading a record's value ---------------------------------------------


class CustomValueMixin:
    """A field reading a custom value: the row's annotation in a table,
    the record's values otherwise (a record just written, a form)."""

    custom_key: str = ""
    custom_resource: Any = None

    def get_attribute(self, instance: Any) -> Any:
        name = getattr(self, "custom_name", "")

        if name in getattr(instance, "__dict__", {}):
            return instance.__dict__[name]

        if (
            self.custom_resource is None
            or getattr(instance, "pk", None) is None
        ):
            return None

        return load(self.custom_resource, instance).get(self.custom_key)


def bind(field: Any, definition: CustomField, resource: Any) -> Any:
    field.custom_key = definition.key
    field.custom_name = definition.name
    field.custom_resource = resource

    # A form's field is one of DRF's own: it reads the value the same
    # way as a column does.
    if not isinstance(field, CustomValueMixin):
        field.get_attribute = MethodType(CustomValueMixin.get_attribute, field)

    return field


def _column_class(base: type) -> type:
    return type(f"Custom{base.__name__}", (CustomValueMixin, base), {})


CustomCharColumn = _column_class(CharColumn)
CustomIntegerColumn = _column_class(IntegerColumn)
CustomDecimalColumn = _column_class(DecimalColumn)
CustomBooleanColumn = _column_class(BooleanColumn)
CustomDateColumn = _column_class(DateColumn)
CustomDateTimeColumn = _column_class(DateTimeColumn)
CustomTagsColumn = _column_class(TagsColumn)


# -- columns --------------------------------------------------------------


def column_for(definition: CustomField, resource: Any) -> Any:
    """The table's column of one custom field.

    Its public name is the annotation the table's queryset carries
    (:func:`generic.customfields.values.annotations`): the cell, the
    filter, the order and the search all read it.
    """
    kind = definition.type
    common: dict[str, Any] = {
        "read_only": True,
        "allow_null": True,
        "title": title_of(definition),
        "visible": definition.in_list,
    }

    if kind == CustomField.Type.CHOICE:
        field = CustomTagsColumn(
            title=common["title"],
            visible=definition.in_list,
            choices=definition.choice_labels(),
            tag_style=TagStyle(colors=definition.choice_colors()),
            filter_type=FILTER_MULTISELECT,
            value_type="string",
            searchable=False,
            facetable=True,
        )
    elif kind == CustomField.Type.INTEGER:
        field = CustomIntegerColumn(**common)
    elif kind == CustomField.Type.DECIMAL:
        field = CustomDecimalColumn(
            max_digits=DECIMAL_DIGITS,
            decimal_places=definition.decimal_places,
            **common,
        )
    elif kind == CustomField.Type.BOOLEAN:
        field = CustomBooleanColumn(**common)
    elif kind == CustomField.Type.DATE:
        field = CustomDateColumn(**common)
    elif kind == CustomField.Type.DATETIME:
        field = CustomDateTimeColumn(**common)
    elif kind == CustomField.Type.TIME:
        # Ordered, not filtered: no filter of the tables compares times.
        field = CustomCharColumn(
            allow_blank=True,
            filterable=False,
            searchable=False,
            **common,
        )
    else:
        wide = kind == CustomField.Type.LONG_TEXT
        field = CustomCharColumn(
            allow_blank=True,
            class_name="dt-col--wide" if wide else None,
            facetable=True if kind == CustomField.Type.TEXT else None,
            **common,
        )

    return bind(field, definition, resource)


def signature(fields: Sequence[CustomField]) -> tuple[Any, ...]:
    return tuple(definition.signature() for definition in fields)


def with_columns(
    serializer_class: Any,
    resource: Any,
    fields: Sequence[CustomField],
) -> Any:
    """``serializer_class`` with a column per custom field, after its
    own."""
    fields = list(fields)

    if not fields:
        return serializer_class

    def build() -> Any:
        def get_fields(self: Any) -> Any:
            found = serializer_class.get_fields(self)

            for definition in fields:
                found[definition.name] = column_for(definition, resource)

            return found

        return type(
            serializer_class.__name__,
            (serializer_class,),
            {
                "get_fields": get_fields,
                "__module__": serializer_class.__module__,
                "generic_custom_fields": tuple(fields),
            },
        )

    return _cached(
        ("table", serializer_class, resource.label_lower, signature(fields)),
        build,
    )


# -- form fields ----------------------------------------------------------


def limits(definition: CustomField) -> tuple[Any, Any]:
    """The field's minimum and maximum, as values of its type; a limit
    that cannot be read is no limit (the definition's form refuses
    them)."""
    found = []

    for raw in (definition.minimum, definition.maximum):
        try:
            value = definition.limit(raw)
        except ValueError:
            value = None

        if isinstance(value, datetime.datetime) and timezone.is_naive(value):
            value = timezone.make_aware(value)

        found.append(value)

    return found[0], found[1]


def default_of(definition: CustomField) -> Any:
    """What the form of a new record starts with, if anything."""
    from generic.customfields.models import parse_value

    if not definition.default:
        return serializers.empty

    try:
        value = parse_value(definition.type, definition.default)
    except ValueError:
        return serializers.empty

    if (
        definition.type == CustomField.Type.CHOICE
        and value not in definition.choice_labels()
    ):
        return serializers.empty

    return value


def form_field_for(definition: CustomField, resource: Any) -> Any:
    """The form's control of one custom field: its type, its limits,
    whether it must be answered."""
    kind = definition.type
    minimum, maximum = limits(definition)
    default = default_of(definition)
    required = definition.required and default is serializers.empty
    common: dict[str, Any] = {
        "label": definition.label(),
        "help_text": definition.help_text() or None,
        "required": required,
        "allow_null": not definition.required,
    }

    if default is not serializers.empty:
        common["default"] = default

    if kind == CustomField.Type.CHOICE:
        field: Any = serializers.ChoiceField(
            choices=list(definition.choice_labels().items()),
            allow_blank=not definition.required,
            **common,
        )
    elif kind == CustomField.Type.INTEGER:
        field = serializers.IntegerField(
            min_value=minimum if minimum is not None else -INTEGER_LIMIT,
            max_value=maximum if maximum is not None else INTEGER_LIMIT,
            **common,
        )
    elif kind == CustomField.Type.DECIMAL:
        places = min(definition.decimal_places, DECIMAL_PLACES)
        field = serializers.DecimalField(
            max_digits=DECIMAL_DIGITS - DECIMAL_PLACES + places,
            decimal_places=places,
            min_value=minimum,
            max_value=maximum,
            **common,
        )
    elif kind == CustomField.Type.BOOLEAN:
        field = serializers.BooleanField(**common)
    elif kind in (
        CustomField.Type.DATE,
        CustomField.Type.TIME,
        CustomField.Type.DATETIME,
    ):
        validators: list[Any] = []

        if minimum is not None:
            validators.append(MinValueValidator(minimum))

        if maximum is not None:
            validators.append(MaxValueValidator(maximum))

        field_class = {
            CustomField.Type.DATE: serializers.DateField,
            CustomField.Type.TIME: serializers.TimeField,
            CustomField.Type.DATETIME: serializers.DateTimeField,
        }[kind]
        field = field_class(validators=validators, **common)
    else:
        longest = (
            LONG_TEXT_MAX_LENGTH
            if kind == CustomField.Type.LONG_TEXT
            else TEXT_MAX_LENGTH
        )
        field_class = {
            CustomField.Type.EMAIL: serializers.EmailField,
            CustomField.Type.URL: serializers.URLField,
        }.get(kind, serializers.CharField)
        field = field_class(
            max_length=min(definition.max_length or longest, longest),
            min_length=definition.min_length or None,
            allow_blank=not definition.required,
            **common,
        )

    return bind(field, definition, resource)


class CustomFormMixin:
    """What the extended form does with the values: kept out of the
    model's create and update, written with the record, in one
    transaction."""

    generic_custom_fields: tuple[CustomField, ...] = ()
    generic_custom_resource: Any = None

    def split_custom(self, validated_data: dict[str, Any]) -> tuple:
        names = {
            definition.name: definition.key
            for definition in self.generic_custom_fields
        }
        own = {
            name: value
            for name, value in validated_data.items()
            if name not in names
        }
        custom = {
            names[name]: value
            for name, value in validated_data.items()
            if name in names
        }

        return own, custom

    def create(self, validated_data: dict[str, Any]) -> Any:
        own, custom = self.split_custom(validated_data)

        with transaction.atomic():
            instance = super().create(own)  # type: ignore[misc]
            write(self.generic_custom_resource, instance, custom)

        return instance

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        own, custom = self.split_custom(validated_data)

        with transaction.atomic():
            instance = super().update(instance, own)  # type: ignore[misc]
            write(self.generic_custom_resource, instance, custom)

        return instance


def with_form_fields(
    serializer_class: Any,
    resource: Any,
    fields: Sequence[CustomField],
    section: Any,
) -> Any:
    """``serializer_class`` with a control per custom field, in a
    section of their own after the declared ones."""
    fields = list(fields)

    if not fields:
        return serializer_class

    def build() -> Any:
        def get_fields(self: Any) -> Any:
            found = serializer_class.get_fields(self)

            for definition in fields:
                found[definition.name] = form_field_for(definition, resource)

            return found

        overrides = {
            definition.name: {
                "section": SECTION,
                "position": POSITION + index,
                "width": (
                    12 if definition.type == CustomField.Type.LONG_TEXT else 6
                ),
                **(
                    {"widget": "textarea", "rows": 3}
                    if definition.type == CustomField.Type.LONG_TEXT
                    else {}
                ),
                **(
                    {"step": float(10**-definition.decimal_places)}
                    if definition.type == CustomField.Type.DECIMAL
                    else {}
                ),
            }
            for index, definition in enumerate(fields)
        }

        return type(
            serializer_class.__name__,
            (CustomFormMixin, serializer_class),
            {
                "get_fields": get_fields,
                "__module__": serializer_class.__module__,
                "form_overrides": overrides,
                "form_sections": (
                    {
                        "name": SECTION,
                        "title": section,
                        "description": "",
                        "position": POSITION,
                    },
                ),
                "generic_custom_fields": tuple(fields),
                "generic_custom_resource": resource,
            },
        )

    return _cached(
        ("form", serializer_class, resource.label_lower, signature(fields)),
        build,
    )


__all__ = [
    "SECTION",
    "column_for",
    "form_field_for",
    "with_columns",
    "with_form_fields",
]

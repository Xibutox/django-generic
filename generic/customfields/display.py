"""Custom values on a record's summary page and in its history.

Both already know how to write out a model field's value - a choice as
its label, a decimal to its places, a date in the reader's language.
A custom field is described to them as a model field of its type, built
for the occasion and never attached to the model, so they write its
values exactly like the model's own.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.utils.text import capfirst

from generic.customfields.models import (
    DECIMAL_DIGITS,
    CustomField,
)


def model_field(definition: CustomField, name: str | None = None) -> Any:
    """A model field shaped like ``definition``, named ``name``."""
    kind = definition.type
    options: dict[str, Any] = {
        "verbose_name": definition.label(),
        "null": True,
        "blank": True,
    }

    if kind == CustomField.Type.CHOICE:
        field: Any = models.CharField(
            max_length=255,
            choices=list(definition.choice_labels().items()),
            **options,
        )
    elif kind == CustomField.Type.LONG_TEXT:
        field = models.TextField(**options)
    elif kind == CustomField.Type.EMAIL:
        field = models.EmailField(**options)
    elif kind == CustomField.Type.URL:
        field = models.URLField(**options)
    elif kind == CustomField.Type.INTEGER:
        field = models.BigIntegerField(**options)
    elif kind == CustomField.Type.DECIMAL:
        field = models.DecimalField(
            max_digits=DECIMAL_DIGITS,
            decimal_places=definition.decimal_places,
            **options,
        )
    elif kind == CustomField.Type.BOOLEAN:
        field = models.BooleanField(**options)
    elif kind == CustomField.Type.DATE:
        field = models.DateField(**options)
    elif kind == CustomField.Type.TIME:
        field = models.TimeField(**options)
    elif kind == CustomField.Type.DATETIME:
        field = models.DateTimeField(**options)
    else:
        field = models.CharField(max_length=255, **options)

    field.set_attributes_from_name(name or definition.name)

    return field


def history_fields(resource: Any, request: Any) -> dict[str, Any]:
    """``{"cf:<key>": field}`` of the custom fields the reader may see,
    the archived ones included: an old version may hold their values."""
    from generic.customfields.definitions import visible

    return {
        definition.history_name: model_field(
            definition, definition.history_name
        )
        for definition in visible(resource, request, archived=True)
    }


def summary_section(
    resource: Any,
    request: Any,
    obj: Any,
) -> dict[str, Any] | None:
    """The summary page's section of custom fields, or ``None``."""
    from django.utils.encoding import force_str

    from generic.api.tags import TagStyle
    from generic.customfields.definitions import declaration
    from generic.customfields.values import load
    from generic.sites.summary import describe_field, describe_tags

    declared = declaration(resource)

    if declared is None:
        return None

    fields = resource.get_custom_fields(request)

    if not fields:
        return None

    values = load(resource, obj)
    holder = _Holder(
        {definition.name: values.get(definition.key) for definition in fields}
    )
    entries = []

    for definition in fields:
        field = model_field(definition)

        if definition.type == CustomField.Type.CHOICE:
            value = values.get(definition.key)
            entry = describe_tags(
                resource.site,
                request,
                TagStyle(colors=definition.choice_colors()),
                [value] if value not in (None, "") else [],
                definition.choice_labels(),
            )
        else:
            entry = describe_field(_Plain(resource), request, holder, field)

        unit = definition.unit

        if unit and entry.get("display") and definition.is_number:
            entry["display"] = f"{entry['display']} {unit}"

        entry.update(
            name=definition.name,
            label=capfirst(force_str(definition.label())),
        )
        entry["wide"] = bool(entry.get("multiline"))
        entries.append(entry)

    return {
        "name": "custom-fields",
        "title": force_str(declared.section),
        "description": "",
        "collapsed": False,
        "fields": entries,
    }


class _Holder:
    """The values, read the way a record's attributes are."""

    def __init__(self, values: dict[str, Any]) -> None:
        self.__dict__.update(values)


class _Plain:
    """The resource, as :func:`describe_field` asks it about a field
    nothing draws as tags."""

    def __init__(self, resource: Any) -> None:
        self.site = resource.site

    def get_tag_style(self, name: str) -> None:
        return None


__all__ = ["history_fields", "model_field", "summary_section"]

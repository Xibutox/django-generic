"""Schema driven forms.

DRF stays the single source of truth. Field types, writability, required
flags, choices and limits are all read off the serializer, so a field
added to a serializer appears in the form without touching the frontend.

``form_overrides`` only ever carries presentation: labels, placeholders,
section and position, widget hints, and the related object editor. It
cannot make a read only field writable or relax a validation rule.

Relation fields describe how they are fed - an autocomplete endpoint or
a capped list of choices - and a record carries the labels of its current
related values under ``_display``; see :mod:`generic.api.relations`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from django.db import models
from django.db.models import NOT_PROVIDED
from django.urls import NoReverseMatch, reverse
from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.fields import empty

from generic.api.columns import json_safe
from generic.api.files import FormFileField, FormImageField, accept_of
from generic.api.relations import (
    DISPLAY_KEY,
    LABEL_KEY,
    build_display_labels,
    describe_relation,
    is_related_field,
)
from generic.conf import generic_settings

#: DRF field class -> frontend field type. Ordered from the most
#: specific to the most general, because ``EmailField`` is a
#: ``CharField`` and ``ChoiceField`` covers ``MultipleChoiceField``.
FIELD_TYPE_MAPPING: tuple[tuple[type[serializers.Field], str], ...] = (
    (serializers.BooleanField, "boolean"),
    (serializers.IntegerField, "integer"),
    (serializers.DecimalField, "decimal"),
    (serializers.FloatField, "float"),
    (serializers.DateTimeField, "datetime"),
    (serializers.DateField, "date"),
    (serializers.TimeField, "time"),
    (serializers.DurationField, "duration"),
    (serializers.EmailField, "email"),
    (serializers.URLField, "url"),
    (serializers.SlugField, "slug"),
    (serializers.UUIDField, "uuid"),
    # An image field is a file field: the image first.
    (serializers.ImageField, "image"),
    (serializers.FileField, "file"),
    (serializers.MultipleChoiceField, "multiselect"),
    (serializers.ChoiceField, "select"),
    (serializers.JSONField, "json"),
    (serializers.ListField, "list"),
    (serializers.CharField, "text"),
)

#: Field types drawn as a file chooser.
FILE_TYPES = frozenset({"file", "image"})

DEFAULT_SECTION = {
    "name": "general",
    "title": _("General information"),
    "description": "",
    "position": 0,
}

__all__ = [
    "DEFAULT_SECTION",
    "DISPLAY_KEY",
    "FIELD_TYPE_MAPPING",
    "FILE_TYPES",
    "FormModelSerializer",
    "FormSerializer",
    "FormSerializerMixin",
    "get_field_choices",
    "get_field_default",
    "get_field_type",
    "is_related_field",
    "remove_none_values",
    "resolve_related_editor_url",
]


def remove_none_values(data: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None`` entries, keeping ``False``, ``0`` and ``""``.

    Those three are meaningful form values; only a missing value is
    worth omitting from the payload.
    """
    return {key: value for key, value in data.items() if value is not None}


def get_field_type(field: serializers.Field) -> str:
    """Infer the frontend field type from a DRF serializer field."""
    if isinstance(field, serializers.ManyRelatedField):
        return "multiselect"

    if isinstance(field, serializers.RelatedField):
        return "select"

    if isinstance(field, serializers.ListSerializer):
        return "list"

    if isinstance(field, serializers.BaseSerializer):
        return "object"

    for field_class, field_type in FIELD_TYPE_MAPPING:
        if isinstance(field, field_class):
            return field_type

    return "text"


def get_field_default(field: serializers.Field) -> Any:
    """The default worth sending to the client.

    An add form opens on the defaults, the way the admin's does, so the
    model's own default counts: DRF turns one into ``required=False``
    and keeps the value to itself, which would leave the field blank
    with no sign that anything was declared.

    A callable default is skipped either way: it is resolved server side
    on save, and calling it here would freeze a value such as ``now``
    into the schema.
    """
    default = field.default

    if default is empty:
        default = model_field_default(field)

    if default is empty or default is None or callable(default):
        return None

    # The schema travels as JSON: a default that is an object of a
    # library's own - a time zone, an enum - would break the whole form
    # rather than that one field.
    return json_safe(default)


def model_field_default(field: serializers.Field) -> Any:
    """The default declared on the model behind a serializer field."""
    parent = getattr(field, "parent", None)
    model = getattr(getattr(parent, "Meta", None), "model", None)

    if model is None or not field.field_name:
        return empty

    try:
        model_field = model._meta.get_field(field.field_name)
    except Exception:
        # A method field, an annotation, a name the model does not know.
        return empty

    default = getattr(model_field, "default", NOT_PROVIDED)

    # Django's own "nothing was declared", which is not a value.
    return empty if default is NOT_PROVIDED else default


def get_field_choices(
    field: serializers.Field,
) -> list[dict[str, Any]]:
    """Fixed choices of a choice field.

    Never of a relation: DRF would list every row of the related table.
    Relations are described by :func:`describe_relation` instead.
    """
    if is_related_field(field):
        return []

    choices = getattr(field, "choices", None)

    if not choices:
        return []

    return [
        {"value": json_safe(value), "label": force_str(label)}
        for value, label in choices.items()
    ]


def resolve_related_editor_url(
    configuration: dict[str, Any],
    *,
    field_name: str,
) -> dict[str, Any]:
    """Resolve the optional named frontend editor route.

    The frontend convention is::

        create: <relatedEditorUrl>
        update: <relatedEditorUrl><pk>/

    The route must therefore reverse without a primary key. A literal
    ``relatedEditorUrl`` stays supported as an escape hatch.
    """
    result = dict(configuration)
    view_name = result.pop("relatedEditorView", None)

    if not view_name:
        return result

    try:
        result["relatedEditorUrl"] = reverse(view_name)
    except NoReverseMatch as error:
        raise RuntimeError(
            f"Unable to reverse relatedEditorView '{view_name}' for "
            f"serializer field '{field_name}'. The route must be "
            f"reversible without a primary key."
        ) from error

    return result


class FormSerializerMixin:
    """Expose frontend form metadata for a DRF serializer."""

    #: Presentation only. Merged along the MRO, so a subclass states
    #: just what it changes.
    form_overrides: dict[str, dict[str, Any]] = {}

    #: Sections the fields are laid out in. Merged along the MRO by
    #: section name. A section may set ``collapsed`` to start closed and
    #: ``tab`` to be drawn as a tab rather than a card.
    form_sections: tuple[dict[str, Any], ...] = (DEFAULT_SECTION,)

    @classmethod
    def get_merged_form_overrides(cls) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}

        for klass in reversed(cls.__mro__):  # type: ignore[attr-defined]
            declared = vars(klass).get("form_overrides", {})

            for field_name, configuration in declared.items():
                merged.setdefault(field_name, {}).update(configuration)

        return merged

    @classmethod
    def get_form_sections(cls) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}

        for klass in reversed(cls.__mro__):  # type: ignore[attr-defined]
            for section in vars(klass).get("form_sections", ()):
                name = section["name"]
                merged.setdefault(name, {}).update(deepcopy(section))

        sections = [
            {
                **section,
                "title": force_str(section.get("title", "")),
                "description": force_str(section.get("description", "")),
            }
            for section in merged.values()
        ]
        sections.sort(key=lambda section: section.get("position", 0))

        return sections

    @classmethod
    def get_form_serializer(cls, request: Any = None) -> Any:
        context = {"request": request} if request is not None else {}

        return cls(context=context)  # type: ignore[call-arg]

    @classmethod
    def resolve_widget(
        cls,
        field: serializers.Field,
        field_type: str,
        overrides: dict[str, Any],
    ) -> str:
        widget = overrides.get("widget", field_type)

        # A model TextField comes through DRF as an unbounded CharField
        # carrying a textarea style hint; the override stays for a plain
        # serializer that has no such hint.
        style = getattr(field, "style", None) or {}

        if widget == "text" and getattr(field, "max_length", None) is None:
            if overrides.get("multiline", False) or (
                style.get("base_template") == "textarea.html"
                and overrides.get("multiline", True)
            ):
                widget = "textarea"

        return widget

    @classmethod
    def build_form_field(
        cls,
        field_name: str,
        field: serializers.Field,
        overrides: dict[str, Any],
        request: Any = None,
    ) -> dict[str, Any] | None:
        """Build one JSON safe field configuration."""
        if overrides.get("enabled") is False:
            return None

        overrides = resolve_related_editor_url(
            overrides,
            field_name=field_name,
        )

        field_type = get_field_type(field)
        widget = cls.resolve_widget(field, field_type, overrides)

        configuration = {
            "name": field_name,
            "type": field_type,
            "widget": widget,
            "label": force_str(
                overrides.get("label")
                or field.label
                or field_name.replace("_", " ").capitalize()
            ),
            "required": field.required,
            "readOnly": field.read_only,
            "writeOnly": field.write_only,
            "allowNull": field.allow_null,
            "allowBlank": getattr(field, "allow_blank", None),
            "default": get_field_default(field),
            "helpText": cls.resolve_help_text(field, overrides),
            "placeholder": overrides.get("placeholder"),
            "section": overrides.get(
                "section",
                generic_settings.FORM_DEFAULT_SECTION,
            ),
            "position": overrides.get("position", 0),
            "width": overrides.get("width", 12),
            "rows": overrides.get("rows"),
            "minimum": getattr(field, "min_value", None),
            "maximum": getattr(field, "max_value", None),
            "minLength": getattr(field, "min_length", None),
            "maxLength": getattr(field, "max_length", None),
            "step": overrides.get("step"),
            "choices": get_field_choices(field) or None,
            "relation": overrides.get(
                "relation",
                is_related_field(field),
            ),
            "relatedEditorUrl": overrides.get("relatedEditorUrl"),
            "relatedCreateUrl": overrides.get("relatedCreateUrl"),
            "relatedUpdateUrl": overrides.get("relatedUpdateUrl"),
            "relatedPopupWidth": overrides.get(
                "relatedPopupWidth",
                generic_settings.FORM_RELATED_POPUP_WIDTH,
            ),
            "relatedPopupHeight": overrides.get(
                "relatedPopupHeight",
                generic_settings.FORM_RELATED_POPUP_HEIGHT,
            ),
            "autocompleteUrl": overrides.get("autocompleteUrl"),
            # What a file chooser offers, and the largest file it takes:
            # both checked in the browser before anything is sent, and
            # by the server again.
            "accept": overrides.get("accept", cls.resolve_accept(field)),
            "maxSize": (
                generic_settings.FILE_MAX_SIZE
                if field_type in FILE_TYPES
                else None
            ),
            # Carried with the record but never drawn, the way the admin
            # treats a record's own key.
            "hidden": overrides.get(
                "hidden",
                cls.is_own_key(field_name, field),
            )
            or None,
        }

        # A read only relation only needs its label, which the record
        # carries; describing how to edit it would be wasted work.
        if is_related_field(field) and not field.read_only:
            for key, value in describe_relation(field, request).items():
                if configuration.get(key) is None:
                    configuration[key] = value

        return remove_none_values(configuration)

    @classmethod
    def is_own_key(cls, field_name: str, field: serializers.Field) -> bool:
        """Whether ``field_name`` is the read only primary key."""
        model = getattr(getattr(cls, "Meta", None), "model", None)

        return bool(
            field.read_only
            and model is not None
            and field_name == model._meta.pk.name
        )

    @staticmethod
    def resolve_accept(field: serializers.Field) -> str | None:
        """The ``accept`` attribute of a file field's chooser."""
        if not isinstance(field, serializers.FileField):
            return None

        return accept_of(field)

    @staticmethod
    def resolve_help_text(
        field: serializers.Field,
        overrides: dict[str, Any],
    ) -> str | None:
        if "helpText" in overrides:
            return overrides["helpText"]

        return force_str(field.help_text) if field.help_text else None

    @classmethod
    def get_form_fields(
        cls,
        request: Any = None,
    ) -> list[dict[str, Any]]:
        serializer = cls.get_form_serializer(request)
        overrides = cls.get_merged_form_overrides()
        result: list[dict[str, Any]] = []

        for index, (field_name, field) in enumerate(serializer.fields.items()):
            configuration = cls.build_form_field(
                field_name,
                field,
                overrides.get(field_name, {}),
                request=request,
            )

            if configuration is None:
                continue

            configuration["_declarationIndex"] = index
            result.append(configuration)

        # Position first, declaration order second, so a subclass can
        # slot a field in without renumbering the others.
        result.sort(
            key=lambda item: (
                item.get("position", 0),
                item["_declarationIndex"],
            )
        )

        for configuration in result:
            configuration.pop("_declarationIndex", None)

        return result

    @classmethod
    def get_form_schema(cls, request: Any = None) -> dict[str, Any]:
        fields = cls.get_form_fields(request=request)
        sections = cls.get_form_sections()
        known_sections = {section["name"] for section in sections}

        # A field pointing at a section nobody declared would silently
        # vanish from the rendered form.
        unknown = {
            field["section"]
            for field in fields
            if field.get("section") not in known_sections
        }

        if unknown:
            raise RuntimeError(
                f"{cls.__name__} places fields in undeclared sections: "
                f"{', '.join(sorted(unknown))}. Declare them in "
                f"form_sections."
            )

        return {
            "version": 2,
            "sections": sections,
            "fields": fields,
            "displayKey": DISPLAY_KEY,
        }

    def to_representation(self, instance: Any) -> Any:
        data = super().to_representation(instance)  # type: ignore[misc]
        labels = build_display_labels(self, instance)  # type: ignore[arg-type]

        if labels:
            data[DISPLAY_KEY] = labels

        # How the record calls itself: the title of an inline card, the
        # name in a confirmation.
        if getattr(instance, "pk", None) is not None:
            data.setdefault(LABEL_KEY, force_str(instance))

        return data


class FormSerializer(FormSerializerMixin, serializers.Serializer):
    """Plain serializer rendered by the generic form."""


class FormModelSerializer(
    FormSerializerMixin,
    serializers.ModelSerializer,
):
    """Model serializer rendered by the generic form.

    A model's file field reads as ``{"name", "url", "size"}`` and takes
    an upload (:mod:`generic.api.files`).
    """

    serializer_field_mapping = {
        **serializers.ModelSerializer.serializer_field_mapping,
        models.FileField: FormFileField,
        models.ImageField: FormImageField,
    }

    def build_standard_field(
        self,
        field_name: str,
        model_field: Any,
    ) -> tuple[Any, dict[str, Any]]:
        field_class, field_kwargs = super().build_standard_field(
            field_name, model_field
        )

        # A file field that may be blank may be emptied: null, in JSON,
        # is how a form says "remove it".
        if isinstance(model_field, models.FileField) and model_field.blank:
            field_kwargs["allow_null"] = True

        return field_class, field_kwargs

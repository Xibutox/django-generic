"""One form over several models: ``ModelsForm`` and its ``FormPart``.

A resource's form writes one record, with its inline rows. Some screens
write several records at once - a customer and its first ticket, a
person and their account - and the reader should see one form, saved
or refused as a whole::

    class NewCustomerForm(ModelsForm):
        parts = (
            FormPart("customer", Customer,
                     fields=("name", "code", "segment"),
                     title=_("Customer")),
            FormPart("ticket", Ticket,
                     fields=("title", "team", "priority"),
                     title=_("First ticket"),
                     links={"customer": "customer"}),
        )

Each part is validated by a model serializer of its own - the model's
validators, unique checks included, exactly as on the record's own form -
and drawn as a section of the form. Its fields are named
``<part>__<field>`` in the schema and the payload, so two parts may
both have a ``name``. The parts are saved in order, in one transaction:
``links`` hands a later part the record an earlier one wrote.

The class is a ``FormSerializer``: fields declared on it are questions
of the form itself (send a welcome mail?), and ``validate`` sees every
part's values, under the part's name, for a rule across models.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from django.core.exceptions import ImproperlyConfigured
from django.db import models, transaction
from django.db.models import NOT_PROVIDED
from django.utils.text import capfirst
from rest_framework import serializers
from rest_framework.settings import api_settings

from generic.api.columns import json_safe
from generic.api.forms import (
    FormModelSerializer,
    FormSerializer,
    narrow_relations,
)
from generic.api.relations import DISPLAY_KEY

#: Between a part's name and its field's, in the schema and the payload.
SEPARATOR = "__"

PART_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class FormPart:
    """One model's share of a :class:`ModelsForm`.

    ``model`` and ``fields`` (or ``exclude``) build the part's model
    serializer; ``serializer`` gives one instead - a
    ``FormModelSerializer`` whose ``form_overrides`` then apply too.
    ``links`` maps a field of this part's model to the name of an earlier
    part: the record that part saved is set on it.
    """

    name: str
    model: type[models.Model] | None = None
    fields: Iterable[str] | str | None = None
    exclude: Iterable[str] | None = None
    serializer: type[serializers.ModelSerializer] | None = None
    title: Any = ""
    description: Any = ""
    links: Mapping[str, str] = field(default_factory=dict)
    position: int | None = None
    collapsed: bool = False
    #: Built from the rest: the model serializer validating the part.
    serializer_class: Any = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not PART_NAME.match(self.name) or SEPARATOR in self.name:
            raise ImproperlyConfigured(
                f"FormPart {self.name!r}: a part's name is lower case "
                f"letters, digits and single underscores, starting with a "
                f"letter."
            )

        if (self.model is None) == (self.serializer is None):
            raise ImproperlyConfigured(
                f"FormPart {self.name!r} needs a model or a serializer, "
                f"not both."
            )

        if self.serializer is not None and (self.fields or self.exclude):
            raise ImproperlyConfigured(
                f"FormPart {self.name!r}: fields and exclude belong to "
                f"its serializer's Meta when a serializer is given."
            )

        model = self.get_model()

        for field_name in self.links:
            try:
                model._meta.get_field(field_name)
            except Exception as error:
                raise ImproperlyConfigured(
                    f"FormPart {self.name!r} links {field_name!r}, which "
                    f"is not a field of {model.__name__}."
                ) from error

        object.__setattr__(self, "serializer_class", self.build_serializer())

    def get_model(self) -> type[models.Model]:
        if self.serializer is not None:
            return self.serializer.Meta.model

        return self.model  # type: ignore[return-value]

    def build_serializer(self) -> type[serializers.ModelSerializer]:
        if self.serializer is not None:
            return self.serializer

        meta: dict[str, Any] = {"model": self.model}

        if self.exclude:
            meta["exclude"] = tuple(self.exclude)
        else:
            fields = self.fields or "__all__"
            meta["fields"] = (
                fields if isinstance(fields, str) else tuple(fields)
            )

        name = f"{self.model.__name__}PartSerializer"  # type: ignore

        return type(
            name,
            (FormModelSerializer,),
            {"Meta": type("Meta", (), meta), "__module__": __name__},
        )

    def prefix(self) -> str:
        return f"{self.name}{SEPARATOR}"

    def get_section(self, position: int) -> dict[str, Any]:
        model = self.get_model()

        return {
            "name": self.name,
            "title": self.title or capfirst(model._meta.verbose_name),
            "description": self.description,
            "position": position if self.position is None else self.position,
            "collapsed": self.collapsed or None,
        }


def part_default(part: FormPart, field_name: str) -> Any:
    """The model's default for a field of ``part``, as the schema sends
    it: the form opens on it, as a record's add form does."""
    try:
        model_field = part.get_model()._meta.get_field(field_name)
    except Exception:
        return None

    default = getattr(model_field, "default", NOT_PROVIDED)

    if default is NOT_PROVIDED or default is None or callable(default):
        return None

    return json_safe(default)


class ModelsForm(FormSerializer):
    """A form writing a record of each of its ``parts``, all or none.

    ``instance``, when given, maps a part's name to the record it edits:
    ``ModelsForm(instance={"user": user, "profile": user.profile})``.
    A part without one creates its record.

    Override ``get_save_kwargs(part, saved)`` for what a part's record
    needs besides its fields and links (a number, the author), and
    ``save_part(part, serializer, saved)`` to save it some other way.
    """

    parts: tuple[FormPart, ...] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        names = [part.name for part in cls.parts]
        seen: set[str] = set()

        for part in cls.parts:
            if part.name in seen:
                raise ImproperlyConfigured(
                    f"{cls.__name__} declares the part {part.name!r} twice."
                )

            for target in part.links.values():
                if target not in seen:
                    raise ImproperlyConfigured(
                        f"{cls.__name__}: part {part.name!r} links to "
                        f"{target!r}, which is not a part declared before "
                        f"it ({', '.join(sorted(seen)) or 'none'})."
                    )

            seen.add(part.name)

        clashes = set(names) & set(cls._declared_fields)

        if clashes:
            raise ImproperlyConfigured(
                f"{cls.__name__}: {', '.join(sorted(clashes))} is both a "
                f"part and a field of the form."
            )

    # -- the parts' serializers -----------------------------------------

    def get_part_instance(self, part: FormPart) -> Any:
        instance = self.instance

        if isinstance(instance, Mapping):
            return instance.get(part.name)

        return None

    def get_part_serializer(self, part: FormPart, **kwargs: Any) -> Any:
        return part.serializer_class(
            self.get_part_instance(part),
            context=self.context,
            **kwargs,
        )

    @property
    def part_serializers(self) -> dict[str, Any]:
        """Each part's serializer, once the form has been validated."""
        return getattr(self, "_part_serializers", {})

    # -- fields ----------------------------------------------------------

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        copies: dict[str, serializers.Field] = {}

        for part in self.parts:
            serializer = self.get_part_serializer(part)
            model = part.get_model()

            for name, part_field in serializer.fields.items():
                # The record's own key is not a question.
                if part_field.read_only and name == model._meta.pk.name:
                    continue

                # Filled from an earlier part, not asked.
                if name in part.links:
                    continue

                # A copy, unbound: the part's own serializer keeps its
                # field, with the name its validators know it by.
                copied = deepcopy(part_field)
                # Bound under its own name, the part's field took its label
                # from it; bound here, it would read "Customer  name".
                copied.label = part_field.label
                copies[part.prefix() + name] = copied

        # A deep copy is built again from the field's arguments, which
        # forgets the part's narrowing: narrowed again here, so the
        # schema offers no more than the part accepts.
        narrow_relations(copies, self.context.get("request"))
        fields.update(copies)

        return fields

    @property
    def _writable_fields(self) -> Any:
        # The form's own questions only: each part validates its fields.
        for name, form_field in self.fields.items():
            if not form_field.read_only and self.part_of(name) is None:
                yield form_field

    @classmethod
    def part_of(cls, field_name: str) -> FormPart | None:
        for part in cls.parts:
            if field_name.startswith(part.prefix()):
                return part

        return None

    # -- the schema --------------------------------------------------------

    @classmethod
    def get_form_sections(cls) -> list[dict[str, Any]]:
        sections = super().get_form_sections()
        known = {section["name"] for section in sections}
        start = max(
            (section.get("position", 0) for section in sections), default=0
        )

        for index, part in enumerate(cls.parts, start=1):
            if part.name in known:
                continue

            section = {
                key: value
                for key, value in part.get_section(start + index).items()
                if value is not None
            }
            sections.append(
                {
                    **section,
                    "title": str(section["title"]),
                    "description": str(section.get("description", "")),
                }
            )

        sections.sort(key=lambda section: section.get("position", 0))

        return sections

    @classmethod
    def build_form_field(
        cls,
        field_name: str,
        field: serializers.Field,
        overrides: dict[str, Any],
        request: Any = None,
    ) -> dict[str, Any] | None:
        part = cls.part_of(field_name)

        if part is not None:
            serializer = part.serializer_class
            own = field_name[len(part.prefix()) :]
            merged: dict[str, Any] = {"section": part.name}

            if hasattr(serializer, "get_merged_form_overrides"):
                inherited = dict(
                    serializer.get_merged_form_overrides().get(own, {})
                )
                # The part's serializer may have sections of its own,
                # which this form does not declare: its fields stay in
                # the part's section.
                inherited.pop("section", None)
                merged.update(inherited)

            merged.update(overrides)
            overrides = merged

        configuration = super().build_form_field(
            field_name, field, overrides, request=request
        )

        if part is not None and configuration is not None:
            if "default" not in configuration:
                default = part_default(part, own)

                if default is not None:
                    configuration["default"] = default

        return configuration

    # -- validation --------------------------------------------------------

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                {
                    api_settings.NON_FIELD_ERRORS_KEY: [
                        "Invalid data: expected a dictionary."
                    ]
                },
                code="invalid",
            )

        errors: dict[str, Any] = {}

        try:
            values = super().to_internal_value(data)
        except serializers.ValidationError as error:
            values = {}
            errors.update(error.detail)  # type: ignore[arg-type]

        self._part_serializers = {}

        for part in self.parts:
            prefix = part.prefix()
            own = {
                key[len(prefix) :]: value
                for key, value in data.items()
                if key.startswith(prefix)
            }
            serializer = self.get_part_serializer(part, data=own)
            self._part_serializers[part.name] = serializer

            if serializer.is_valid():
                values[part.name] = serializer.validated_data
                continue

            for key, messages in serializer.errors.items():
                if key == api_settings.NON_FIELD_ERRORS_KEY:
                    errors.setdefault(key, []).extend(
                        f"{part.get_section(0)['title']}: {message}"
                        for message in messages
                    )
                else:
                    errors[prefix + key] = messages

        if errors:
            raise serializers.ValidationError(errors)

        return values

    # -- saving ------------------------------------------------------------

    def create(self, validated_data: dict[str, Any]) -> dict[str, Any]:
        return self.save_parts()

    def update(self, instance: Any, validated_data: Any) -> dict[str, Any]:
        return self.save_parts()

    @transaction.atomic
    def save_parts(self) -> dict[str, Any]:
        """Save every part, in order; what each saved, by part name."""
        saved: dict[str, Any] = {}

        for part in self.parts:
            serializer = self.part_serializers[part.name]
            saved[part.name] = self.save_part(part, serializer, saved)

        return saved

    def save_part(
        self,
        part: FormPart,
        serializer: Any,
        saved: dict[str, Any],
    ) -> Any:
        kwargs = {
            field_name: saved[target]
            for field_name, target in part.links.items()
        }
        kwargs.update(self.get_save_kwargs(part, saved))

        return serializer.save(**kwargs)

    def get_save_kwargs(
        self,
        part: FormPart,
        saved: dict[str, Any],
    ) -> dict[str, Any]:
        """Values a part's record is saved with, besides its fields."""
        return {}

    # -- reading -------------------------------------------------------------

    def to_representation(self, instance: Any) -> dict[str, Any]:
        """Each part's record, its fields prefixed: the initial values
        of a form editing them."""
        data: dict[str, Any] = {}
        display: dict[str, Any] = {}
        records = instance if isinstance(instance, Mapping) else {}

        for part in self.parts:
            record = records.get(part.name)

            if record is None:
                continue

            serializer = part.serializer_class(record, context=self.context)

            for key, value in serializer.data.items():
                if key == DISPLAY_KEY:
                    display.update(
                        {
                            part.prefix() + name: label
                            for name, label in value.items()
                        }
                    )
                elif not key.startswith("_"):
                    data[part.prefix() + key] = value

        if display:
            data[DISPLAY_KEY] = display

        return data

    # -- permissions -------------------------------------------------------

    @classmethod
    def get_required_permissions(cls, instance: Any = None) -> list[str]:
        """Adding (or changing) a record of each part's model."""
        records = instance if isinstance(instance, Mapping) else {}
        permissions = []

        for part in cls.parts:
            options = part.get_model()._meta
            action = "change" if records.get(part.name) else "add"
            permissions.append(
                f"{options.app_label}.{action}_{options.model_name}"
            )

        return permissions


__all__ = ["FormPart", "ModelsForm", "SEPARATOR"]

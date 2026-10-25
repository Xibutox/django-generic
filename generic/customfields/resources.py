"""The page where people add fields to a model: *Customize fields*.

An ordinary resource over the definitions, so it has what every list
and form has - filters, history, exports - narrowed to the models the
reader may customize. Its form asks for a label (and a help text) in
each language the project offers, then for the limits of the type.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.models import Permission
from django.db.models import CharField, Value
from django.db.models.functions import Concat
from django.utils.encoding import force_str
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from rest_framework import serializers

from generic.customfields import TYPES
from generic.customfields.definitions import (
    customizable,
    declaration,
    enabled_resources,
    forget,
    max_fields,
    may_customize,
)
from generic.customfields.models import (
    DECIMAL_PLACES,
    KEY_PATTERN,
    LONG_TEXT_MAX_LENGTH,
    PREFIX,
    TEXT_MAX_LENGTH,
    CustomField,
    parse_choices,
    parse_value,
)
from generic.sites import ModelResource, TagStyle, action, display, site

#: The type tags of the list.
TYPE_COLORS = {
    "text": "#2563eb",
    "textarea": "#2563eb",
    "email": "#0891b2",
    "url": "#0891b2",
    "integer": "#16a34a",
    "decimal": "#16a34a",
    "boolean": "#7c3aed",
    "date": "#d97706",
    "time": "#d97706",
    "datetime": "#d97706",
    "choice": "#db2777",
}

#: The limits that mean something for each type.
LENGTH_TYPES = frozenset({"text", "textarea", "email", "url"})
RANGE_TYPES = frozenset({"integer", "decimal", "date", "time", "datetime"})


def languages() -> list[tuple[str, str]]:
    """``(code, name)`` of the languages labels are written in: the
    project's offered ones, else its own language alone."""
    from generic.i18n import offered_languages

    offered = offered_languages()

    if offered:
        return offered

    code = settings.LANGUAGE_CODE.split("-")[0]

    return [(code, code)]


def default_language() -> str:
    codes = [code for code, _name in languages()]
    wanted = settings.LANGUAGE_CODE

    for candidate in (wanted, wanted.split("-")[0]):
        if candidate in codes:
            return candidate

    return codes[0]


def model_key(resource: Any) -> str:
    return resource.label_lower


def resource_of(definition: CustomField) -> Any:
    if definition.content_type_id is None:
        return None

    model = definition.content_type.model_class()

    return site.get_resource(model) if model is not None else None


def list_url_for(target: Any) -> str:
    """The list of ``target``'s custom fields."""
    resource = site.get_resource(CustomField)

    if resource is None:
        return ""

    filters = {
        "match": "all",
        "conditions": [
            {
                "column": "model_display",
                "operator": "equals",
                "value": model_key(target),
            }
        ],
    }

    return f"{resource.get_list_url()}?filters={quote(json.dumps(filters))}"


class CustomFieldResource(ModelResource):
    """A model's custom fields, for whoever may customize it."""

    icon = "dynamic_form"
    label = _("custom field")
    label_plural = _("custom fields")
    description = _(
        "Fields added to the application's records, their labels, types "
        "and limits."
    )
    show_in_navigation = False

    list_display = (
        "label_display",
        "key",
        "model_display",
        "type",
        "required",
        "in_list",
        "position",
        "archived",
    )
    list_display_links = ("label_display",)
    search_fields = ("key", "labels")
    ordering = ("content_type", "position", "pk")
    tag_fields = {"type": TagStyle(colors=TYPE_COLORS)}
    list_select_related = ("content_type",)
    actions = ("archive", "restore", "delete_selected")
    duplicate = False
    watchable = False
    mailing = False

    detail_stats = ("model_display", "type", "required")
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    ("key", "position"),
                    ("labels_display", "help_texts_display"),
                    ("default", "unit"),
                    ("in_list", "archived"),
                )
            },
        ),
        (
            _("Limits"),
            {
                "fields": (
                    ("min_length", "max_length"),
                    ("minimum", "maximum"),
                    "decimal_places",
                    "choices",
                )
            },
        ),
        (
            _("Display and access"),
            {"fields": (("view_permission", "change_permission"),)},
        ),
    )

    def get_queryset(self, request: Any) -> Any:
        allowed = [
            resource.model for resource in customizable(self.site, request)
        ]

        from django.contrib.contenttypes.models import ContentType

        types = ContentType.objects.get_for_models(*allowed).values()

        return (
            super().get_queryset(request).filter(content_type__in=list(types))
        )

    def get_list_queryset(self, request: Any) -> Any:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                model_key=Concat(
                    "content_type__app_label",
                    Value("."),
                    "content_type__model",
                    output_field=CharField(),
                )
            )
        )

    # -- who --------------------------------------------------------------

    def allowed(self, request: Any, obj: Any = None) -> bool:
        # A definition not saved yet belongs to no model so far.
        if obj is None or obj.content_type_id is None:
            return bool(customizable(self.site, request))

        resource = resource_of(obj)

        return resource is not None and may_customize(resource, request)

    def has_view_permission(self, request: Any, obj: Any = None) -> bool:
        return self.allowed(request, obj)

    def has_add_permission(self, request: Any) -> bool:
        return self.allowed(request)

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return self.allowed(request, obj)

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return self.allowed(request, obj)

    # -- columns ----------------------------------------------------------

    @display(description=_("Label"), ordering="key")
    def label_display(self, definition: CustomField) -> str:
        return definition.label()

    @display(description=_("Labels"))
    def labels_display(self, definition: CustomField) -> str:
        return written_out(definition.labels)

    @display(description=_("Help texts"))
    def help_texts_display(self, definition: CustomField) -> str:
        return written_out(definition.help_texts)

    @display(
        description=_("Model"),
        ordering="model_key",
        filter_field="model_key",
    )
    def model_display(self, definition: CustomField) -> str:
        resource = resource_of(definition)

        if resource is None:
            return force_str(definition.content_type)

        return force_str(resource.get_label_plural()).capitalize()

    # -- the form ---------------------------------------------------------

    def get_fieldsets(self, request: Any = None) -> Any:
        codes = [code for code, _name in languages()]
        texts: list[Any] = [
            (f"label_{code}", f"help_{code}") for code in codes
        ]

        return (
            (
                None,
                {
                    "fields": (
                        ("model", "type"),
                        "key",
                        *texts,
                        ("required", "default"),
                    )
                },
            ),
            (
                _("Limits"),
                {
                    "fields": (
                        ("min_length", "max_length"),
                        ("minimum", "maximum"),
                        ("decimal_places", "unit"),
                        "choices",
                    ),
                    "description": _(
                        "Each type uses its own: lengths for texts, a "
                        "minimum and a maximum for numbers, dates and "
                        "times, places for decimals, the list for a "
                        "choice."
                    ),
                },
            ),
            (
                _("Display and access"),
                {
                    "fields": (
                        ("position", "in_list"),
                        ("view_permission", "change_permission"),
                        "archived",
                    )
                },
            ),
        )

    def get_fields(self, request: Any = None) -> Any:
        from generic.sites.serializers import flatten_fieldsets

        return flatten_fieldsets(self.get_fieldsets(request))

    form_overrides = {
        "choices": {"rows": 5},
    }

    _custom_form_serializer: Any = None

    def get_form_serializer_class(self) -> Any:
        if self._custom_form_serializer is None:
            self._custom_form_serializer = build_definition_serializer(
                super_class=self.build_generated_form()
            )

        return self._custom_form_serializer

    def build_generated_form(self) -> Any:
        from generic.sites.serializers import build_form_serializer

        codes = [code for code, _name in languages()]
        default = default_language()
        names = dict(languages())
        several = len(codes) > 1
        extra: dict[str, Any] = {
            # Every model open to custom fields, which the schema lists;
            # narrowed to the reader's own per request (get_fields).
            "model": serializers.ChoiceField(
                choices=[
                    model_key(resource)
                    for resource in enabled_resources(self.site)
                ],
                label=_("Model"),
                help_text=_("The records this field is added to."),
            )
        }

        for code in codes:
            suffix = f" ({names[code]})" if several else ""
            extra[f"label_{code}"] = serializers.CharField(
                max_length=200,
                required=code == default,
                allow_blank=code != default,
                label=f"{gettext('Label')}{suffix}",
            )
            extra[f"help_{code}"] = serializers.CharField(
                max_length=500,
                required=False,
                allow_blank=True,
                label=f"{gettext('Help text')}{suffix}",
            )

        model_fields = [
            name
            for name in self.get_fields()
            if name not in extra and name not in ("labels", "help_texts")
        ]
        names_in_form = [*model_fields, *extra]

        return build_form_serializer(
            CustomField,
            fields=[
                name for name in self.get_fields() if name in names_in_form
            ],
            fieldsets=self.get_fieldsets(),
            overrides=self.form_overrides,
            extra_fields=extra,
            source=self,
        )

    def get_initial(self, request: Any) -> dict[str, Any]:
        """The model the list was showing, or the only one there is."""
        wanted = request.GET.get("model", "")
        keys = [model_key(each) for each in customizable(self.site, request)]

        if wanted in keys:
            return {"model": wanted}

        return {"model": keys[0]} if len(keys) == 1 else {}

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        from django.contrib.contenttypes.models import ContentType

        extra = serializer.extra_values
        instance = serializer.instance
        labels = dict(getattr(instance, "labels", None) or {})
        help_texts = dict(getattr(instance, "help_texts", None) or {})

        for code, _name in languages():
            if f"label_{code}" in extra:
                labels[code] = extra[f"label_{code}"].strip()

            if f"help_{code}" in extra:
                help_texts[code] = extra[f"help_{code}"].strip()

        stamps: dict[str, Any] = {
            "labels": {code: text for code, text in labels.items() if text},
            "help_texts": {
                code: text for code, text in help_texts.items() if text
            },
        }

        if not change:
            target = serializer.target_resource
            stamps["content_type"] = ContentType.objects.get_for_model(
                target.model
            )

            if "position" not in serializer.validated_data:
                stamps["position"] = (
                    CustomField.objects.filter(
                        content_type=stamps["content_type"]
                    ).count()
                    + 1
                ) * 10

        saved = serializer.save(**stamps)
        forget(request)

        return saved

    # -- actions ----------------------------------------------------------

    @action(
        description=_("Archive"),
        icon="inventory_2",
        permissions=("change",),
        help=_(
            "Hide the fields everywhere; their values and history are kept."
        ),
    )
    def archive(self, request: Any, queryset: Any) -> str:
        return self.set_archived(request, queryset, True)

    @action(
        description=_("Restore"),
        icon="unarchive",
        permissions=("change",),
        help=_("Show the archived fields again, with their values."),
    )
    def restore(self, request: Any, queryset: Any) -> str:
        return self.set_archived(request, queryset, False)

    def set_archived(self, request: Any, queryset: Any, archived: bool) -> str:
        count = 0

        for definition in queryset:
            if definition.archived == archived:
                continue

            if not self.has_change_permission(request, definition):
                continue

            definition.archived = archived
            definition.save(update_fields=("archived", "updated_at"))
            count += 1

        forget(request)

        if archived:
            return ngettext(
                "%(count)s field archived.",
                "%(count)s fields archived.",
                count,
            ) % {"count": count}

        return ngettext(
            "%(count)s field restored.",
            "%(count)s fields restored.",
            count,
        ) % {"count": count}

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        if name == "archive":
            return not obj.archived

        if name == "restore":
            return obj.archived

        return True


def written_out(texts: Any) -> str:
    """``{"en": "Colour", "fr": "Couleur"}`` as a line per language."""
    names = dict(languages())

    return "\n".join(
        f"{names.get(code, code)}: {text}"
        for code, text in (texts or {}).items()
        if text
    )


def reader(name: str) -> Any:
    """How an extra question of the form reads a definition."""

    def read(instance: Any) -> Any:
        if not isinstance(instance, CustomField):
            return None

        if name == "model":
            resource = resource_of(instance)

            return model_key(resource) if resource is not None else ""

        kind, _, code = name.partition("_")
        texts = instance.labels if kind == "label" else instance.help_texts

        return (texts or {}).get(code, "")

    return read


def build_definition_serializer(super_class: Any) -> Any:
    """The generated form, made to read and check a definition."""

    class DefinitionSerializer(super_class):
        #: The resource of the model a new field is added to.
        target_resource: Any = None

        def get_fields(self) -> Any:
            fields = super().get_fields()
            request = self.context.get("request")
            instance = getattr(self, "instance", None)

            # The extra questions are read back too: they are the
            # definition's labels, by language, and its model.
            for name in super_class.generic_extra_fields:
                if name in fields:
                    fields[name].write_only = False
                    fields[name].get_attribute = reader(name)

            if "model" in fields:
                if isinstance(instance, CustomField):
                    # Fixed once created: its values are that model's.
                    fields["model"].read_only = True
                elif getattr(getattr(request, "user", None), "pk", None):
                    # A reader's own; the schema (no one signed in)
                    # keeps every model open to custom fields.
                    fields["model"].choices = [
                        (
                            model_key(resource),
                            force_str(
                                resource.get_label_plural()
                            ).capitalize(),
                        )
                        for resource in customizable(site, request)
                    ]

            if isinstance(instance, CustomField) and "key" in fields:
                fields["key"].read_only = True

            return fields

        def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
            attrs = super().validate(attrs)
            instance = (
                self.instance
                if isinstance(self.instance, CustomField)
                else None
            )
            request = self.context.get("request")
            errors: dict[str, Any] = {}

            def value(name: str, default: Any = "") -> Any:
                if name in attrs:
                    return attrs[name]

                return (
                    getattr(instance, name, default) if instance else default
                )

            # Whose field it is.
            if instance is None:
                wanted = attrs.get("model", "")
                target = next(
                    (
                        resource
                        for resource in customizable(site, request)
                        if model_key(resource) == wanted
                    ),
                    None,
                )

                if target is None:
                    raise serializers.ValidationError(
                        {"model": gettext("Choose a model you may customize.")}
                    )
            else:
                target = resource_of(instance)

            self.target_resource = target
            declared = declaration(target) if target is not None else None
            kind = value("type", "text")

            # The key, once.
            if instance is None:
                key = attrs.get("key", "")

                if not KEY_PATTERN.match(key or ""):
                    errors["key"] = gettext(
                        "Lowercase letters, digits and _, starting with a "
                        "letter; 40 at most."
                    )
                elif CustomField.objects.filter(
                    content_type__app_label=target.model._meta.app_label,
                    content_type__model=target.model._meta.model_name,
                    key=key,
                ).exists():
                    errors["key"] = gettext(
                        "This model has a field with this key already."
                    )
                elif self.clashes(target, f"{PREFIX}{key}"):
                    errors["key"] = gettext(
                        "The model has a field or a column of this name."
                    )

                count = CustomField.objects.filter(
                    content_type__app_label=target.model._meta.app_label,
                    content_type__model=target.model._meta.model_name,
                ).count()

                if count >= max_fields(target):
                    raise serializers.ValidationError(
                        gettext(
                            "This model has %(count)s custom fields: the "
                            "most it may have."
                        )
                        % {"count": count}
                    )

            # The type: one of those offered, kept once values exist.
            offered = declared.types if declared and declared.types else TYPES

            if kind not in offered:
                errors["type"] = gettext("This type is not offered here.")
            elif (
                instance is not None
                and kind != instance.type
                and instance.values.exists()
            ):
                errors["type"] = gettext(
                    "Records hold values of this field: its type can no "
                    "longer change. Add a field of the new type instead."
                )

            # The label, in the project's language at least.
            default = default_language()

            if not (attrs.get(f"label_{default}") or "").strip() and (
                instance is None
                or f"label_{default}" in attrs
                or not (instance.labels or {}).get(default)
            ):
                errors[f"label_{default}"] = gettext("A label is required.")

            # The limits, read as the type's values.
            self.check_limits(kind, value, errors)

            # The choices of a choice.
            choices_text = value("choices", "")

            if kind == "choice":
                try:
                    choices = parse_choices(choices_text)
                except Exception as error:
                    errors["choices"] = " ".join(
                        force_str(message)
                        for message in getattr(error, "messages", [error])
                    )
                    choices = None

                if choices is not None and not choices:
                    errors["choices"] = gettext("Give at least one choice.")
                elif choices is not None and instance is not None:
                    removed = {
                        choice["value"] for choice in instance.get_choices()
                    } - {choice["value"] for choice in choices}

                    if (
                        removed
                        and instance.values.filter(
                            value_text__in=removed
                        ).exists()
                    ):
                        errors["choices"] = gettext(
                            "Records hold a choice that is no longer "
                            "listed: %(values)s."
                        ) % {"values": ", ".join(sorted(removed))}

            # The default, as a value of the type.
            default_text = value("default", "")

            if default_text:
                try:
                    parsed = parse_value(kind, default_text)
                except ValueError:
                    errors["default"] = gettext("Not a value of this type.")
                else:
                    if kind == "choice" and parsed not in {
                        choice["value"]
                        for choice in parse_choices(choices_text or "")
                    }:
                        errors["default"] = gettext("Not one of the choices.")

            # Permissions that exist.
            for name in ("view_permission", "change_permission"):
                wanted = (value(name, "") or "").strip()

                if wanted and not self.permission_exists(wanted):
                    errors[name] = gettext(
                        "No such permission: write app.codename."
                    )

            if errors:
                raise serializers.ValidationError(errors)

            return attrs

        @staticmethod
        def clashes(target: Any, name: str) -> bool:
            names = {
                field.name for field in target.model._meta.get_fields()
            } | {field.attname for field in target.model._meta.concrete_fields}

            return name in names or name in {
                force_str(entry) for entry in target.get_list_display()
            }

        @staticmethod
        def permission_exists(wanted: str) -> bool:
            app_label, dot, codename = wanted.partition(".")

            return bool(
                dot
                and Permission.objects.filter(
                    content_type__app_label=app_label, codename=codename
                ).exists()
            )

        @staticmethod
        def check_limits(kind: str, value: Any, errors: dict) -> None:
            longest = (
                LONG_TEXT_MAX_LENGTH if kind == "textarea" else TEXT_MAX_LENGTH
            )
            shortest_length = value("min_length", None)
            longest_length = value("max_length", None)

            if kind in LENGTH_TYPES:
                if longest_length is not None and longest_length > longest:
                    errors["max_length"] = gettext("At most %(count)s.") % {
                        "count": longest
                    }
                elif (
                    shortest_length is not None
                    and longest_length is not None
                    and shortest_length > longest_length
                ):
                    errors["min_length"] = gettext("Longer than the longest.")

            if value("decimal_places", 2) > DECIMAL_PLACES:
                errors["decimal_places"] = gettext("At most %(count)s.") % {
                    "count": DECIMAL_PLACES
                }

            bounds: list[Any] = []

            for name in ("minimum", "maximum"):
                raw = (value(name, "") or "").strip()

                if not raw:
                    bounds.append(None)
                    continue

                if kind not in RANGE_TYPES:
                    errors[name] = gettext(
                        "Only numbers, dates and times have one."
                    )
                    bounds.append(None)
                    continue

                try:
                    bounds.append(parse_value(kind, raw))
                except ValueError:
                    errors[name] = gettext("Not a value of this type.")
                    bounds.append(None)

            if bounds[0] is not None and bounds[1] is not None:
                if bounds[0] > bounds[1]:
                    errors["minimum"] = gettext("Above the maximum.")

    DefinitionSerializer.__name__ = super_class.__name__

    return DefinitionSerializer


def customize_link(resource: Any, request: Any) -> Any:
    """*Customize fields*, for the list of a model open to them."""
    from generic.views.toolbar import ToolbarItem

    if not may_customize(resource, request):
        return None

    url = list_url_for(resource)

    if not url:
        return None

    return ToolbarItem(
        url=url,
        label=gettext("Customize fields"),
        icon="dynamic_form",
        # A button of the bar, never folded into the menu: only the
        # holders of the permission are given it at all.
        variant="default",
        placement="bar",
    )


def register_screens() -> None:
    """Put the definitions' page on the site, once a resource opened a
    model to custom fields."""
    from generic.conf import generic_settings

    if not getattr(generic_settings, "CUSTOM_FIELDS", True):
        return

    if not enabled_resources(site):
        return

    if not site.is_registered(CustomField):
        site.register(CustomField, CustomFieldResource)


__all__ = [
    "CustomFieldResource",
    "customize_link",
    "list_url_for",
    "register_screens",
]

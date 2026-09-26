"""Admin-style fieldsets, without depending on ``ModelAdmin``.

Django's admin has the nicest form layout in the ecosystem: named
fieldsets, rows that put several fields side by side, read-only fields
rendered as text, help text under the input. All of that lives in
``django.contrib.admin.helpers`` and is wired to a registered
``ModelAdmin``.

This is the same idea, reimplemented small and standalone, so a view can
declare::

    fieldsets = (
        (None, {"fields": ("title", ("author", "publisher"))}),
        (
            "Commercial",
            {
                "fields": ("price", "is_available"),
                "description": "Pricing and availability.",
                "classes": ("collapse",),
            },
        ),
    )

A tuple inside ``fields`` puts those fields on one row.
"""

from __future__ import annotations

from typing import Any, Iterator, Sequence

from django import forms
from django.db import models
from django.utils.encoding import force_str
from django.utils.formats import localize
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext_lazy as _

#: What a read-only field shows when it has no value.
EMPTY_VALUE_DISPLAY = "—"

#: Fieldset declaration: ``(name, options)`` pairs.
FieldsetsSpec = Sequence[tuple[str | None, dict[str, Any]]]


def render_readonly_value(value: Any) -> SafeString:
    """Format a value for display outside an input."""
    if value is None or value == "":
        return mark_safe(EMPTY_VALUE_DISPLAY)  # nosec B308 B703 - a constant

    if isinstance(value, bool):
        return format_html(
            '<span class="boolean boolean--{}">{}</span>',
            "yes" if value else "no",
            _("Yes") if value else _("No"),
        )

    if isinstance(value, models.Model):
        return format_html("{}", force_str(value))

    if isinstance(value, models.Manager):
        values = [force_str(item) for item in value.all()]
        return format_html(
            "{}", ", ".join(values) if values else EMPTY_VALUE_DISPLAY
        )

    if isinstance(value, (list, tuple)):
        return format_html(
            "{}",
            ", ".join(force_str(item) for item in value)
            or EMPTY_VALUE_DISPLAY,
        )

    return format_html("{}", localize(value))


class FieldsetField:
    """One field inside a fieldset row.

    Wraps either a bound form field or a read-only value, so the template
    can treat both the same way.
    """

    def __init__(
        self,
        form: forms.BaseForm,
        name: str,
        *,
        readonly: bool = False,
        source: Any = None,
    ) -> None:
        self.form = form
        self.name = name
        # Usually the view. A read-only field is often computed there
        # rather than stored on the model, exactly as ``ModelAdmin``
        # does it.
        self.source = source
        self.is_readonly = readonly or name not in form.fields
        self.bound_field = form[name] if name in form.fields else None

    @property
    def source_callable(self) -> Any:
        """A ``method(self, instance)`` on the source, if there is one."""
        if self.source is None:
            return None

        method = getattr(self.source, self.name, None)

        return method if callable(method) else None

    # -- display ------------------------------------------------------

    @property
    def label(self) -> str:
        if self.bound_field is not None:
            return self.bound_field.label or self.name

        return self.readonly_label()

    def readonly_label(self) -> str:
        """Label for a field that is not on the form at all."""
        method = self.source_callable
        described = getattr(method, "short_description", None)

        if described:
            return force_str(described)

        instance = getattr(self.form, "instance", None)

        if instance is not None:
            try:
                field = instance._meta.get_field(self.name)
            except Exception:
                field = None

            if field is not None:
                return force_str(
                    getattr(field, "verbose_name", self.name)
                ).capitalize()

        attribute = getattr(type(self.form), self.name, None)
        label = getattr(attribute, "short_description", None)

        if label:
            return force_str(label)

        return self.name.replace("_", " ").capitalize()

    @property
    def label_tag(self) -> SafeString:
        if self.bound_field is not None and not self.is_readonly:
            return self.bound_field.label_tag()

        return format_html(
            "<label>{}{}</label>",
            self.label,
            ":" if self.label else "",
        )

    @property
    def is_checkbox(self) -> bool:
        return (
            self.bound_field is not None
            and not self.is_readonly
            and isinstance(
                self.bound_field.field.widget,
                forms.CheckboxInput,
            )
        )

    @property
    def is_hidden(self) -> bool:
        return self.bound_field is not None and self.bound_field.is_hidden

    @property
    def is_required(self) -> bool:
        return self.bound_field is not None and self.bound_field.field.required

    @property
    def errors(self) -> forms.utils.ErrorList:
        if self.bound_field is None or self.is_readonly:
            return self.form.error_class()

        return self.bound_field.errors

    @property
    def help_text(self) -> str:
        if self.bound_field is None:
            return ""

        return force_str(self.bound_field.field.help_text or "")

    @property
    def contents(self) -> SafeString:
        """Rendered value of a read-only field."""
        instance = getattr(self.form, "instance", None)
        value: Any = None

        # Resolution order: the view, then the form, then the model.
        # The view comes first so a display value can be computed
        # without touching either of the other two.
        source_method = self.source_callable
        form_method = getattr(type(self.form), self.name, None)

        if source_method is not None:
            value = source_method(instance)
        elif callable(form_method):
            value = form_method(self.form)
        elif instance is not None and hasattr(instance, self.name):
            display = getattr(
                instance,
                f"get_{self.name}_display",
                None,
            )
            value = (
                display()
                if callable(display)
                else getattr(instance, self.name)
            )
        elif self.bound_field is not None:
            value = self.bound_field.value()

        return render_readonly_value(value)

    def __str__(self) -> str:
        if self.bound_field is not None and not self.is_readonly:
            return str(self.bound_field)

        return str(self.contents)


class FieldsetRow:
    """One row of a fieldset: a single field, or several side by side."""

    def __init__(
        self,
        form: forms.BaseForm,
        names: Sequence[str],
        readonly_fields: Sequence[str],
        source: Any = None,
    ) -> None:
        self.fields = [
            FieldsetField(
                form,
                name,
                readonly=name in readonly_fields,
                source=source,
            )
            for name in names
        ]

    @property
    def is_multiline(self) -> bool:
        return len(self.fields) > 1

    @property
    def has_visible_fields(self) -> bool:
        return any(not field.is_hidden for field in self.fields)

    @property
    def has_errors(self) -> bool:
        return any(field.errors for field in self.fields)

    @property
    def css_classes(self) -> str:
        classes = ["form-row"]

        if self.has_errors:
            classes.append("form-row--errors")

        if not self.has_visible_fields:
            classes.append("is-hidden")

        classes.extend(f"field-{field.name}" for field in self.fields)

        return " ".join(classes)

    def __iter__(self) -> Iterator[FieldsetField]:
        return iter(self.fields)


class Fieldset:
    """A named group of rows."""

    def __init__(
        self,
        form: forms.BaseForm,
        name: str | None,
        options: dict[str, Any],
        readonly_fields: Sequence[str] = (),
        source: Any = None,
    ) -> None:
        self.form = form
        self.title = name
        self.description = options.get("description", "")
        self.classes = " ".join(options.get("classes", ()))
        self.rows = [
            FieldsetRow(
                form,
                (entry,) if isinstance(entry, str) else tuple(entry),
                readonly_fields,
                source,
            )
            for entry in options.get("fields", ())
        ]

    @property
    def is_collapsible(self) -> bool:
        return "collapse" in self.classes

    def __iter__(self) -> Iterator[FieldsetRow]:
        return iter(self.rows)


class FieldsetForm:
    """A form plus its layout.

    Templates iterate this instead of the raw form, so the layout lives
    in one place rather than being repeated per template.
    """

    def __init__(
        self,
        form: forms.BaseForm,
        fieldsets: FieldsetsSpec,
        readonly_fields: Sequence[str] = (),
        source: Any = None,
    ) -> None:
        self.form = form
        self.readonly_fields = tuple(readonly_fields)
        self.source = source
        self.fieldsets = [
            Fieldset(
                form,
                name,
                options,
                self.readonly_fields,
                source,
            )
            for name, options in fieldsets
        ]

    @property
    def media(self) -> forms.Media:
        return self.form.media

    @property
    def non_field_errors(self) -> forms.utils.ErrorList:
        return self.form.non_field_errors()

    @property
    def hidden_fields(self) -> list[forms.BoundField]:
        return self.form.hidden_fields()

    def __iter__(self) -> Iterator[Fieldset]:
        return iter(self.fieldsets)


def build_default_fieldsets(
    form: forms.BaseForm,
    readonly_fields: Sequence[str] = (),
) -> FieldsetsSpec:
    """Everything in one unnamed fieldset, in declaration order."""
    names = [
        name
        for name, field in form.fields.items()
        if not isinstance(field.widget, forms.HiddenInput)
    ]
    names.extend(name for name in readonly_fields if name not in names)

    return ((None, {"fields": tuple(names)}),)

"""Fields people add to a model, and the values records hold in them.

Two tables, whatever the number of models opened to custom fields: a
definition per field, and a row per field and record holding its value
in a column of the right type. Nothing is added to the project's own
tables, so a model is opened with one option on its resource and no
migration; and a value is a real date, number or yes/no to the
database, so the tables filter and sort them like any column.
"""

from __future__ import annotations

import datetime
import decimal
import re
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.utils.encoding import force_str
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from generic.api.tags import clean_color

#: A key: what the field is called in tables, forms, the API and the
#: history, ``cf_<key>``. Lowercase, so a filter typed in the search box
#: (``cf_warranty:>2``) reads the same as the column.
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

#: The prefix of a custom field's public name.
PREFIX = "cf_"

#: The prefix of a custom field's value in a version of the record:
#: a colon, which no model field name can hold.
HISTORY_PREFIX = "cf:"

#: The colours of choices given none, in order.
PALETTE = (
    "#2563eb",
    "#16a34a",
    "#d97706",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#64748b",
)

#: Digits a decimal value is stored with, and places after the point.
DECIMAL_DIGITS = 24
DECIMAL_PLACES = 6

#: The longest short text, and the longest long one.
TEXT_MAX_LENGTH = 255
LONG_TEXT_MAX_LENGTH = 10000


class CustomField(models.Model):
    """One field added to one model."""

    class Type(models.TextChoices):
        TEXT = "text", _("Text")
        LONG_TEXT = "textarea", _("Long text")
        EMAIL = "email", _("E-mail address")
        URL = "url", _("Web address")
        INTEGER = "integer", _("Whole number")
        DECIMAL = "decimal", _("Decimal number")
        BOOLEAN = "boolean", _("Yes/no")
        DATE = "date", _("Date")
        TIME = "time", _("Time")
        DATETIME = "datetime", _("Date and time")
        CHOICE = "choice", _("Choice")

    content_type = models.ForeignKey(
        ContentType,
        verbose_name=_("model"),
        on_delete=models.CASCADE,
        related_name="+",
    )
    key = models.CharField(
        _("key"),
        max_length=40,
        help_text=_(
            "How tables, the API and the history name the field, after "
            "cf_. Lowercase letters, digits and _; it cannot be changed "
            "later."
        ),
    )
    type = models.CharField(
        _("type"), max_length=10, choices=Type.choices, default=Type.TEXT
    )
    #: ``{language code: label}``, one per language of ``LANGUAGES``.
    labels = models.JSONField(_("labels"), default=dict, blank=True)
    #: ``{language code: help text}``.
    help_texts = models.JSONField(_("help texts"), default=dict, blank=True)
    required = models.BooleanField(
        _("required"),
        default=False,
        help_text=_(
            "Asked each time a record is saved from its form. Records "
            "saved before stay as they are."
        ),
    )
    default = models.CharField(
        _("default value"),
        max_length=255,
        blank=True,
        default="",
        help_text=_("What the form of a new record starts with."),
    )
    unit = models.CharField(
        _("unit"),
        max_length=20,
        blank=True,
        default="",
        help_text=_("Shown after a number: kg, h, %."),
    )
    min_length = models.PositiveIntegerField(
        _("shortest"), null=True, blank=True
    )
    max_length = models.PositiveIntegerField(
        _("longest"), null=True, blank=True
    )
    minimum = models.CharField(
        _("minimum"),
        max_length=40,
        blank=True,
        default="",
        help_text=_(
            "The smallest number, or the earliest date or time "
            "(2026-01-31, 08:30)."
        ),
    )
    maximum = models.CharField(
        _("maximum"),
        max_length=40,
        blank=True,
        default="",
        help_text=_("The largest number, or the latest date or time."),
    )
    decimal_places = models.PositiveSmallIntegerField(
        _("decimal places"), default=2
    )
    choices = models.TextField(
        _("choices"),
        blank=True,
        default="",
        help_text=_(
            "One choice a line: its value, then its label, the label in "
            "other languages and a colour, separated by |. For example: "
            "blue | Blue | fr: Bleu | #2563eb"
        ),
    )
    position = models.PositiveIntegerField(_("position"), default=0)
    in_list = models.BooleanField(
        _("shown in the table"),
        default=True,
        help_text=_(
            "Shown in the table from the start. Otherwise it is offered "
            "by the column selector."
        ),
    )
    view_permission = models.CharField(
        _("permission to see it"),
        max_length=150,
        blank=True,
        default="",
        help_text=_(
            "app.codename: only who holds it sees the field. Empty: whoever "
            "may see the record."
        ),
    )
    change_permission = models.CharField(
        _("permission to change it"),
        max_length=150,
        blank=True,
        default="",
        help_text=_(
            "app.codename: only who holds it changes the field. Empty: "
            "whoever may change the record."
        ),
    )
    archived = models.BooleanField(
        _("archived"),
        default=False,
        help_text=_(
            "Hidden everywhere; its values and their history are kept, and "
            "come back when it is restored."
        ),
    )
    updated_at = models.DateTimeField(_("changed"), auto_now=True)

    class Meta:
        verbose_name = _("custom field")
        verbose_name_plural = _("custom fields")
        ordering = ("content_type", "position", "pk")
        constraints = (
            models.UniqueConstraint(
                fields=("content_type", "key"),
                name="generic_customfield_unique_key",
            ),
        )

    def __str__(self) -> str:
        return self.label()

    # -- naming ----------------------------------------------------------

    @property
    def name(self) -> str:
        """The public name: a column's, a form field's, an API key."""
        return f"{PREFIX}{self.key}"

    @property
    def history_name(self) -> str:
        """The name of its value in a version of the record."""
        return f"{HISTORY_PREFIX}{self.key}"

    def label(self, language: str | None = None) -> str:
        """The label in ``language`` - the active one by default - else
        in the project's, else the first one written, else the key."""
        return translated(self.labels, language) or self.key

    def help_text(self, language: str | None = None) -> str:
        return translated(self.help_texts, language)

    # -- storage ---------------------------------------------------------

    @property
    def column(self) -> str:
        """The column of :class:`CustomValue` holding its values."""
        return STORAGE[self.type]

    @property
    def is_number(self) -> bool:
        return self.type in (self.Type.INTEGER, self.Type.DECIMAL)

    @property
    def is_text(self) -> bool:
        return self.type in TEXT_TYPES

    # -- limits ----------------------------------------------------------

    def limit(self, raw: str) -> Any:
        """``minimum`` or ``maximum``, read as this type's value."""
        return parse_value(self.type, raw) if raw else None

    def get_choices(self) -> list[dict[str, Any]]:
        """``[{"value", "labels", "color"}]``, from the ``choices``
        text."""
        return parse_choices(self.choices)

    def choice_labels(self, language: str | None = None) -> dict[str, str]:
        return {
            choice["value"]: translated(choice["labels"], language)
            or choice["value"]
            for choice in self.get_choices()
        }

    def choice_colors(self) -> dict[str, str]:
        return {
            choice["value"]: choice["color"] or PALETTE[index % len(PALETTE)]
            for index, choice in enumerate(self.get_choices())
        }

    def signature(self) -> tuple[Any, ...]:
        """What a serializer built from this definition depends on."""
        return (
            self.pk,
            self.updated_at.isoformat() if self.updated_at else "",
        )


class CustomValue(models.Model):
    """What one record holds in one custom field.

    No row is an empty value. ``object_id`` is text, like a history
    entry's, so a model keyed on a code keeps custom fields too.
    """

    field = models.ForeignKey(
        CustomField,
        verbose_name=_("field"),
        on_delete=models.CASCADE,
        related_name="values",
    )
    object_id = models.CharField(_("record"), max_length=128)
    value_text = models.TextField(_("text"), null=True, blank=True)
    value_integer = models.BigIntegerField(_("whole number"), null=True)
    value_decimal = models.DecimalField(
        _("decimal number"),
        max_digits=DECIMAL_DIGITS,
        decimal_places=DECIMAL_PLACES,
        null=True,
    )
    value_bool = models.BooleanField(_("yes/no"), null=True)
    value_date = models.DateField(_("date"), null=True)
    value_time = models.TimeField(_("time"), null=True)
    value_datetime = models.DateTimeField(_("date and time"), null=True)

    class Meta:
        verbose_name = _("custom value")
        verbose_name_plural = _("custom values")
        constraints = (
            models.UniqueConstraint(
                fields=("field", "object_id"),
                name="generic_customvalue_unique_record",
            ),
        )
        indexes = (
            models.Index(
                fields=("field", "value_integer"),
                name="generic_cv_integer",
            ),
            models.Index(
                fields=("field", "value_decimal"),
                name="generic_cv_decimal",
            ),
            models.Index(
                fields=("field", "value_date"), name="generic_cv_date"
            ),
            models.Index(
                fields=("field", "value_datetime"),
                name="generic_cv_datetime",
            ),
        )

    def __str__(self) -> str:
        return f"{self.field_id}:{self.object_id}"


TEXT_TYPES = frozenset(
    {
        CustomField.Type.TEXT,
        CustomField.Type.LONG_TEXT,
        CustomField.Type.EMAIL,
        CustomField.Type.URL,
        CustomField.Type.CHOICE,
    }
)

#: Type -> the column of CustomValue holding it.
STORAGE: dict[str, str] = {
    CustomField.Type.TEXT: "value_text",
    CustomField.Type.LONG_TEXT: "value_text",
    CustomField.Type.EMAIL: "value_text",
    CustomField.Type.URL: "value_text",
    CustomField.Type.CHOICE: "value_text",
    CustomField.Type.INTEGER: "value_integer",
    CustomField.Type.DECIMAL: "value_decimal",
    CustomField.Type.BOOLEAN: "value_bool",
    CustomField.Type.DATE: "value_date",
    CustomField.Type.TIME: "value_time",
    CustomField.Type.DATETIME: "value_datetime",
}


def translated(texts: Any, language: str | None = None) -> str:
    """The text of ``texts`` (``{code: text}``) for ``language``.

    ``fr-ca`` falls back on ``fr``; then the project's language, then
    whichever one was written first: a label in another language says
    more than no label.
    """
    if not isinstance(texts, dict) or not texts:
        return ""

    language = language or get_language() or settings.LANGUAGE_CODE
    candidates = [
        language,
        language.split("-")[0],
        settings.LANGUAGE_CODE,
        settings.LANGUAGE_CODE.split("-")[0],
    ]

    for code in candidates:
        text = texts.get(code)

        if text:
            return force_str(text)

    for text in texts.values():
        if text:
            return force_str(text)

    return ""


def parse_value(kind: str, raw: Any) -> Any:
    """``raw`` text - a limit, a default - as a value of type ``kind``.

    Raises ``ValueError`` when it is not one.
    """
    text = force_str(raw).strip()
    value: Any

    if kind == CustomField.Type.INTEGER:
        return int(text)

    if kind == CustomField.Type.DECIMAL:
        try:
            value = decimal.Decimal(text)
        except decimal.InvalidOperation:
            raise ValueError(text) from None

        if not value.is_finite():
            raise ValueError(text)

        return value

    if kind == CustomField.Type.DATE:
        value = parse_date(text)
    elif kind == CustomField.Type.TIME:
        value = parse_time(text)
    elif kind == CustomField.Type.DATETIME:
        value = parse_datetime(text)

        if value is None:
            day = parse_date(text)
            value = (
                datetime.datetime.combine(day, datetime.time())
                if day is not None
                else None
            )
    elif kind == CustomField.Type.BOOLEAN:
        lowered = text.lower()

        if lowered in ("1", "true", "yes", "y", "on"):
            return True

        if lowered in ("0", "false", "no", "n", "off"):
            return False

        raise ValueError(text)
    else:
        return text

    if value is None:
        raise ValueError(text)

    return value


def is_color(part: str) -> bool:
    """Whether a segment of a choice is its colour.

    Only a hex code or a colour function: "Blue" is a CSS colour too,
    and far more often the label of a choice.
    """
    lowered = part.lower()

    return bool(
        (lowered.startswith("#") or re.match(r"^[a-z]+\(", lowered))
        and clean_color(part)
    )


def parse_choices(text: str) -> list[dict[str, Any]]:
    """The choices written in a definition's ``choices``.

    A line per choice: ``value | label | fr: libelle | #2563eb``. A line
    of one word is its own value and label. Raises ``ValidationError``
    naming the line that cannot be read.
    """
    from generic.i18n import offered_languages

    languages = {code for code, _label in offered_languages()} or {
        code for code, _label in settings.LANGUAGES
    }
    default = settings.LANGUAGE_CODE.split("-")[0]
    choices: list[dict[str, Any]] = []
    seen: set[str] = set()

    for number, line in enumerate((text or "").splitlines(), start=1):
        parts = [part.strip() for part in line.split("|")]
        parts = [part for part in parts if part]

        if not parts:
            continue

        value = parts[0]
        labels: dict[str, str] = {}
        color = ""

        for part in parts[1:]:
            code, colon, rest = part.partition(":")
            code = code.strip()

            if colon and code in languages and rest.strip():
                labels[code] = rest.strip()
            elif not color and is_color(part):
                color = clean_color(part) or ""
            elif default not in labels:
                labels[default] = part
            else:
                raise ValidationError(
                    _("Line %(number)s: “%(part)s” is not understood.")
                    % {"number": number, "part": part}
                )

        if value in seen:
            raise ValidationError(
                _("Line %(number)s: “%(value)s” is there twice.")
                % {"number": number, "value": value}
            )

        if len(value) > TEXT_MAX_LENGTH:
            raise ValidationError(
                _("Line %(number)s: the value is too long.")
                % {"number": number}
            )

        seen.add(value)
        labels.setdefault(default, value)
        choices.append({"value": value, "labels": labels, "color": color})

    return choices


__all__ = [
    "HISTORY_PREFIX",
    "KEY_PATTERN",
    "PREFIX",
    "STORAGE",
    "CustomField",
    "CustomValue",
    "parse_choices",
    "parse_value",
    "translated",
]

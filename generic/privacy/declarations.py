"""What a model holds about people, said once: ``PersonalData``.

A declaration names the fields that are personal data and what each
becomes when the record is anonymized, how to tell whose record it is
(a path to the user it is about, fields holding an e-mail address),
and how long it may be kept (``Retention``). Everything else in
``generic.privacy`` reads it: the inventory, the export of one
person's data, the anonymization and the retention.

Checked when the resource is registered: a field that does not exist,
a way of anonymizing it that it cannot take, a path that leads nowhere
raise ``ImproperlyConfigured`` there, not in the middle of the night
the retention first runs.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, Mapping, NoReturn, Sequence, Union

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models

#: What a field becomes, by name:
#:
#: * ``blank`` - empty: ``""`` for text (a file is deleted from the
#:   storage first), ``None`` for anything nullable;
#: * ``null`` - ``None``;
#: * ``pseudonym`` - ``anonymous-<pk>``: still unique, still says
#:   which record it was, says nothing of the person;
#: * ``email`` - ``anonymous-<pk>@anonymized.invalid``: still a valid
#:   and unique address, which reaches nobody (``.invalid``, RFC 2606).
#:
#: A callable ``(obj, field_name) -> value`` does anything else; it
#: should give the same value when run twice, as a retention runs
#: every night over rows it has already anonymized.
STRATEGIES = ("blank", "null", "pseudonym", "email")

#: What a retention does to a row past its period.
ACTIONS = ("anonymize", "delete")

#: The start of a pseudonym, and of the address an e-mail becomes.
ANONYMOUS = "anonymous"
ANONYMOUS_DOMAIN = "anonymized.invalid"

Strategy = Union[str, Callable[[Any, str], Any]]


@dataclasses.dataclass(frozen=True)
class Retention:
    """How long a model's rows are kept, and what happens after.

    ``days`` after the date in ``after`` - a ``DateField`` or
    ``DateTimeField`` of the model, or a path to one - a row is
    anonymized (``action="anonymize"``, the default) or deleted
    (``"delete"``). ``filter`` narrows the rows concerned, as keyword
    lookups: ``{"is_active": False}`` keeps the active ones whatever
    their age. A row whose date is empty is kept.
    """

    days: int
    after: str
    action: str = "anonymize"
    filter: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class PersonalData:
    """The personal data a model holds, and the person it is about."""

    #: Field name -> what it becomes when the record is anonymized: a
    #: name from ``STRATEGIES`` or a callable.
    fields: Mapping[str, Strategy] = dataclasses.field(default_factory=dict)
    #: The path from the model to the user a row is about - ``"user"``,
    #: ``"customer__account"`` - or None. ``--user`` finds rows by it.
    subject: str | None = None
    #: Fields holding the person's e-mail address: ``--email`` (and a
    #: user's own address) finds rows by them, ignoring case.
    email: Sequence[str] = ()
    #: More fields an export of the person's data carries, besides
    #: ``fields`` - what they gave that is not secret enough to blank.
    export: Sequence[str] = ()
    #: How long the rows are kept (``Retention``), or None: as long as
    #: the project keeps them.
    retention: Retention | None = None
    #: A ``DateTimeField`` set to the moment a row is anonymized: the
    #: retention then skips rows it has already done, the screens can
    #: show it. Optional.
    marker: str | None = None
    #: Whether the list offers the bulk action *Anonymize* to whoever
    #: may delete.
    action: bool = True

    def check(self, model: Any, owner: str) -> None:
        """Raise ``ImproperlyConfigured`` naming ``owner`` (the class and
        attribute it is declared on) when something does not fit
        ``model``."""
        label = model._meta.label

        def refuse(message: str) -> NoReturn:
            raise ImproperlyConfigured(f"{owner} on {label}: {message}")

        if isinstance(self.email, str) or isinstance(self.export, str):
            refuse("'email' and 'export' are tuples of field names.")

        for name, strategy in self.fields.items():
            field = _field(model, name, refuse)
            _check_strategy(field, name, strategy, refuse)

        for name in (*self.email, *self.export):
            _field(model, name, refuse)

        if self.subject is not None:
            _check_subject(model, self.subject, refuse)

        if self.marker is not None:
            field = _field(model, self.marker, refuse)

            if not isinstance(field, models.DateTimeField) or not field.null:
                refuse(
                    f"the marker '{self.marker}' must be a nullable "
                    f"DateTimeField."
                )

        if self.retention is not None:
            _check_retention(model, self.retention, refuse)


def _field(model: Any, name: str, refuse: Callable[[str], NoReturn]) -> Any:
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        refuse(f"no field '{name}'.")

    if not getattr(field, "concrete", False) or field.many_to_many:
        refuse(f"'{name}' is not a column of the model.")

    return field


def is_text(field: Any) -> bool:
    """Whether ``""`` is a value the field stores (files included)."""
    return isinstance(
        field, (models.CharField, models.TextField, models.FileField)
    )


def _check_strategy(
    field: Any,
    name: str,
    strategy: Any,
    refuse: Callable[[str], NoReturn],
) -> None:
    if callable(strategy):
        return

    if strategy not in STRATEGIES:
        refuse(
            f"'{name}': unknown way to anonymize '{strategy}' - one of "
            f"{', '.join(STRATEGIES)}, or a callable."
        )

    if strategy == "blank" and not (is_text(field) or field.null):
        refuse(
            f"'{name}' can be neither empty nor null: give it a " f"callable."
        )

    if strategy == "null" and not field.null:
        refuse(f"'{name}' is not nullable.")

    if strategy in ("pseudonym", "email") and not isinstance(
        field, (models.CharField, models.TextField)
    ):
        refuse(f"'{name}' is not text: '{strategy}' needs text.")


def _check_subject(
    model: Any,
    path: str,
    refuse: Callable[[str], NoReturn],
) -> None:
    from django.contrib.auth import get_user_model

    target = model

    for part in path.split("__"):
        try:
            field = target._meta.get_field(part)
        except FieldDoesNotExist:
            refuse(f"the subject '{path}' leads nowhere ('{part}').")

        if not field.is_relation or field.related_model is None:
            refuse(f"the subject '{path}' crosses '{part}', not a relation.")

        target = field.related_model

    if target is not get_user_model():
        refuse(
            f"the subject '{path}' must lead to the user model, not "
            f"{target._meta.label}."
        )


def _check_retention(
    model: Any,
    retention: Retention,
    refuse: Callable[[str], NoReturn],
) -> None:
    if not isinstance(retention.days, int) or retention.days < 1:
        refuse("a retention's 'days' is a whole number of days, 1 or more.")

    if retention.action not in ACTIONS:
        refuse(
            f"a retention's action is one of {', '.join(ACTIONS)}, not "
            f"'{retention.action}'."
        )

    target = model
    field: Any = None

    for part in retention.after.split("__"):
        try:
            field = target._meta.get_field(part)
        except FieldDoesNotExist:
            refuse(f"the retention's date '{retention.after}' leads nowhere.")

        if field.is_relation:
            target = field.related_model

    if not isinstance(field, models.DateField):
        refuse(
            f"the retention's date '{retention.after}' must be a "
            f"DateField or a DateTimeField."
        )

    try:
        model._default_manager.none().filter(**dict(retention.filter))
    except Exception as error:  # FieldError, ValueError, TypeError...
        refuse(f"the retention's filter does not apply: {error}")


__all__ = [
    "ACTIONS",
    "ANONYMOUS",
    "ANONYMOUS_DOMAIN",
    "PersonalData",
    "Retention",
    "STRATEGIES",
    "is_text",
]

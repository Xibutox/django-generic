"""What a request sends, checked before anything reads it.

A write to the API is a JSON object - or a form, which reads like one.
A body that parses and is something else (``[1, 2]``, ``"text"``,
``3``) is a mistake of the caller's, and it gets a 400 saying so
rather than the 500 of an ``AttributeError`` further down. The same
goes for a primary key that cannot be one: ``abc`` where a number is
expected names no record, it does not break the query.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext
from rest_framework.exceptions import ValidationError

#: The methods whose body the endpoints read.
WRITES = ("POST", "PUT", "PATCH")

#: What a value that is no primary key raises, converted or looked up.
KEY_ERRORS = (TypeError, ValueError, OverflowError, DjangoValidationError)


def require_object(request: Any) -> None:
    """Refuse (400) a body that is neither an object nor a form."""
    if request.method not in WRITES:
        return

    # Parsed here when it was not yet: a body that does not parse is
    # DRF's 400 as it always was.
    if not hasattr(request.data, "get"):
        raise ValidationError(
            {"detail": gettext("Send a JSON object.")},
        )


class ObjectBodyMixin:
    """Before an ``APIView``: its writes take an object, or nothing."""

    def initial(self, request: Any, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)  # type: ignore[misc]
        require_object(request)


def clean_keys(model: Any, values: Iterable[Any]) -> list[Any]:
    """``values`` that can be primary keys of ``model``, converted.

    The others name no record and are left out, so a lookup on the
    result finds what exists instead of raising on what cannot.
    """
    field = model._meta.pk
    keys = []

    for value in values:
        if isinstance(value, (list, tuple, dict, set, bool)):
            continue

        # 1.5 would be read as 1: another record than the one named.
        if isinstance(value, float) and not value.is_integer():
            continue

        try:
            key = field.to_python(value)
            # Its range too: a number no column holds matches nothing,
            # and some databases refuse to be asked.
            field.run_validators(key)
        except KEY_ERRORS:
            continue

        if key is not None:
            keys.append(key)

    return keys


__all__ = [
    "KEY_ERRORS",
    "ObjectBodyMixin",
    "clean_keys",
    "require_object",
]

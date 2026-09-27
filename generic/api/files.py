"""Files in forms, tables and summaries.

A stored file travels as an object, never as a storage URL::

    {"name": "invoice.pdf", "url": "/api/shop/order/7/files/invoice/",
     "size": 48213}

``url`` is where a reader downloads it - an endpoint that checks who
asks, which the layer serving the serializer knows and this one does
not: it hands over a function in the serializer context, under
:data:`FILE_URL`, taking the stored file and giving that address (or
``None``). Nothing here assumes a public ``MEDIA_URL``.

A form sends a new file as a multipart part (see
:mod:`generic.api.parsers`); ``null`` removes the current one where the
model field allows it to be blank.
"""

from __future__ import annotations

import posixpath
from typing import Any

from django.core.validators import FileExtensionValidator
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext
from rest_framework import serializers

from generic.conf import generic_settings

#: Serializer context key: ``callable(field_file) -> url | None``.
FILE_URL = "file_url"

__all__ = [
    "FILE_URL",
    "FileValueMixin",
    "FormFileField",
    "FormImageField",
    "accept_of",
    "describe_file",
    "file_name",
    "file_size",
]


def file_name(value: Any) -> str:
    """The name a stored file is shown by: its last part, not its path."""
    name = getattr(value, "name", None) or ""

    return posixpath.basename(str(name).replace("\\", "/"))


def file_size(value: Any) -> int | None:
    """Its size in bytes, or ``None`` when the storage cannot say.

    A file named in the database may be missing from the storage - a
    restored backup, a volume not mounted - and a page showing the
    record must not fail on it.
    """
    try:
        return int(value.size)
    except Exception:  # noqa: BLE001 - any storage, any failure
        return None


def describe_file(
    value: Any,
    url: str | None,
    *,
    with_size: bool = True,
) -> dict[str, Any] | None:
    """``{"name", "url", "size"}``, or ``None`` for an empty field."""
    if not value:
        return None

    return {
        "name": file_name(value),
        "url": url or None,
        "size": file_size(value) if with_size else None,
    }


def accept_of(field: Any) -> str | None:
    """What a file chooser should offer, as its ``accept`` attribute.

    The extensions of a ``FileExtensionValidator`` on the field when it
    has one (``".pdf,.png"``), any image for an image field without one,
    and anything otherwise.
    """
    for validator in getattr(field, "validators", ()) or ():
        if isinstance(validator, FileExtensionValidator):
            extensions = validator.allowed_extensions

            if extensions:
                return ",".join(
                    f".{str(extension).lower().lstrip('.')}"
                    for extension in extensions
                )

    if isinstance(field, serializers.ImageField):
        return "image/*"

    return None


def too_large_message(limit: int) -> str:
    return gettext("The file is too large: at most %(limit)s.") % {
        "limit": filesizeformat(limit)
    }


class FileValueMixin:
    """A stored file, read as ``{"name", "url", "size"}``."""

    #: Whether reading a value asks the storage for its size: once per
    #: record on a form, but a table would ask once per row - a request
    #: each on a remote storage.
    describe_size = True

    def get_download_url(self, value: Any) -> str | None:
        resolver = self.context.get(FILE_URL)  # type: ignore[attr-defined]

        if resolver is None:
            return None

        return resolver(value)

    def to_representation(self, value: Any) -> dict[str, Any] | None:
        if not value:
            return None

        return describe_file(
            value,
            self.get_download_url(value),
            with_size=self.describe_size,
        )


class FormFileField(FileValueMixin, serializers.FileField):
    """A model's file field, as the generated forms read and write it.

    Written as an uploaded file, a multipart part. ``null`` - or ``""``,
    which is what an HTML form sends - removes the current file where
    the field may be left empty (``allow_null``, which a model field's
    ``blank=True`` sets), and stores ``""``: the column holds a name,
    and an empty one is Django's own "no file".

    The file removed, or replaced, stays in the storage: the record's
    history keeps versions naming it.
    """

    def validate_empty_values(self, data: Any) -> tuple[bool, Any]:
        if not self.read_only and (data is None or data == ""):
            if self.allow_null:
                return (True, "")

            if data is None:
                self.fail("null")

            self.fail("required")

        return super().validate_empty_values(data)

    def to_internal_value(self, data: Any) -> Any:
        data = super().to_internal_value(data)
        limit = generic_settings.FILE_MAX_SIZE

        if limit and data.size > limit:
            raise serializers.ValidationError(too_large_message(limit))

        return data


class FormImageField(FormFileField, serializers.ImageField):
    """An image field: a file, which Pillow must also read as an image."""

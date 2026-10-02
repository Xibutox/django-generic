"""A record's files: where each is downloaded, and how it is served.

Nothing is served from ``MEDIA_URL``. A file is a field of a record, so
it is read the way the record is - through the resource's endpoint::

    GET api/<app>/<model>/<pk>/files/<field>/

found through the resource's queryset (its row restrictions apply),
behind its view permission, and only for a file field the resource
shows that reader - in its form, on the summary page or in the list.

What comes back must never run in the site's origin: a file somebody
uploaded is anything they wanted it to be. So every answer carries
``X-Content-Type-Options: nosniff`` and ``Content-Security-Policy:
sandbox``, and only a raster image - PNG, JPEG, GIF, WebP - is shown in
the browser; everything else, HTML and SVG first, is a download.
"""

from __future__ import annotations

import mimetypes
import posixpath
from functools import partial
from typing import Any, Callable

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.http import FileResponse

from generic.api.files import file_name
from generic.sites.serializers import flatten_fieldsets

#: The only files shown in the page rather than downloaded, by
#: extension: images a browser draws and never runs.
RASTER_IMAGES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: Headers every answer of the download endpoint carries.
PROTECTIVE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",
}


def file_url(site: Any, value: Any) -> str | None:
    """Where ``value`` - a stored file of a record - is downloaded.

    Worked out from the record the file belongs to, which may be
    another model's than the table showing it (``ticket__attachment``).
    ``None`` when that model has no resource on ``site``.
    """
    instance = getattr(value, "instance", None)
    field = getattr(value, "field", None)

    if instance is None or field is None or instance.pk is None:
        return None

    resource = site.get_resource(type(instance)) or site.get_resource(
        instance._meta.concrete_model
    )

    if resource is None:
        return None

    return resource.get_file_url(instance.pk, field.name) or None


def file_url_resolver(site: Any) -> Callable[[Any], str | None]:
    """What a serializer context carries under ``generic.api.files``'s
    ``FILE_URL``."""
    return partial(file_url, site)


def is_file_field(model: Any, name: Any) -> bool:
    if not isinstance(name, str):
        return False

    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return False

    return isinstance(field, models.FileField)


def exposed_file_fields(resource: Any, request: Any = None) -> frozenset:
    """The file fields ``resource`` shows this reader.

    In its form, on the summary page - sections and figures - or as a
    column of its list: a file the screens never show is not served
    either, even to someone who may read the record.
    """
    names: list[Any] = [
        *resource.get_list_display(),
        *resource.get_detail_stats(request),
        *flatten_fieldsets(resource.get_detail_fieldsets(request)),
    ]

    serializer = resource.get_form_serializer_class()(
        context={"request": request}
    )

    names += [
        field.source if isinstance(field.source, str) else name
        for name, field in serializer.fields.items()
        if not field.write_only
    ]

    return frozenset(
        name for name in names if is_file_field(resource.model, name)
    )


def file_response(value: Any, filename: str = "") -> FileResponse:
    """``value``, a stored file, as a download - or an image, shown.

    Opened through the field's own storage, whatever it is. The type is
    read from the stored name; a raster image is shown inline, anything
    else - a page, an SVG, a script - is an attachment, never displayed.
    ``filename`` is the name the browser saves it under, when it is not
    the stored one.
    """
    stored = file_name(value)
    name = filename or stored
    shown = RASTER_IMAGES.get(posixpath.splitext(stored)[1].lower())
    content_type = shown or (
        mimetypes.guess_type(stored)[0] or "application/octet-stream"
    )
    response = FileResponse(
        value.open("rb"),
        as_attachment=shown is None,
        filename=name,
        content_type=content_type,
    )

    return protect(response)


def protect(response: Any) -> Any:
    """Add the headers that keep a served file from running anything."""
    for header, value in PROTECTIVE_HEADERS.items():
        response[header] = value

    return response


def is_stored(value: Any) -> bool:
    """Whether the storage still holds the file the record names."""
    if not value:
        return False

    try:
        return bool(value.storage.exists(value.name))
    except Exception:  # noqa: BLE001 - any storage, any failure
        return False

"""Renderers for the data table endpoints."""

from __future__ import annotations

from typing import Any

from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy as _
from rest_framework.renderers import JSONRenderer
from rest_framework.utils import encoders


def flatten_error_detail(detail: Any) -> str:
    """Collapse a DRF error payload into one readable sentence."""
    if isinstance(detail, dict):
        parts = []

        for key, value in detail.items():
            message = flatten_error_detail(value)

            if key in {"detail", "non_field_errors"}:
                parts.append(message)
            else:
                parts.append(f"{key}: {message}")

        return " ".join(part for part in parts if part)

    if isinstance(detail, (list, tuple)):
        return " ".join(flatten_error_detail(item) for item in detail if item)

    return str(detail)


class SafeJSONEncoder(encoders.JSONEncoder):
    """DRF's encoder, with text as the last resort.

    A table draws whatever a project's models hold, field types from
    libraries the framework never heard of included - a time zone, an
    enum of somebody's own. Refusing to encode one of those turns a
    whole page into a 500 over a single cell, and its text is what the
    cell would have shown anyway.

    Everything DRF knows how to encode - dates, decimals, UUIDs,
    durations, files - still goes through its own rules.
    """

    def default(self, obj: Any) -> Any:
        try:
            return super().default(obj)
        except TypeError:
            return force_str(obj)


class GenericJSONRenderer(JSONRenderer):
    """The JSON renderer every generated endpoint uses."""

    encoder_class = SafeJSONEncoder


class DataTablesRenderer(GenericJSONRenderer):
    """JSON renderer selected by ``?format=datatables``.

    Registering the format is what lets the client keep sending
    ``format=datatables`` without content negotiation rejecting it.

    On an error response the payload is rewritten to ``{"error": ...}``,
    the only error shape DataTables surfaces to the user. Without this a
    rejected filter shows up as a silent empty table.
    """

    media_type = "application/json"
    format = "datatables"

    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: dict[str, Any] | None = None,
    ) -> bytes:
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")

        if response is not None and response.status_code >= 400:
            data = self.build_error_payload(data, renderer_context)

        return super().render(data, accepted_media_type, renderer_context)

    def build_error_payload(
        self,
        data: Any,
        renderer_context: dict[str, Any],
    ) -> dict[str, Any]:
        message = flatten_error_detail(data).strip()

        if not message:
            message = str(_("The request could not be processed."))

        request = renderer_context.get("request")
        draw = 0

        if request is not None:
            try:
                draw = int(request.query_params.get("draw", 0))
            except (TypeError, ValueError):
                draw = 0

        return {
            "draw": draw,
            "recordsTotal": 0,
            "recordsFiltered": 0,
            "data": [],
            "error": message,
        }

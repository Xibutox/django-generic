"""Template helpers used by the generic templates."""

from __future__ import annotations

from typing import Any

from django import template
from django.http import QueryDict
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def query_replace(context: dict, **replacements: Any) -> str:
    """Current query string with some parameters replaced.

    Keeps search and pagination intact while one control changes::

        <a href="?{% query_replace page=2 %}">

    Passing ``None`` removes a parameter, which is how "clear this
    filter" links are built.
    """
    request = context.get("request")
    parameters: QueryDict = (
        request.GET.copy() if request is not None else QueryDict(mutable=True)
    )

    for key, value in replacements.items():
        if value is None:
            parameters.pop(key, None)
        else:
            parameters[key] = value

    return parameters.urlencode()


@register.simple_tag(takes_context=True)
def ordering_url(
    context: dict,
    column_name: str,
    order_param: str = "o",
) -> str:
    """Query string that sorts by ``column_name``.

    Cycles ascending, descending, then back to the default ordering, so
    a column header is a single control rather than three.
    """
    state = context.get("ordering_state") or {}
    current = state.get(column_name)

    if current == "asc":
        value: Any = f"-{column_name}"
    elif current == "desc":
        value = None
    else:
        value = column_name

    # Changing the sort must return to the first page, otherwise the
    # user lands on page 7 of a differently ordered list.
    return query_replace(context, **{order_param: value, "page": None})


@register.simple_tag(takes_context=True)
def ordering_indicator(context: dict, column_name: str) -> SafeString:
    """Arrow showing how a column is currently sorted."""
    state = context.get("ordering_state") or {}
    direction = state.get(column_name)

    if direction is None:
        # A fixed string, so no interpolation is needed - and
        # format_html refuses to be called without arguments.
        indicator = '<span class="sort-indicator" aria-hidden="true"></span>'

        return mark_safe(indicator)  # nosec B308 B703 - a constant

    return format_html(
        '<span class="sort-indicator sort-indicator--{}" '
        'aria-hidden="true">{}</span>',
        direction,
        "\u2191" if direction == "asc" else "\u2193",
    )


@register.filter
def field_value(row: Any, name: str) -> Any:
    """Read a key or attribute, whichever the object has."""
    if hasattr(row, "get"):
        return row.get(name)

    return getattr(row, name, None)


@register.simple_tag
def message_icon(tags: str) -> str:
    """Icon name matching a Django message level."""
    for level in ("error", "warning", "success"):
        if level in (tags or ""):
            return level

    return "info"

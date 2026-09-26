"""Template helpers for the application frame.

``{% generic_chrome as chrome %}`` is what ``generic/base.html`` builds
its sidebar, top bar and account menu from. It is a tag rather than a
context processor so a project gets the whole frame by extending the
template, without adding anything to its settings.
"""

from __future__ import annotations

import re
from typing import Any

from django import template
from django.urls import NoReverseMatch, reverse
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import SafeString, mark_safe

register = template.Library()

#: Short names the framework used before it had an icon font, and the
#: Material Symbols glyph each now stands for. Anything else is passed
#: through, so any Material Symbols name works directly.
ICON_ALIASES = {
    "view": "visibility",
    "theme": "contrast",
    "calendar": "calendar_month",
    "success": "check_circle",
    "error": "error",
    "warning": "warning",
    "info": "info",
}


@register.filter
def icon_name(name: Any) -> str:
    """Resolve a legacy short name to its Material Symbols glyph."""
    text = str(name or "")

    return ICON_ALIASES.get(text, text)


@register.simple_tag
def icon(name: Any, css_class: str = "", label: str = "") -> SafeString:
    """An icon from the Material Symbols font.

    Decorative by default. Pass ``label`` when the icon is the only
    thing inside a control, so screen readers still announce it.
    """
    if label:
        return format_html(
            '<span class="icon material-symbols-outlined {}" '
            'aria-hidden="true">{}</span><span class="sr-only">{}</span>',
            css_class,
            icon_name(name),
            label,
        )

    return format_html(
        '<span class="icon material-symbols-outlined {}" '
        'aria-hidden="true">{}</span>',
        css_class,
        icon_name(name),
    )


#: ``code`` in a line of a changelog, a help text: what Markdown means.
_INLINE_CODE = re.compile(r"`([^`\n]+)`")


@register.filter
def inline_code(text: Any) -> SafeString:
    """Text with its `backquoted` parts as code, the rest escaped.

    Everything is escaped first; only the backquotes, which escaping
    leaves alone, become ``<code>``: nothing in the text can inject
    markup of its own.
    """
    escaped = str(conditional_escape(text))
    marked = _INLINE_CODE.sub(r"<code>\1</code>", escaped)

    return mark_safe(marked)  # nosec B308 B703 - escaped just above


@register.simple_tag
def toolbar_layout(items: Any) -> Any:
    """``{% toolbar_layout toolbar_items as toolbar %}``: the buttons
    split around the *More* menu they fold into when room runs out."""
    from generic.views.toolbar import layout_toolbar

    return layout_toolbar(items or ())


@register.simple_tag(takes_context=True)
def generic_chrome(context: Any) -> dict[str, Any]:
    """Everything the application frame needs, for this request.

    Computed once per request: the sidebar, the top bar and the palette
    all ask for it.
    """
    request = context.get("request")

    if request is not None:
        cached = getattr(request, "_generic_chrome", None)

        if cached is not None:
            return cached

    from generic.sites import site as default_site

    site = context.get("generic_site") or default_site
    chrome = site.get_chrome(request)

    if request is not None:
        request._generic_chrome = chrome

    return chrome


@register.inclusion_tag("generic/charts/chart.html", takes_context=True)
def generic_chart(
    context: Any,
    model: str,
    name: str,
    **overrides: Any,
) -> dict[str, Any]:
    """Draw a chart a resource declares, anywhere - a dashboard, say::

        {% generic_chart "example.ticket" "opened" height="20rem" %}

    Nothing is drawn for a user who may not see it. ``title``,
    ``description``, ``height`` and ``period`` may be overridden.
    """
    from django.core.exceptions import ImproperlyConfigured

    from generic.sites import site as default_site
    from generic.sites.charts import chart_entries

    site = context.get("generic_site") or default_site
    resource = site.get_resource_by_label(model)

    if resource is None:
        raise ImproperlyConfigured(f"No resource is registered for {model}.")

    allowed = {"title", "description", "height", "period"}
    unknown = set(overrides) - allowed

    if unknown:
        raise ImproperlyConfigured(
            f"generic_chart does not take {', '.join(sorted(unknown))}."
        )

    chart = resource.get_chart(name)

    if chart is not None and overrides.get("period"):
        if overrides["period"] not in chart.get_periods():
            raise ImproperlyConfigured(
                f"Chart '{name}' does not offer the period "
                f"'{overrides['period']}'."
            )

    config = resource.get_chart_config(
        context.get("request"), name, **overrides
    )

    return {"chart": chart_entries([config])[0] if config else None}


@register.simple_tag
def js_catalog_url() -> str:
    """URL of Django's JavaScript catalog, or an empty string.

    The catalog is optional: without it, the interface falls back to
    its English source strings rather than failing.
    """
    try:
        return reverse("javascript-catalog")
    except NoReverseMatch:
        return ""

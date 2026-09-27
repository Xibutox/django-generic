"""A record, described for its summary page.

The summary page draws what :func:`build_summary` returns - figures,
sections of labelled values, related tables - and so does every live
refresh of it, from the resource's ``<pk>/summary/`` endpoint. Values
arrive typed and already formatted in the user's language, so the
browser never has to guess what a date or a relation looks like::

    {"name": "team", "label": "Team", "type": "link",
     "display": "Front office", "url": "/example/team/1/"}
"""

from __future__ import annotations

import datetime
import decimal
import json
from typing import Any

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.template.defaultfilters import filesizeformat
from django.utils import formats, timezone
from django.utils.encoding import force_str
from django.utils.text import capfirst, slugify
from django.utils.translation import gettext

from generic.api.files import describe_file
from generic.api.tags import tag_items
from generic.sites.serializers import (
    flatten_fieldsets,
    resolve_display_callable,
    tag_style_of,
)
from generic.sites.transitions import is_transition_action

#: Related records listed inline as links, before "and N more".
LINKS_LIMIT = 20


def record_url(site: Any, request: Any, obj: Any) -> str:
    """The page ``obj`` opens on, when its model is registered and the
    user may see it."""
    resource = site.get_resource(type(obj)) or site.get_resource(
        obj._meta.concrete_model
    )

    if resource is None or not resource.has_view_permission(request, obj):
        return ""

    return resource.get_object_url(obj.pk)


def format_number(value: Any, decimal_places: int | None = None) -> str:
    return formats.number_format(
        value,
        decimal_pos=decimal_places,
        use_l10n=True,
        force_grouping=True,
    )


def describe_many(site: Any, request: Any, values: Any) -> dict[str, Any]:
    """Several records, as links, capped at ``LINKS_LIMIT``."""
    if isinstance(values, models.QuerySet):
        items = list(values[: LINKS_LIMIT + 1])
        more = values.count() - LINKS_LIMIT if len(items) > LINKS_LIMIT else 0
    else:
        items = list(values)
        more = max(0, len(items) - LINKS_LIMIT)

    if not items:
        return {"type": "links", "empty": True}

    return {
        "type": "links",
        "items": [
            {"label": force_str(item), "url": record_url(site, request, item)}
            for item in items[:LINKS_LIMIT]
        ],
        "more": more,
    }


def describe_tags(
    site: Any,
    request: Any,
    style: Any,
    values: Any,
    labels: Any = None,
) -> dict[str, Any]:
    """Values drawn as coloured tags, each record linking to its page."""
    if isinstance(values, models.QuerySet):
        items = list(values[: LINKS_LIMIT + 1])
        more = values.count() - LINKS_LIMIT if len(items) > LINKS_LIMIT else 0
    else:
        items = tag_items(values)
        more = max(0, len(items) - LINKS_LIMIT)

    tags = []

    for item in items[:LINKS_LIMIT]:
        described = style.describe_all([item], labels)

        if not described:
            continue

        tag = described[0]

        if isinstance(item, models.Model):
            tag["url"] = record_url(site, request, item)

        tags.append(tag)

    if not tags:
        return {"type": "tags", "empty": True}

    return {"type": "tags", "items": tags, "more": more}


def describe_value(
    site: Any,
    request: Any,
    value: Any,
    boolean: bool = False,
) -> dict[str, Any]:
    """A value computed by a method or a property, typed by what it is."""
    if boolean:
        if value is None:
            return {"type": "boolean", "empty": True}

        return {"type": "boolean", "value": bool(value)}

    if value is None or value == "":
        return {"type": "text", "empty": True}

    if isinstance(value, bool):
        return {"type": "boolean", "value": value}

    if isinstance(value, datetime.datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)

        return {
            "type": "datetime",
            "value": value.isoformat(),
            "display": formats.date_format(value, "DATETIME_FORMAT"),
        }

    if isinstance(value, datetime.date):
        return {
            "type": "date",
            "value": value.isoformat(),
            "display": formats.date_format(value, "DATE_FORMAT"),
        }

    if isinstance(value, (int, float, decimal.Decimal)):
        return {"type": "number", "display": format_number(value)}

    if isinstance(value, models.Model):
        return {
            "type": "link",
            "display": force_str(value),
            "url": record_url(site, request, value),
        }

    if isinstance(value, models.QuerySet) or hasattr(value, "all"):
        return describe_many(
            site,
            request,
            value if isinstance(value, models.QuerySet) else value.all(),
        )

    if isinstance(value, (list, tuple, set)):
        if all(isinstance(item, models.Model) for item in value):
            return describe_many(site, request, value)

        return {
            "type": "text",
            "display": ", ".join(force_str(item) for item in value),
        }

    text = force_str(value)

    return {"type": "text", "display": text, "multiline": "\n" in text}


def field_value(obj: Any, field: Any) -> Any:
    """What ``field`` holds on ``obj``: records, a record, or a value."""
    if field.many_to_many or field.one_to_many:
        accessor = (
            field.get_accessor_name()
            if isinstance(field, models.ForeignObjectRel)
            else field.name
        )

        return getattr(obj, accessor).all()

    if field.is_relation:
        try:
            return getattr(obj, field.name)
        except models.ObjectDoesNotExist:
            return None

    return getattr(obj, field.attname)


def describe_stored_file(
    resource: Any,
    obj: Any,
    field: Any,
    value: Any,
) -> dict[str, Any]:
    """A file of the record: its name, linking to its download.

    ``value`` is ``{"name", "url", "size"}``, as the form reads it; the
    link is the resource's permission-checked endpoint, never the
    storage's own URL.
    """
    described = describe_file(value, resource.get_file_url(obj.pk, field.name))

    if described is None:
        return {"type": "file", "empty": True}

    size = described["size"]

    return {
        "type": "file",
        "display": described["name"],
        "url": described["url"] or "",
        "size": size,
        "sizeDisplay": filesizeformat(size) if size is not None else "",
        "value": described,
    }


def describe_field(
    resource: Any,
    request: Any,
    obj: Any,
    field: Any,
) -> dict[str, Any]:
    """A model field's value on ``obj``."""
    site = resource.site
    style = resource.get_tag_style(field.name)

    if style is not None:
        return describe_tags(
            site,
            request,
            style,
            field_value(obj, field),
            (
                dict(field.flatchoices)
                if getattr(field, "choices", None)
                else None
            ),
        )

    if field.many_to_many or field.one_to_many:
        accessor = (
            field.get_accessor_name()
            if isinstance(field, models.ForeignObjectRel)
            else field.name
        )

        return describe_many(site, request, getattr(obj, accessor).all())

    if field.is_relation:
        try:
            related = getattr(obj, field.name)
        except models.ObjectDoesNotExist:
            related = None

        if related is None:
            return {"type": "link", "empty": True}

        return {
            "type": "link",
            "display": force_str(related),
            "url": record_url(site, request, related),
        }

    value = getattr(obj, field.attname)

    if field.choices:
        if value is None or value == "":
            return {"type": "choice", "empty": True}

        return {
            "type": "choice",
            "value": force_str(value),
            "display": force_str(dict(field.flatchoices).get(value, value)),
        }

    if isinstance(field, models.BooleanField):
        return describe_value(site, request, value, boolean=True)

    if isinstance(field, models.FileField):
        return describe_stored_file(resource, obj, field, value)

    if value is None or value == "":
        return {"type": "text", "empty": True}

    if isinstance(field, models.DecimalField):
        return {
            "type": "number",
            "display": format_number(value, field.decimal_places),
        }

    if isinstance(field, models.EmailField):
        return {"type": "email", "display": value}

    if isinstance(field, models.URLField):
        return {"type": "url", "display": value, "url": value}

    if isinstance(field, models.JSONField):
        return {
            "type": "text",
            "display": json.dumps(value, indent=2, ensure_ascii=False),
            "multiline": True,
            "code": True,
        }

    if isinstance(field, models.TextField):
        return {"type": "text", "display": force_str(value), "multiline": True}

    return describe_value(site, request, value)


def describe_entry(
    resource: Any,
    request: Any,
    obj: Any,
    name: str,
) -> dict[str, Any]:
    """One entry of a section or a figure: a field, or something computed."""
    model = resource.model

    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        field = None

    if field is not None:
        label = getattr(field, "verbose_name", None) or (
            field.related_model._meta.verbose_name_plural
        )
        entry = describe_field(resource, request, obj, field)
        entry.update(name=name, label=capfirst(force_str(label)))
    else:
        function = resolve_display_callable(name, resource, model)

        if function is None:
            raise ImproperlyConfigured(
                f"{type(resource).__name__} shows '{name}' on the summary "
                f"page, which is neither a field of {model.__name__}, a "
                f"method of the resource, nor an attribute of the model."
            )

        label = getattr(function, "short_description", None) or (
            name.replace("_", " ")
        )
        tags = getattr(function, "tags", None)

        if tags:
            entry = describe_tags(
                resource.site, request, tag_style_of(tags), function(obj)
            )
        else:
            entry = describe_value(
                resource.site,
                request,
                function(obj),
                boolean=bool(getattr(function, "boolean", False)),
            )

        entry.update(name=name, label=capfirst(force_str(label)))

    # Long text and lists of links take the width of the section.
    count = len(entry.get("items", ()))
    entry["wide"] = bool(
        entry.get("multiline")
        or (entry.get("type") == "links" and count > 4)
        or (entry.get("type") == "tags" and count > 8)
    )

    return entry


def build_sections(
    resource: Any,
    request: Any,
    obj: Any,
) -> list[dict[str, Any]]:
    sections = []

    for index, (title, options) in enumerate(
        resource.get_detail_fieldsets(request)
    ):
        names = flatten_fieldsets([(title, options)])
        classes = tuple(options.get("classes", ()))
        title = force_str(title or "")

        sections.append(
            {
                "name": slugify(title) or f"section-{index}",
                "title": title,
                "description": force_str(options.get("description", "")),
                "collapsed": "collapse" in classes,
                "fields": [
                    describe_entry(resource, request, obj, name)
                    for name in names
                ],
            }
        )

    return sections


def build_history_entry(resource: Any, obj: Any) -> dict[str, Any] | None:
    """Where this record's history is, and what it last says.

    ``None`` where the model keeps none, which is what hides the tab.
    """
    from generic.history.reading import last_change
    from generic.history.recording import is_recorded

    if not is_recorded(resource):
        return None

    return {
        "url": resource.get_history_api_url(obj.pk),
        # Named here rather than in the browser: the tab bar is built
        # from one list, and this is the only entry of it that is not
        # a related table.
        "label": gettext("History"),
        "last": last_change(resource, obj),
    }


def build_summary(resource: Any, request: Any, obj: Any) -> dict[str, Any]:
    """Everything the summary page of ``obj`` shows."""
    can_change = resource.has_change_permission(request, obj)
    can_delete = resource.has_delete_permission(request, obj)

    related = [
        {
            "name": bound.name,
            "title": bound.get_title(),
            "icon": bound.get_icon(),
            "description": force_str(bound.definition.description),
            "count": bound.count(request, obj),
            "addUrl": bound.get_add_url(request, obj),
        }
        for bound in resource.get_related_tables(request)
        if bound.is_visible(request)
    ]

    return {
        "object": {
            "pk": force_str(obj.pk),
            "label": resource.get_object_label(obj),
            "model": resource.label_lower,
            "verboseName": resource.get_label(),
            "icon": resource.get_icon(),
        },
        "urls": {
            "summary": resource.get_summary_api_url(obj.pk),
            "change": resource.get_change_url(obj.pk) if can_change else "",
            "delete": resource.get_delete_url(obj.pk) if can_delete else "",
            "list": (
                resource.get_list_url()
                if resource.has_view_permission(request)
                else ""
            ),
            "actions": resource.get_actions_url(),
            "transitions": resource.get_transitions_url(obj.pk),
        },
        # Bulk actions work on one record too; deleting has its own
        # button, and transitions theirs, below.
        "actions": [
            entry.as_client()
            for name, entry in resource.get_actions(request).items()
            if name != "delete_selected" and not is_transition_action(name)
        ],
        # What this reader may do to this record's state, now.
        "transitions": [
            info.describe(resource, obj)
            for info in resource.get_available_transitions(request, obj)
        ],
        "stats": [
            describe_entry(resource, request, obj, name)
            for name in resource.get_detail_stats(request)
        ],
        "sections": build_sections(resource, request, obj),
        "related": related,
        "history": build_history_entry(resource, obj),
        "topic": resource.topic_name if resource.realtime else "",
    }

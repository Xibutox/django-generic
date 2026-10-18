"""A few records side by side, the values that differ marked.

Declared on the resource with the fields to compare::

    @register(Article)
    class ArticleResource(ModelResource):
        # The summary page's sections and fields, in its order:
        compare_fields = True
        # or these fields only, in this order:
        compare_fields = ("category", "unit_cost", "supplier")

The list's selection bar then offers *Compare the selected ...* for two
to ``MAX_COMPARED`` rows ticked. It opens the page ``<model>/compare/``,
whose address names the records (``?ids=3,8,12``): a column per record,
a row per field, each value drawn as the summary page draws it, the rows
whose values differ marked, and a switch hiding the others.

The endpoint, ``GET api/<app>/<model>/compare/?ids=3,8,12``, reads the
records through the resource's queryset and asks the view permission of
each: a record the reader may not see is left out, as one that does not
exist.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_str
from django.utils.text import slugify
from django.utils.translation import gettext, gettext_lazy
from rest_framework.exceptions import ValidationError

from generic.sites.dashboard import check_entry
from generic.sites.pages import ResourcePage, ResourcePageView
from generic.sites.serializers import flatten_fieldsets

#: The most records compared at once: past it, the columns are too
#: narrow to read.
MAX_COMPARED = 6

#: The page's name, and its address piece.
PAGE_NAME = "compare"


def check(resource: Any) -> list[tuple[str, list[str]]]:
    """The sections compared - ``(title, names)`` - or a refusal naming
    the declaration. Empty when the resource compares nothing."""
    declared = resource.compare_fields
    owner = type(resource).__name__

    if not declared:
        return []

    if declared is True:
        sections = [
            (force_str(title or ""), list(flatten_fieldsets([(title, opts)])))
            for title, opts in resource.get_detail_fieldsets()
        ]
    elif isinstance(declared, str):
        raise ImproperlyConfigured(
            f"{owner}.compare_fields is a tuple of names, or True - not "
            f"one string."
        )
    else:
        sections = [("", list(declared))]

    for _title, names in sections:
        for name in names:
            check_entry(resource, "compare_fields", name)

    sections = [(title, names) for title, names in sections if names]

    if not sections:
        raise ImproperlyConfigured(
            f"{owner}.compare_fields names no field to compare."
        )

    return sections


def parse_ids(value: Any) -> list[str]:
    """``"3,8,12"`` (or several ``ids``) as distinct keys, in order."""
    if isinstance(value, (list, tuple)):
        value = ",".join(force_str(item) for item in value)

    keys: list[str] = []

    for piece in force_str(value or "").split(","):
        piece = piece.strip()

        if piece and piece not in keys:
            keys.append(piece)

    if len(keys) < 2:
        raise ValidationError(
            {"ids": [gettext("Name at least two records to compare.")]}
        )

    if len(keys) > MAX_COMPARED:
        raise ValidationError(
            {
                "ids": [
                    gettext("At most %(count)s records are compared at once.")
                    % {"count": MAX_COMPARED}
                ]
            }
        )

    return keys


def fingerprint(entry: dict[str, Any]) -> str:
    """What an entry shows, without its name and its layout: two equal
    fingerprints are the same value."""
    shown = {
        key: value
        for key, value in entry.items()
        if key not in ("name", "label", "wide")
    }

    return json.dumps(shown, sort_keys=True, default=str)


def find_records(resource: Any, request: Any, queryset: Any, keys: Any):
    """The records named, in the order named, the ones the reader may
    not see - or that are not there - left out."""
    by_key: dict[str, Any] = {}
    field = resource.model._meta.pk
    wanted: list[Any] = []

    # A key that cannot be one of this model's ("abc" for a number)
    # finds nothing, as a key no record has; "03" is the record 3.
    for key in keys:
        try:
            value = field.to_python(key)
        except DjangoValidationError:
            continue

        if value not in wanted:
            wanted.append(value)

    found = list(queryset.filter(pk__in=wanted)) if wanted else []

    for obj in found:
        if resource.has_view_permission(request, obj):
            by_key[force_str(obj.pk)] = obj

    return [
        by_key[force_str(value)]
        for value in wanted
        if force_str(value) in by_key
    ]


def answer(resource: Any, request: Any, queryset: Any, value: Any) -> dict:
    """``{records, sections: [{title, rows: [{name, label, same,
    values}]}], missing}`` for the records ``value`` names."""
    from generic.sites.summary import describe_entry, record_url

    keys = parse_ids(value)
    records = find_records(resource, request, queryset, keys)
    sections = []

    for index, (title, names) in enumerate(resource.get_compare_sections()):
        rows = []

        for name in names:
            values = [
                describe_entry(resource, request, obj, name) for obj in records
            ]

            # A field the reader may not see (field_permissions): no row.
            if values and all(entry.get("hidden") for entry in values):
                continue

            label = values[0]["label"] if values else name
            prints = {fingerprint(entry) for entry in values}

            for entry in values:
                entry.pop("name", None)
                entry.pop("label", None)

            rows.append(
                {
                    "name": name,
                    "label": label,
                    "same": len(prints) <= 1,
                    "values": values,
                }
            )

        sections.append(
            {
                "name": slugify(title) or f"section-{index}",
                "title": title,
                "rows": rows,
            }
        )

    return {
        "records": [
            {
                "id": force_str(obj.pk),
                "label": force_str(resource.get_object_label(obj)),
                "url": record_url(resource.site, request, obj),
            }
            for obj in records
        ],
        "sections": sections,
        "missing": len(keys) - len(records),
    }


def compare_page() -> ResourcePage:
    return ResourcePage(
        PAGE_NAME,
        view=ComparePageView,
        title=gettext_lazy("Compare"),
        icon="compare",
        # Opened from a selection, never from a button: without the
        # records it compares it is an empty page.
        button=False,
    )


class ComparePageView(ResourcePageView):
    """The page comparing the records its address names."""

    template_name = "generic/resource/compare.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        resource = self.resource
        context["compare_config"] = {
            "url": resource.get_compare_url(),
            "ids": self.request.GET.get("ids", ""),
            "max": MAX_COMPARED,
            "listUrl": resource.get_list_url(),
        }

        return context


__all__ = [
    "ComparePageView",
    "MAX_COMPARED",
    "answer",
    "check",
    "compare_page",
    "parse_ids",
]

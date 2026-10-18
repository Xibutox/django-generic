"""Labels to print: a record's name, a few of its values and a QR code
leading to its page - to stick on a machine, a box, a shelf.

Declared on the resource::

    @register(Equipment)
    class EquipmentResource(ModelResource):
        labels = True              # the list's first columns
        labels = Labels(fields=("serial_number", "site"), size="small")

Two ways to print them:

* **Many at once.** The list's selection bar gains the bulk action
  *Print labels*: the rows ticked, or every row the filters match, up
  to ``MAX_LABELS``. It opens ``<model>/labels/?ids=3,8,12``, a sheet of
  labels laid out for the printer.
* **One.** A record's page gains a *Label* button, ``<model>/<pk>/label/``.

The QR code holds the address of the record's page, absolute, so a
phone scanning it opens the record (signed in, with the rights its
reader has: the code opens nothing by itself). ``content`` encodes
something else - a field, a method, any text.

Codes are drawn by segno (``pip install django-generic[labels]``),
pure Python, as inline SVG. Without it, labels still print, the address
written out in place of the code.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Sequence

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_str
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext, gettext_lazy, pgettext_lazy
from rest_framework.response import Response

from generic.sites.dashboard import check_entry
from generic.sites.pages import ResourcePage, ResourcePageView

#: The most labels a sheet holds: past it, filter the list further.
MAX_LABELS = 500

#: The sheet's page and the record's.
SHEET_PAGE = "labels"
RECORD_PAGE = "label"

#: The bulk action printing the selection.
ACTION_NAME = "print_labels"

#: A label's size, in millimetres: what common sheets of stickers use
#: (css/labels.css draws each, as .label-sheet--<size>).
SIZES = {
    "small": (38, 21),
    "medium": (63, 38),
    "large": (99, 57),
}

#: Fields shown when ``labels = True``: the list's first columns.
DEFAULT_FIELDS = 3


@dataclasses.dataclass(frozen=True)
class Labels:
    """What a label shows, and how large it is."""

    #: Values written under the record's name: fields, model attributes
    #: or resource methods, as a summary page shows them. None: the
    #: list's first columns.
    fields: Sequence[str] | None = None
    #: "small", "medium" or "large" (``SIZES``).
    size: str = "medium"
    #: What the code holds: None, the record's page; a field, a method
    #: of the resource or an attribute of the model, its value.
    content: str | None = None
    #: The label's first line: a field or method; default the record's
    #: label.
    title: str | None = None
    #: Needed besides the resource's view permission, as a page's.
    permission: Any = None


def labels_of(declared: Any) -> Labels | None:
    if not declared:
        return None

    if declared is True:
        return Labels()

    if isinstance(declared, Labels):
        return declared

    raise ImproperlyConfigured(
        f"labels is True or Labels(...), not {declared!r}."
    )


def check(resource: Any) -> Labels | None:
    """The declaration, its fields worked out and checked - or a refusal
    naming the resource."""
    try:
        definition = labels_of(resource.labels)
    except ImproperlyConfigured as error:
        raise ImproperlyConfigured(
            f"{type(resource).__name__}.{error}"
        ) from None

    if definition is None:
        return None

    owner = type(resource).__name__

    if definition.size not in SIZES:
        raise ImproperlyConfigured(
            f"{owner}.labels: size '{definition.size}' is not one of "
            f"{', '.join(SIZES)}."
        )

    if isinstance(definition.fields, str):
        raise ImproperlyConfigured(
            f"{owner}.labels: fields is a tuple of names, not one string."
        )

    fields = definition.fields

    if fields is None:
        title = definition.title
        fields = tuple(
            name
            for name in resource.get_list_display()
            if isinstance(name, str) and name not in ("__str__", title)
        )[1 : DEFAULT_FIELDS + 1]

    for name in (
        *fields,
        *([definition.content] if definition.content else ()),
        *([definition.title] if definition.title else ()),
    ):
        check_entry(resource, "labels", name)

    return dataclasses.replace(definition, fields=tuple(fields))


# -- drawing --------------------------------------------------------------


def entry_text(entry: dict[str, Any]) -> str:
    """A summary-typed value as one line of text."""
    if entry.get("empty"):
        return ""

    if entry.get("items"):
        return ", ".join(
            force_str(item.get("label", "")) for item in entry["items"]
        )

    if entry.get("type") == "boolean":
        return gettext("Yes") if entry.get("value") else gettext("No")

    return force_str(entry.get("display", ""))


def qr_svg(content: str) -> SafeString | None:
    """``content`` as an inline SVG QR code, or None without segno."""
    try:
        import segno
    except ImportError:
        return None

    code = segno.make(content, error="m", micro=False)
    svg = code.svg_inline(
        scale=1,
        border=2,
        omitsize=True,
        # Black on the label's white, whatever the page's theme: a code
        # is read dark on light only.
        dark="#000",
        svgclass="print-label__code",
        lineclass="",
    )

    # segno's own markup, from the code's modules alone: no text of the
    # record reaches it.
    return mark_safe(svg)  # nosec B308 B703


def describe(resource: Any, request: Any, definition: Labels, obj: Any):
    """One label: its title, its lines, its code."""
    from generic.sites.summary import describe_entry, record_url

    if definition.title:
        title = entry_text(
            describe_entry(resource, request, obj, definition.title)
        )
    else:
        title = force_str(resource.get_object_label(obj))

    lines = []

    for name in definition.fields or ():
        entry = describe_entry(resource, request, obj, name)
        text = entry_text(entry)

        if text:
            lines.append({"label": entry.get("label", ""), "text": text})

    if definition.content:
        content = entry_text(
            describe_entry(resource, request, obj, definition.content)
        )
    else:
        content = request.build_absolute_uri(
            record_url(resource.site, request, obj)
            or resource.get_object_url(obj.pk)
        )

    return {
        "id": force_str(obj.pk),
        "title": title,
        "lines": lines,
        "content": content,
        "code": qr_svg(content) if content else None,
    }


def parse_ids(value: Any) -> list[str]:
    keys: list[str] = []

    for piece in force_str(value or "").split(","):
        piece = piece.strip()

        if piece and piece not in keys:
            keys.append(piece)

    return keys[:MAX_LABELS]


def find_records(resource: Any, request: Any, keys: Sequence[str]) -> list:
    """The records named, in the order named, those the reader may not
    see left out."""
    field = resource.model._meta.pk
    wanted: list[Any] = []

    for key in keys:
        try:
            value = field.to_python(key)
        except DjangoValidationError:
            continue

        if value not in wanted:
            wanted.append(value)

    if not wanted:
        return []

    found = {
        force_str(obj.pk): obj
        for obj in resource.get_list_queryset(request).filter(pk__in=wanted)
        if resource.has_view_permission(request, obj)
    }

    return [
        found[force_str(value)]
        for value in wanted
        if force_str(value) in found
    ]


# -- the action, the pages ---------------------------------------------------


def print_action(resource: Any):
    """The bulk action: the selection's sheet of labels."""

    def print_labels(request: Any, queryset: Any) -> Any:
        count = queryset.count()

        if count > MAX_LABELS:
            return Response(
                {
                    "message": gettext(
                        "At most %(count)s labels are printed at once: "
                        "filter the list further."
                    )
                    % {"count": MAX_LABELS},
                    "level": "error",
                }
            )

        ids = ",".join(
            force_str(pk)
            for pk in queryset.order_by(
                *(resource.get_ordering(request) or ("pk",))
            ).values_list("pk", flat=True)
        )

        return Response(
            {"redirect": f"{resource.get_page_url(SHEET_PAGE)}?ids={ids}"}
        )

    return print_labels


def sheet_page(definition: Labels) -> ResourcePage:
    return ResourcePage(
        SHEET_PAGE,
        view=LabelSheetView,
        title=gettext_lazy("Labels"),
        icon="qr_code_2",
        # Opened from a selection: without one it is an empty sheet.
        button=False,
        permission=definition.permission,
    )


def record_page(definition: Labels) -> ResourcePage:
    return ResourcePage(
        RECORD_PAGE,
        view=LabelSheetView,
        detail=True,
        # A sticker, not the name of a field.
        title=pgettext_lazy("sticker", "Label"),
        icon="qr_code_2",
        description=gettext_lazy("A label of this record, to print."),
        permission=definition.permission,
    )


class LabelSheetView(ResourcePageView):
    """A sheet of labels: the records its address names, or the one
    record of a record's page."""

    template_name = "generic/resource/labels.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        resource = self.resource
        definition = resource.get_labels()

        if self.object is not None:
            records = [self.object]
        else:
            records = find_records(
                resource, self.request, parse_ids(self.request.GET.get("ids"))
            )

        context.update(
            labels=[
                describe(resource, self.request, definition, obj)
                for obj in records
            ],
            label_size=definition.size,
            list_url=resource.get_list_url(),
        )

        return context


__all__ = [
    "Labels",
    "LabelSheetView",
    "MAX_LABELS",
    "SIZES",
    "check",
    "qr_svg",
]

"""Pages worked out from the model: the minimal declaration.

A ``ModelResource`` says everything by hand - the columns, the search,
the form, the tables of related rows. That is the way to a page shaped
exactly as the work needs it. This is the other way: one line, and the
model says the rest::

    from generic.sites import auto

    auto(Supplier, related=("equipment",))
    auto(Equipment, related=("maintenances",))

Each line gives the model its five pages - list, summary, add, change,
delete - its endpoint, its place in the navigation, its history and its
live updates, and works out from the model what a resource would have
declared:

* **the list's columns** - the field that names a row first, then the
  others in the model's order: no long text, nothing that looks like a
  secret, at most ``max_columns``;
* **the search** - the text fields, and the name of each record a row
  points at;
* **choices as coloured tags**, one colour per choice;
* **the form**, two short fields a row, long text underneath;
* **an icon**, from the words of the model's name.

Only the related rows are asked for, by the relation's name: each gets
a table on the summary page - its own columns, filters, search, export -
and, for a reverse foreign key, a tab of its rows edited on the form. A
related model nobody declared is given pages of its own the same way,
out of the navigation: it is reached from its parent.

Anything declared wins over what is worked out. ``auto(Equipment,
list_display=(...))``, or a class::

    @register(Equipment)
    class EquipmentResource(AutoResource):
        related = ("maintenances",)
        exclude = ("notes",)
        icon = "laptop"

and the rest is still worked out.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models

from generic.api.tags import TagStyle
from generic.sites.inlines import TabularInline
from generic.sites.related import RelatedTable
from generic.sites.resources import ModelResource
from generic.sites.serializers import default_form_fields, label_field_for

#: Colours given to a field's choices, in the order they are declared:
#: enough to tell eight apart, then round again.
PALETTE = (
    "#2563eb",
    "#16a34a",
    "#d97706",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#64748b",
)

#: A column named like this is left out of the list and of the search:
#: a secret in a table is a secret for everyone who may read it.
PRIVATE = re.compile(r"password|secret|token|api_?key|hash|salt", re.I)

#: The Material Symbols icon for a word of a model's name.
ICONS = {
    "account": "account_circle",
    "address": "home",
    "agent": "support_agent",
    "article": "article",
    "asset": "devices",
    "booking": "event_available",
    "category": "category",
    "client": "domain",
    "comment": "chat",
    "company": "domain",
    "contact": "contacts",
    "contract": "contract",
    "customer": "domain",
    "device": "devices",
    "document": "description",
    "employee": "badge",
    "equipment": "devices",
    "event": "event",
    "file": "description",
    "invoice": "receipt_long",
    "issue": "bug_report",
    "item": "inventory_2",
    "location": "location_on",
    "maintenance": "build",
    "meeting": "groups",
    "message": "mail",
    "note": "sticky_note_2",
    "order": "shopping_cart",
    "payment": "payments",
    "person": "person",
    "product": "inventory_2",
    "project": "folder",
    "quote": "request_quote",
    "repair": "build",
    "report": "summarize",
    "reservation": "event_available",
    "site": "location_on",
    "stock": "inventory_2",
    "supplier": "local_shipping",
    "tag": "sell",
    "task": "task_alt",
    "team": "groups",
    "ticket": "confirmation_number",
    "user": "person",
    "vehicle": "directions_car",
    "vendor": "local_shipping",
}

#: Columns an inline row shows at most, required fields apart.
INLINE_COLUMNS = 6


# -- what a field is ---------------------------------------------------------


def is_long(field: Any) -> bool:
    """Text too long for a cell or a half-width row."""
    return isinstance(field, (models.TextField, models.JSONField)) or (
        isinstance(field, models.BinaryField)
    )


def is_private(field: Any) -> bool:
    return bool(PRIVATE.search(field.name))


def is_required(field: Any) -> bool:
    """A field a new record cannot be saved without."""
    return bool(
        field.editable
        and not field.blank
        and not field.null
        and not field.has_default()
        and not getattr(field, "auto_now", False)
        and not getattr(field, "auto_now_add", False)
    )


def shows_in_list(field: Any) -> bool:
    """Whether a concrete field makes a useful column."""
    if field.auto_created or is_long(field) or is_private(field):
        return False

    if isinstance(field, (models.FileField, models.UUIDField)):
        return False

    # A timestamp the application keeps - created, modified - is worth
    # a column; any other value nobody may write is internal.
    if not field.editable:
        return isinstance(field, models.DateField)

    return True


def field_of(model: Any, name: str) -> Any:
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def naming_field(model: Any) -> str | None:
    """The field that names a row: a ``name``, a ``title``... or else
    the first plain text field - a maintenance visit's description."""
    label = label_field_for(model)

    if label:
        return label

    for field in model._meta.fields:
        if (
            isinstance(field, models.CharField)
            and not field.choices
            and not field.auto_created
            and not is_private(field)
        ):
            return field.name

    return None


# -- what a resource would have declared ---------------------------------


def infer_list_display(
    model: Any,
    limit: int = 7,
    exclude: Sequence[str] = (),
) -> tuple[str, ...]:
    """The columns: the naming field first, then the model's order."""
    names = [
        field.name
        for field in model._meta.fields
        if shows_in_list(field) and field.name not in exclude
    ]
    label = naming_field(model)

    if label in names:
        names.remove(label)
        names.insert(0, label)

    return tuple(names[:limit]) or ("__str__",)


def infer_search_fields(
    model: Any,
    exclude: Sequence[str] = (),
) -> tuple[str, ...]:
    """The text fields, then the name of each record a row points at."""
    short = []
    long_ = []

    for field in model._meta.fields:
        if field.name in exclude or is_private(field) or field.auto_created:
            continue

        if isinstance(field, models.CharField) and not field.choices:
            short.append(field.name)
        elif isinstance(field, models.TextField):
            long_.append(field.name)

    label = naming_field(model)

    if label in short:
        short.remove(label)
        short.insert(0, label)

    related = []

    for field in model._meta.fields:
        if field.many_to_one and field.name not in exclude:
            name = label_field_for(field.related_model)

            if name:
                related.append(f"{field.name}__{name}")

    return tuple((short + long_)[:5] + related[:2])


def infer_tag_fields(
    model: Any,
    exclude: Sequence[str] = (),
) -> dict[str, TagStyle]:
    """Every field with choices, drawn as tags: one colour a choice."""
    styles = {}

    for field in model._meta.fields:
        if not field.choices or field.name in exclude:
            continue

        if isinstance(field, models.BooleanField):
            continue

        styles[field.name] = TagStyle(
            colors={
                value: PALETTE[index % len(PALETTE)]
                for index, (value, _label) in enumerate(field.flatchoices)
            }
        )

    return styles


def infer_form_rows(
    model: Any,
    exclude: Sequence[str] = (),
) -> tuple[Any, ...]:
    """The form's rows: the name alone, short fields two by two, long
    text and many-to-many relations the whole width underneath."""
    short = []
    wide = []

    for name in default_form_fields(model, exclude=exclude):
        field = field_of(model, name)

        if field is not None and (field.many_to_many or is_long(field)):
            wide.append(name)
        else:
            short.append(name)

    rows: list[Any] = []
    label = naming_field(model)

    if label in short:
        short.remove(label)
        rows.append(label)

    for index in range(0, len(short), 2):
        pair = tuple(short[index : index + 2])
        rows.append(pair if len(pair) == 2 else pair[0])

    return tuple(rows + wide)


def infer_detail_rows(
    model: Any,
    rows: Sequence[Any],
    exclude: Sequence[str] = (),
) -> tuple[Any, ...]:
    """The summary's rows: the form's, then what the application keeps
    on its own - a creation date, a last change."""
    kept = [
        field.name
        for field in model._meta.fields
        if not field.editable
        and not field.auto_created
        and isinstance(field, models.DateField)
        and field.name not in exclude
    ]

    return tuple(rows) + tuple(kept)


def infer_icon(model: Any) -> str:
    """An icon from the words of the model's name: MaintenanceVisit is
    "maintenance", then "visit"."""
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", model.__name__)

    for word in words:
        word = word.lower()

        for candidate in (word, word.rstrip("s")):
            if candidate in ICONS:
                return ICONS[candidate]

    return "table_rows"


def related_field(model: Any, name: str, owner: str = "") -> Any:
    """The relation ``related`` names, or an error saying what it takes."""
    where = f"{owner}.related" if owner else "related"
    field = field_of(model, name)

    if field is None:
        choices = sorted(
            field.name
            for field in model._meta.get_fields()
            if field.is_relation and (field.one_to_many or field.many_to_many)
        )
        raise ImproperlyConfigured(
            f"{where} names '{name}', which is not a relation of "
            f"{model.__name__}. It takes the name a relation is reached "
            f"by from {model.__name__}: "
            f"{', '.join(choices) or 'it has none'}."
        )

    if not (field.is_relation and (field.one_to_many or field.many_to_many)):
        raise ImproperlyConfigured(
            f"{where} names '{name}', which holds one record, not rows: "
            f"it is a column already."
        )

    return field


def inline_fields(child: Any, fk: Any) -> tuple[str, ...]:
    """What a row edited on its parent's form shows.

    Every field it cannot be saved without - long text too - then the
    others that fit in a row, up to ``INLINE_COLUMNS``.
    """
    names = default_form_fields(child, exclude=[fk.name])
    required = [name for name in names if is_required(field_of(child, name))]
    optional = [
        name
        for name in names
        if name not in required
        and not is_long(field_of(child, name))
        and not field_of(child, name).many_to_many
    ]
    room = max(0, INLINE_COLUMNS - len(required))
    shown = set(required + optional[:room])

    return tuple(name for name in names if name in shown)


def build_inline(child: Any, fk: Any) -> type[TabularInline]:
    """A tab of the related rows, edited on the parent's form."""
    return type(
        f"{child.__name__}AutoInline",
        (TabularInline,),
        {
            "model": child,
            "fk_name": fk.name,
            "fields": inline_fields(child, fk),
            "classes": ("tab",),
            "__module__": __name__,
        },
    )


class AutoResource(ModelResource):
    """A resource that works out from the model what it does not say.

    Declare what matters and leave the rest: every attribute a class -
    or ``auto(...)``, or ``register(..., **options)`` - declares is
    kept; every other one below is worked out once, at registration.
    """

    #: Relations of the model, by the name it reaches them by - a
    #: reverse foreign key's related name, a many-to-many. Each gets a
    #: table on the summary page.
    related: Sequence[str] = ()
    #: Which of ``related`` are edited on the form, as a tab of rows.
    #: None: every reverse foreign key among them; ``()``: none - for a
    #: relation with hundreds of rows, which a form should not carry.
    related_inlines: Sequence[str] | None = None
    #: How many columns the list shows at first.
    max_columns: int = 7
    #: Draw every field with choices as coloured tags.
    tag_choices: bool = True

    def __init__(self, model: Any, site: Any) -> None:
        super().__init__(model, site)

        declared = declared_names(type(self))

        for name, value in self.infer(declared).items():
            setattr(self, name, value)

    def infer(self, declared: set[str]) -> dict[str, Any]:
        """What this model's declaration would have said, where it
        says nothing."""
        model = self.model
        owner = type(self).__name__
        exclude = tuple(self.exclude)
        worked_out: dict[str, Any] = {}

        if "list_display" not in declared:
            worked_out["list_display"] = infer_list_display(
                model, self.max_columns, exclude
            )

        if "search_fields" not in declared:
            worked_out["search_fields"] = infer_search_fields(model, exclude)

        if "tag_fields" not in declared and self.tag_choices:
            worked_out["tag_fields"] = infer_tag_fields(model, exclude)

        if "icon" not in declared:
            worked_out["icon"] = infer_icon(model)

        if not {"fields", "fieldsets"} & declared:
            rows = infer_form_rows(model, exclude)
            worked_out["fieldsets"] = ((None, {"fields": rows}),)

            if "detail_fieldsets" not in declared:
                worked_out["detail_fieldsets"] = (
                    (
                        None,
                        {"fields": infer_detail_rows(model, rows, exclude)},
                    ),
                )

        fields = [related_field(model, name, owner) for name in self.related]

        if "related_tables" not in declared:
            worked_out["related_tables"] = tuple(
                RelatedTable(name) for name in self.related
            )

        if "inlines" not in declared:
            edited = (
                None
                if self.related_inlines is None
                else set(self.related_inlines)
            )
            worked_out["inlines"] = tuple(
                build_inline(field.related_model, field.field)
                for name, field in zip(self.related, fields)
                if field.one_to_many
                and field.auto_created
                and (edited is None or name in edited)
            )

        return worked_out

    def get_related_models(self) -> list[Any]:
        """The models of ``related``: they need pages of their own."""
        return [
            related_field(self.model, name).related_model
            for name in self.related
        ]


def declared_names(cls: type) -> set[str]:
    """What the classes below ``AutoResource`` say themselves."""
    names: set[str] = set()

    for klass in cls.__mro__:
        if klass is AutoResource:
            break

        names.update(vars(klass))

    return names


def auto(model_or_models: Any, *, site: Any = None, **options: Any) -> None:
    """Give models their pages, worked out from each model.

    ``options`` are resource attributes - ``related``, ``group``,
    ``exclude``, ``list_display``... - and win over what is worked out.
    """
    from generic.sites.site import site as default_site

    (site or default_site).register(model_or_models, AutoResource, **options)


__all__ = [
    "AutoResource",
    "auto",
    "infer_form_rows",
    "infer_icon",
    "infer_list_display",
    "infer_search_fields",
    "infer_tag_fields",
]

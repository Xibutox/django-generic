"""Serializers generated from a resource declaration.

A resource names fields the way a ``ModelAdmin`` does. These factories
turn that into the two kinds of serializer the framework already drives
- a table declaration and a form declaration - so a generated screen and
a hand-written serializer go through exactly the same code.

Everything is derived from the model: a choice field becomes a
multiselect filter showing labels, a foreign key a Select2 filter fed by
the related model's autocomplete when it has one, a many-to-many a
comma-separated list filtered without duplicating rows.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Sequence

from django.contrib.admin.utils import NotRelationField, get_fields_from_path
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.utils.encoding import force_str
from django.utils.functional import lazy
from django.utils.text import slugify
from rest_framework import serializers

from generic.api.columns import (
    FILTER_BOOLEAN,
    FILTER_MULTISELECT,
    BooleanColumn,
    CharColumn,
    ChoiceColumn,
    DateColumn,
    DateTimeColumn,
    DecimalColumn,
    FileColumn,
    FloatColumn,
    IntegerColumn,
    ManyRelatedColumn,
    MethodColumn,
    TagsColumn,
    prettify_field_name,
)
from generic.api.forms import FormModelSerializer
from generic.api.serializers import DataTableModelSerializer
from generic.api.tags import TagStyle

#: Hidden field every generated row carries: the primary key, which the
#: client needs for row links, selection and row actions.
ROW_KEY = "_pk"

#: Public name of the ``__str__`` column.
LABEL_KEY = "_label"

#: Field names that make a good label for a row, by preference.
LABEL_CANDIDATES = (
    "name",
    "title",
    "label",
    "reference",
    "code",
    "username",
    "email",
)


# ---------------------------------------------------------------------
# Model introspection
# ---------------------------------------------------------------------


def is_many(field: Any) -> bool:
    return bool(
        getattr(field, "many_to_many", False)
        or getattr(field, "one_to_many", False)
    )


def is_text_field(model: type[models.Model], name: str) -> bool:
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return False

    return bool(getattr(field, "concrete", False)) and isinstance(
        field, (models.CharField, models.TextField)
    )


def plain_ordering(model: type[models.Model]) -> list[str]:
    """Field names of ``Meta.ordering``, without direction or paths."""
    names = []

    for entry in model._meta.ordering:
        if not isinstance(entry, str) or entry == "?":
            continue

        name = entry.lstrip("-")

        if "__" not in name:
            names.append(name)

    return names


def _joined_title(*parts: Any) -> str:
    return " ".join(force_str(part) for part in parts).capitalize()


#: ``Customer name`` from ``customer`` and ``name``, translated when it
#: is read rather than when the serializer class is built.
joined_title = lazy(_joined_title, str)


def label_field_for(model: type[models.Model]) -> str | None:
    """A text field naming the rows of ``model``, if it has one."""
    for candidate in [*plain_ordering(model), *LABEL_CANDIDATES]:
        if is_text_field(model, candidate):
            return candidate

    return None


def ordering_field_for(model: type[models.Model]) -> str | None:
    """What a column showing ``model`` rows should order on."""
    for name in plain_ordering(model):
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            continue

        if getattr(field, "concrete", False):
            return name

    return label_field_for(model)


def value_type_for(model: type[models.Model]) -> str:
    """How the primary keys of ``model`` are coerced when filtering."""
    return (
        "integer"
        if isinstance(model._meta.pk, models.IntegerField)
        else "string"
    )


def plain_value(value: Any) -> Any:
    """A value a JSON payload and a spreadsheet can both carry."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, models.Model):
        return force_str(value)

    if hasattr(value, "all"):
        return ", ".join(force_str(item) for item in value.all())

    if isinstance(value, (list, tuple, set)):
        return ", ".join(force_str(item) for item in value)

    return force_str(value)


def make_getter(
    function: Callable[[Any], Any],
    *,
    boolean: bool = False,
) -> Callable[[Any, Any], Any]:
    """A ``get_<name>`` method for a ``SerializerMethodField``."""

    def getter(serializer: Any, instance: Any) -> Any:
        value = function(instance)

        if boolean and value is not None:
            return bool(value)

        return plain_value(value)

    return getter


def make_icons_getter(
    function: Callable[[Any], Any],
) -> Callable[[Any, Any], list[dict[str, str]]]:
    """A ``get_<name>`` method for a column of ``@display(icons=True)``:
    the dicts the method returns, as ``{"icon", "url", "label"}`` - and
    ``"target"`` - the client draws. One without an address is left
    out."""

    def getter(serializer: Any, instance: Any) -> list[dict[str, str]]:
        icons = []

        for item in function(instance) or ():
            if not item or not item.get("url"):
                continue

            icon = {
                "icon": force_str(item.get("icon") or "link"),
                "url": force_str(item["url"]),
                "label": force_str(item.get("label") or ""),
            }

            if item.get("target"):
                icon["target"] = force_str(item["target"])

            icons.append(icon)

        return icons

    return getter


def model_attribute_reader(
    model: type[models.Model],
    name: str,
) -> Callable[[Any], Any]:
    """Read a property or a method of the model, admin style."""
    attribute = getattr(model, name)
    target = (
        getattr(attribute, "fget", None)
        or getattr(attribute, "func", None)
        or attribute
    )

    def read(instance: Any) -> Any:
        value = getattr(instance, name)

        return value() if callable(value) else value

    for key in (
        "short_description",
        "boolean",
        "admin_order_field",
        "tags",
        "icons",
    ):
        if hasattr(target, key):
            setattr(read, key, getattr(target, key))

    return read


def tag_style_of(value: Any) -> TagStyle:
    """The style ``@display(tags=...)`` gave: its own, or the default."""
    return value if isinstance(value, TagStyle) else TagStyle()


def related_resource(resource: Any, model: type[models.Model]) -> Any:
    """The resource registered for ``model`` on the same site."""
    return resource.site.get_resource(model)


def related_search_path(
    model: type[models.Model],
    resource: Any,
) -> str | None:
    """Which field of a related model the global search looks into."""
    if resource is not None:
        fields = resource.get_search_fields()

        if fields:
            return fields[0]

    return label_field_for(model)


# ---------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------


class TableSerializerBuilder:
    """Turn ``list_display`` into a ``DataTableModelSerializer``."""

    def __init__(
        self,
        resource: Any,
        list_display: Sequence[Any] | None = None,
        links: bool = True,
    ) -> None:
        self.resource = resource
        self.list_display = list_display
        #: Whether the link columns open their row's page.
        self.links = links
        self.model = resource.model
        self.declared: dict[str, Any] = {}
        self.methods: dict[str, Any] = {}
        self.names: list[str] = []
        #: list_display entry -> public column name.
        self.entry_names: dict[Any, str] = {}
        self.select_related: set[str] = set()
        self.prefetch_related: set[str] = set()
        #: Tag column -> the relation path its tags are records of.
        self.tag_links: dict[str, str] = {}

    def build(self) -> type[DataTableModelSerializer]:
        for entry in self.list_display or self.resource.get_list_display():
            self.add(entry)

        self.declared[ROW_KEY] = serializers.ReadOnlyField(source="pk")
        self.names.append(ROW_KEY)

        meta = type(
            "Meta",
            (),
            {"model": self.model, "fields": tuple(self.names)},
        )

        attributes = {
            **self.declared,
            **self.methods,
            "Meta": meta,
            "datatable_overrides": self.column_overrides(),
            "generic_select_related": tuple(sorted(self.select_related)),
            "generic_prefetch_related": tuple(sorted(self.prefetch_related)),
            "generic_tag_links": dict(self.tag_links),
            "__module__": __name__,
        }

        return type(
            f"{self.model.__name__}TableSerializer",
            (DataTableModelSerializer,),
            attributes,
        )

    # -- entries -------------------------------------------------------

    def add(self, entry: Any) -> None:
        if callable(entry) and not isinstance(entry, str):
            name = (
                getattr(entry, "__name__", "") or f"column_{len(self.names)}"
            )
            self.add_method(entry, name, entry)
            return

        if entry == "__str__":
            opts = self.model._meta

            def label(instance: Any) -> str:
                return force_str(instance)

            label.short_description = force_str(  # type: ignore[attr-defined]
                opts.verbose_name
            ).capitalize()
            self.add_method(entry, LABEL_KEY, label)
            return

        if callable(getattr(type(self.resource), entry, None)):
            self.add_method(entry, entry, getattr(self.resource, entry))
            return

        try:
            path = get_fields_from_path(self.model, entry)
        except (FieldDoesNotExist, NotRelationField):
            path = None

        if path:
            self.add_field(entry, path)
            return

        if hasattr(self.model, entry):
            self.add_method(
                entry,
                entry,
                model_attribute_reader(self.model, entry),
            )
            return

        raise ImproperlyConfigured(
            f"{type(self.resource).__name__}.list_display names "
            f"'{entry}', which is neither a field of "
            f"{self.model.__name__}, a method of the resource, nor an "
            f"attribute of the model."
        )

    def register(self, entry: Any, name: str, field: Any) -> None:
        self.declared[name] = field
        self.names.append(name)
        self.entry_names[entry] = name

    def add_method(
        self,
        entry: Any,
        name: str,
        function: Callable[[Any], Any],
    ) -> None:
        title = getattr(function, "short_description", None)
        # Kept lazy: the class is built once per process, and a title
        # forced here would stay in the language of the first request.
        options: dict[str, Any] = {
            "title": title if title else prettify_field_name(name)
        }

        ordering = getattr(function, "admin_order_field", None)

        if ordering:
            options.update(
                orderable=True,
                order_field=str(ordering).lstrip("-"),
            )

        filter_field = getattr(function, "filter_field", None)

        if filter_field:
            options.update(filterable=True, filter_field=filter_field)

            if getattr(function, "filter_type", None):
                options["filter_type"] = function.filter_type  # type: ignore

        search_field = getattr(function, "search_field", None)

        if search_field:
            options.update(searchable=True, search_field=search_field)

        tags = getattr(function, "tags", None)

        if tags:
            # The whole row goes to the method, whose result is drawn
            # as tags; like any computed column, filtering and ordering
            # only exist where the declaration points at real paths.
            for key in ("filterable", "orderable", "searchable"):
                options.setdefault(key, False)

            self.register(
                entry,
                name,
                TagsColumn(
                    source="*",
                    reader=function,
                    tag_style=tag_style_of(tags),
                    **options,
                ),
            )
            return

        if getattr(function, "icons", False):
            # Shortcuts of the row: nothing an export could write.
            options.update(display_type="icons", exportable=False)
            self.register(entry, name, MethodColumn(**options))
            self.methods[f"get_{name}"] = make_icons_getter(function)
            return

        boolean = bool(getattr(function, "boolean", False))

        if boolean:
            options["display_type"] = FILTER_BOOLEAN

        self.register(entry, name, MethodColumn(**options))
        self.methods[f"get_{name}"] = make_getter(function, boolean=boolean)

    def add_field(self, entry: str, path: list[Any]) -> None:
        final = path[-1]

        if any(is_many(field) for field in path[:-1]):
            raise ImproperlyConfigured(
                f"{type(self.resource).__name__}.list_display: "
                f"'{entry}' goes through a many-valued relation. Use a "
                f"method column instead."
            )

        title = joined_title(
            *(
                getattr(field, "verbose_name", None)
                or field.related_model._meta.verbose_name_plural
                for field in path
            )
        )

        prefix = entry.split("__")[:-1]

        if prefix:
            self.select_related.add("__".join(prefix))

        style = self.resource.get_tag_style(entry)

        if is_many(final):
            self.add_many(entry, final, title, style)
        elif final.is_relation:
            self.add_foreign_key(entry, final, title, style)
        elif style is not None:
            self.register(
                entry,
                entry,
                self.tags_column_for(final, entry, title, style),
            )
        else:
            self.register(entry, entry, self.column_for(final, entry, title))

    @staticmethod
    def source_for(name: str, source: str | None = None) -> dict[str, str]:
        """The ``source`` option of a column named after a field path.

        DRF refuses a ``source`` that repeats the field name, which is
        what a plain field's would be: it is only given when it differs.
        """
        source = source or name.replace("__", ".")

        return {} if source == name else {"source": source}

    def column_for(self, field: Any, name: str, title: str) -> Any:
        common = {**self.source_for(name), "read_only": True, "title": title}

        if field.choices:
            value_type = (
                "integer"
                if isinstance(field, models.IntegerField)
                else "string"
            )

            return ChoiceColumn(
                choices=field.choices,
                value_type=value_type,
                allow_null=True,
                **common,
            )

        if isinstance(field, models.BooleanField):
            return BooleanColumn(allow_null=True, **common)

        # Before DateField: a DateTimeField is one.
        if isinstance(field, models.DateTimeField):
            return DateTimeColumn(allow_null=True, **common)

        if isinstance(field, models.DateField):
            return DateColumn(allow_null=True, **common)

        if isinstance(field, models.DecimalField):
            return DecimalColumn(
                max_digits=field.max_digits,
                decimal_places=field.decimal_places,
                allow_null=True,
                **common,
            )

        if isinstance(field, models.FloatField):
            return FloatColumn(allow_null=True, **common)

        if isinstance(field, models.IntegerField):
            return IntegerColumn(allow_null=True, **common)

        # Its name, linking to the permission-checked download.
        if isinstance(field, models.FileField):
            return FileColumn(**common)

        if isinstance(field, (models.CharField, models.TextField)):
            # Long text is given room, rather than a word per line.
            wide = isinstance(field, models.TextField) or (
                (field.max_length or 0) >= 100
            )

            # A short, repeating value - a city, a category - is worth
            # offering as a list in the filter; a unique code or long
            # text is not.
            short = (
                not wide
                and not field.unique
                and isinstance(field, models.CharField)
            )

            return CharColumn(
                allow_null=True,
                allow_blank=True,
                class_name="dt-col--wide" if wide else None,
                facetable=True if short else None,
                **common,
            )

        # A time, a UUID, some JSON: shown as text, not filtered - an
        # icontains on those is either meaningless or an error.
        return CharColumn(
            allow_null=True,
            allow_blank=True,
            filterable=False,
            searchable=False,
            **common,
        )

    def tags_column_for(
        self,
        field: Any,
        name: str,
        title: str,
        style: TagStyle,
    ) -> TagsColumn:
        """A plain field drawn as a tag: a choice, most often."""
        options: dict[str, Any] = {
            **self.source_for(name),
            "title": title,
            "tag_style": style,
        }

        if field.choices:
            options.update(
                choices=dict(field.flatchoices),
                filter_type=FILTER_MULTISELECT,
                value_type=(
                    "integer"
                    if isinstance(field, models.IntegerField)
                    else "string"
                ),
            )
        elif not isinstance(field, (models.CharField, models.TextField)):
            options.update(filterable=False, searchable=False)

        return TagsColumn(**options)

    def add_foreign_key(
        self,
        entry: str,
        field: Any,
        title: str,
        style: TagStyle | None = None,
    ) -> None:
        related = field.related_model
        resource = related_resource(self.resource, related)

        options: dict[str, Any] = {
            **self.source_for(entry),
            "read_only": True,
            "allow_null": True,
            "title": title,
        }

        order_path = ordering_field_for(related)
        options["order_field"] = (
            f"{entry}__{order_path}" if order_path else entry
        )

        search_path = related_search_path(related, resource)

        if search_path:
            options["search_field"] = f"{entry}__{search_path}"
        else:
            options["searchable"] = False

        label = label_field_for(related)

        if resource is not None and resource.get_search_fields():
            # Filtered on the key itself, picked through the related
            # model's own autocomplete: exact, and cheap however many
            # rows the related table holds.
            options.update(
                filter_type=FILTER_MULTISELECT,
                filter_field=entry,
                value_type=value_type_for(related),
                autocomplete_route=resource.api_url_name("autocomplete"),
                minimum_input_length=0,
            )
        elif label:
            options["filter_field"] = f"{entry}__{label}"
            options["facetable"] = True
        else:
            options["filterable"] = False

        self.select_related.add(entry)

        if style is not None:
            # The tag carries the related key itself, and links with it.
            self.register(entry, entry, TagsColumn(tag_style=style, **options))
            self.tag_links[entry] = entry
            return

        self.register(entry, entry, CharColumn(**options))

        # The related key rides along with the row, unseen, so the cell
        # can link to the related record's page - when the user may
        # open it, which ModelResource.get_table_config decides.
        key = f"_fk_{entry}"
        self.declared[key] = serializers.ReadOnlyField(
            source=f"{entry.replace('__', '.')}_id"
        )
        self.names.append(key)

    def add_many(
        self,
        entry: str,
        field: Any,
        title: str,
        style: TagStyle | None = None,
    ) -> None:
        related = field.related_model
        resource = related_resource(self.resource, related)
        source = (
            field.get_accessor_name()
            if isinstance(field, models.ForeignObjectRel)
            else entry
        )

        options: dict[str, Any] = {
            **self.source_for(entry, source),
            "title": title,
        }

        search_path = related_search_path(related, resource)

        if search_path:
            options["search_field"] = f"{entry}__{search_path}"
        else:
            options["searchable"] = False

        label = label_field_for(related)

        if resource is not None and resource.get_search_fields():
            options.update(
                filter_type=FILTER_MULTISELECT,
                filter_field=entry,
                value_type=value_type_for(related),
                autocomplete_route=resource.api_url_name("autocomplete"),
                minimum_input_length=0,
            )
        elif label:
            options["filter_field"] = f"{entry}__{label}"
        else:
            options["filterable"] = False

        self.prefetch_related.add(source)

        if style is not None:
            self.register(
                entry,
                entry,
                TagsColumn(
                    tag_style=style,
                    orderable=False,
                    filter_many=True,
                    **options,
                ),
            )
            self.tag_links[entry] = entry
            return

        self.register(entry, entry, ManyRelatedColumn(**options))

    # -- links ---------------------------------------------------------

    def column_overrides(self) -> dict[str, dict[str, Any]]:
        """The link columns, and the ones the table starts without."""
        overrides = self.link_overrides()

        for entry in getattr(self.resource, "list_display_hidden", ()):
            name = self.entry_names.get(entry, entry)

            if name in self.declared and name != ROW_KEY:
                overrides.setdefault(name, {})["visible"] = False

        return overrides

    def link_overrides(self) -> dict[str, dict[str, Any]]:
        """Make the link columns open the change page of their row."""
        template = self.resource.get_row_url_template() if self.links else ""

        if not template:
            return {}

        links = self.resource.list_display_links

        if links is None:
            names = self.names[:1]
        else:
            names = [self.entry_names.get(entry, entry) for entry in links]

        return {
            name: {"display_type": "link", "link_url": template}
            for name in names
            if name in self.declared and name != ROW_KEY
            # Tags link each to their own record, not to the row's; a
            # file to its download.
            and not isinstance(self.declared[name], (TagsColumn, FileColumn))
        }


def build_table_serializer(
    resource: Any,
    list_display: Sequence[Any] | None = None,
    links: bool = True,
) -> type[DataTableModelSerializer]:
    """``resource``'s table - or one of other columns, ``list_display``,
    its rows leading nowhere without ``links``."""
    return TableSerializerBuilder(resource, list_display, links).build()


def with_row_key(
    serializer_class: type[DataTableModelSerializer],
) -> type[DataTableModelSerializer]:
    """A hand-written table serializer, plus the hidden row key."""
    if ROW_KEY in getattr(serializer_class, "_declared_fields", {}):
        return serializer_class

    meta = serializer_class.Meta
    fields = getattr(meta, "fields", None)

    attributes: dict[str, Any] = {
        ROW_KEY: serializers.ReadOnlyField(source="pk"),
        "__module__": serializer_class.__module__,
    }

    if fields is not None and fields != serializers.ALL_FIELDS:
        attributes["Meta"] = type(
            "Meta",
            (meta,),
            {"fields": (*tuple(fields), ROW_KEY)},
        )

    return type(serializer_class.__name__, (serializer_class,), attributes)


# ---------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------


def default_form_fields(
    model: type[models.Model],
    exclude: Sequence[str] = (),
) -> list[str]:
    """Every field a user may edit, in declaration order."""
    opts = model._meta
    names = [
        field.name
        for field in [*opts.fields, *opts.many_to_many]
        if field.editable and not field.auto_created
    ]

    return [name for name in names if name not in exclude]


def flatten_fieldsets(fieldsets: Any) -> list[str]:
    names: list[str] = []

    for _title, options in fieldsets or ():
        for entry in options.get("fields", ()):
            if isinstance(entry, (list, tuple)):
                names.extend(entry)
            else:
                names.append(entry)

    return names


def without_fields(fieldsets: Any, names: set[str]) -> Any:
    """``fieldsets`` with ``names`` taken out, rows and sections kept."""
    result = []

    for title, options in fieldsets or ():
        entries = []

        for entry in options.get("fields", ()):
            if isinstance(entry, (list, tuple)):
                row = tuple(name for name in entry if name not in names)

                if row:
                    entries.append(row if len(row) > 1 else row[0])
            elif entry not in names:
                entries.append(entry)

        if entries:
            result.append((title, {**options, "fields": tuple(entries)}))

    return tuple(result)


def sections_from_fieldsets(
    fieldsets: Any,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Fieldsets, admin style, as form sections and field layout.

    A tuple inside ``fields`` shares one row between its fields; the
    ``collapse`` class starts a section closed and ``tab`` draws it as a
    tab of its own.
    """
    sections: list[dict[str, Any]] = []
    layout: dict[str, dict[str, Any]] = {}
    used: set[str] = set()
    position = 0

    for index, (title, options) in enumerate(fieldsets):
        classes = tuple(options.get("classes", ()))
        name = options.get("name") or (
            slugify(force_str(title))
            if title
            else ("general" if index == 0 else f"section-{index}")
        )

        while name in used:
            name = f"{name}-{index}"

        used.add(name)
        sections.append(
            {
                "name": name,
                # Lazy, like every title here: read in the language of
                # the request that sends the schema, not the first one.
                "title": title or "",
                "description": options.get("description", ""),
                "position": index,
                "collapsed": "collapse" in classes,
                "tab": "tab" in classes,
            }
        )

        for entry in options.get("fields", ()):
            row = (
                tuple(entry) if isinstance(entry, (list, tuple)) else (entry,)
            )
            width = max(3, 12 // len(row))

            for field_name in row:
                layout[field_name] = {
                    "section": name,
                    "position": position,
                    "width": width,
                }
                position += 1

    return sections, layout


def automatic_layout(
    model: type[models.Model],
    fields: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Two short fields to a row, long ones on a row of their own."""
    layout: dict[str, dict[str, Any]] = {}

    for position, name in enumerate(fields):
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            field = None

        wide = isinstance(field, (models.TextField, models.ManyToManyField))
        layout[name] = {"position": position, "width": 12 if wide else 6}

    return layout


def resolve_display_callable(
    name: str,
    source: Any,
    model: type[models.Model],
) -> Callable[[Any], Any] | None:
    """A read-only value computed by the resource, or by the model."""
    if source is not None and callable(getattr(type(source), name, None)):
        return getattr(source, name)

    if hasattr(model, name):
        return model_attribute_reader(model, name)

    return None


def make_display_getter(
    function: Callable[[Any], Any],
) -> Callable[[Any, Any], Any]:
    def getter(serializer: Any, instance: Any) -> Any:
        # Nothing to compute on a record that does not exist yet.
        if not isinstance(instance, models.Model) or instance.pk is None:
            return None

        return plain_value(function(instance))

    return getter


def build_form_serializer(
    model: type[models.Model],
    *,
    fields: Sequence[str],
    readonly_fields: Sequence[str] = (),
    fieldsets: Any = None,
    overrides: dict[str, dict[str, Any]] | None = None,
    extra_kwargs: dict[str, dict[str, Any]] | None = None,
    extra_fields: dict[str, Any] | None = None,
    source: Any = None,
    name: str | None = None,
) -> type[FormModelSerializer]:
    """A ``FormModelSerializer`` for ``fields`` of ``model``.

    ``extra_fields`` are questions the form asks that are not the
    model's: write only, and taken out before the record is saved.
    """
    opts = model._meta
    model_fields = {field.name for field in [*opts.fields, *opts.many_to_many]}

    declared: dict[str, Any] = {}
    methods: dict[str, Any] = {}
    meta_fields = [opts.pk.name]
    read_only = [
        field_name
        for field_name in readonly_fields
        if field_name in model_fields
    ]

    extra_fields = dict(extra_fields or {})

    for field_name, field in extra_fields.items():
        if field_name in model_fields:
            raise ImproperlyConfigured(
                f"form_extra_fields of {model.__name__}: '{field_name}' "
                f"is a field of the model already."
            )

        if not isinstance(field, serializers.Field):
            raise ImproperlyConfigured(
                f"form_extra_fields of {model.__name__}: '{field_name}' "
                f"must be a DRF serializer field."
            )

    if not fieldsets:
        # Laid out by nobody: after the model's own fields.
        fields = [
            *fields,
            *(name for name in extra_fields if name not in fields),
        ]

    for field_name in fields:
        if field_name in meta_fields:
            continue

        meta_fields.append(field_name)

        if field_name in model_fields:
            continue

        if field_name in extra_fields:
            # Built again, write only: DRF copies a declared field from
            # its arguments for each serializer, so the flag must be one.
            field = extra_fields[field_name]
            declared[field_name] = type(field)(
                *deepcopy(field._args),
                **{**deepcopy(field._kwargs), "write_only": True},
            )
            continue

        function = resolve_display_callable(field_name, source, model)

        if function is None or field_name not in readonly_fields:
            raise ImproperlyConfigured(
                f"'{field_name}' is not a field of {model.__name__}. "
                f"A computed value must be listed in readonly_fields "
                f"and be a method of the resource or the model."
            )

        label = getattr(function, "short_description", None)
        declared[field_name] = serializers.SerializerMethodField(
            label=label or None
        )
        methods[f"get_{field_name}"] = make_display_getter(function)

    if fieldsets:
        sections, layout = sections_from_fieldsets(fieldsets)
    else:
        sections = [
            {"name": "general", "title": "", "description": "", "position": 0}
        ]
        layout = automatic_layout(model, fields)

    merged: dict[str, dict[str, Any]] = {
        field_name: dict(entry) for field_name, entry in layout.items()
    }

    for field_name, entry in (overrides or {}).items():
        merged.setdefault(field_name, {}).update(entry)

    # Only for fields the serializer actually builds: DRF raises on an
    # extra_kwargs entry naming something that is not there, and a typo
    # should say so rather than take the whole form down on first use.
    options = {
        field_name: dict(entry)
        for field_name, entry in (extra_kwargs or {}).items()
        if field_name in meta_fields and field_name not in declared
    }

    meta = type(
        "Meta",
        (),
        {
            "model": model,
            "fields": tuple(meta_fields),
            "read_only_fields": tuple(read_only),
            "extra_kwargs": options,
        },
    )

    attributes = {
        **declared,
        **methods,
        "Meta": meta,
        "form_sections": tuple(sections),
        "form_overrides": merged,
        "generic_extra_fields": tuple(
            field_name for field_name in extra_fields if field_name in declared
        ),
        "__module__": __name__,
    }

    return type(
        name or f"{model.__name__}FormSerializer",
        (FormModelSerializer,),
        attributes,
    )

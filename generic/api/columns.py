"""Column declarations.

A column is declared once, on the serializer field, and drives three
things at the same time:

* the JSON column configuration handed to DataTables,
* the server side filtering whitelist,
* the export header and ordering.

Declaring it in a single place is what keeps the table honest: the client
can only filter or order on something a serializer field opted into, so a
client supplied ORM path can never reach the queryset.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any, Callable, Iterable

from django.urls import reverse
from django.utils.encoding import force_str
from rest_framework import serializers

from generic.api.files import FileValueMixin, file_name
from generic.api.tags import TagStyle, tag_items, tags_text

#: Filter engines understood by both the client and
#: :mod:`generic.api.filters`.
FILTER_TEXT = "text"
FILTER_INTEGER = "integer"
FILTER_FLOAT = "float"
FILTER_DATE = "date"
FILTER_DATETIME = "datetime"
FILTER_BOOLEAN = "boolean"
FILTER_MULTISELECT = "multiselect"

FILTER_TYPES = frozenset(
    {
        FILTER_TEXT,
        FILTER_INTEGER,
        FILTER_FLOAT,
        FILTER_DATE,
        FILTER_DATETIME,
        FILTER_BOOLEAN,
        FILTER_MULTISELECT,
    }
)

#: Display types the client knows how to render. ``link`` renders an
#: anchor, ``tags`` coloured labels, ``file`` a stored file's name
#: linking to its download and ``icons`` a list of ``{"icon", "url",
#: "label"}`` as icons one clicks; all still filter as text unless the
#: column forces another filter.
DISPLAY_TYPES = FILTER_TYPES | {"link", "tags", "file", "icons"}


def prettify_field_name(field_name: str) -> str:
    """Turn ``time_spent`` into ``Time spent``."""
    return field_name.replace("_", " ").capitalize()


def json_safe(value: Any) -> Any:
    """A value the table configuration can carry to the client.

    The configuration is rendered into the page as JSON, so a field
    whose choices are objects - a time zone, an enum of a library's own
    - would break the whole page rather than that one column. Their
    text is what the client sends back anyway.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    return force_str(value)


@dataclasses.dataclass(frozen=True)
class FilterSpec:
    """How one public column name maps onto the ORM.

    ``type`` is the filter engine, shared with the client. ``value_type``
    is how the incoming value is coerced before it reaches the ORM, and
    is what separates a ``DateField`` from a ``DateTimeField`` behind the
    same ``date`` engine.

    ``many`` marks a path crossing a many-valued relation. Filtering on
    it directly would repeat a row once per matching related value, so
    the backend matches through a subquery on the primary key instead.
    """

    field: str
    type: str
    value_type: str = "string"
    many: bool = False

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class ColumnOptions:
    """Presentation and filtering options of a single column.

    Frozen on purpose: a subclass adjusts inherited columns through
    ``datatable_overrides``, which rebuilds the options with
    :func:`dataclasses.replace`. An unknown key therefore raises instead
    of being silently ignored, which is how column typos used to survive
    all the way to production.
    """

    title: str | None = None
    #: Include the column in the table at all.
    column: bool = True
    #: Start hidden; the column selector can still reveal it.
    visible: bool = True
    position: int = 0
    #: Expose a per column filter control.
    filterable: bool = True
    orderable: bool = True
    #: Include in the global search box.
    searchable: bool = True
    exportable: bool = True

    #: Force a filter engine instead of inferring it from the field.
    filter_type: str | None = None
    #: ORM path to filter on, when it differs from the public name.
    filter_field: str | None = None
    #: The filter path crosses a many-valued relation.
    filter_many: bool = False
    #: ORM path to order on, when it differs from the public name.
    order_field: str | None = None
    #: ORM path for the global search, defaults to ``filter_field``.
    search_field: str | None = None
    #: ``integer`` coerces multiselect values before they hit the ORM.
    value_type: str | None = None
    #: Offer the column's values, with their counts, in the filter
    #: editor (the ``facets`` endpoint). ``None``: choices, relations,
    #: booleans, numbers and dates do; free text does not.
    facetable: bool | None = None

    #: Force a renderer instead of inferring it from the field.
    display_type: str | None = None
    link_url: str | None = None
    link_field: str | None = None
    link_target: str | None = None
    #: For a tags column: each tag links here, ``{id}`` being its key.
    tag_url: str | None = None

    #: Named route returning Select2 results, for multiselect filters.
    autocomplete_route: str | None = None
    #: Literal URL, when the route is not reversible.
    autocomplete_url: str | None = None
    placeholder: str | None = None
    minimum_input_length: int | None = None

    width: str | None = None
    class_name: str | None = None
    step: float | None = None

    def replace(self, **overrides: Any) -> "ColumnOptions":
        try:
            return dataclasses.replace(self, **overrides)
        except TypeError as error:
            known = ", ".join(
                sorted(field.name for field in dataclasses.fields(self))
            )
            raise TypeError(
                f"Unknown datatable column option. Known options: " f"{known}."
            ) from error


class DataTableFieldMixin:
    """Attach column metadata to a DRF serializer field.

    Mixed into a serializer field so that one declaration describes both
    the payload and the table::

        temps_passe = IntegerColumn(title="T.P.", read_only=True)
    """

    #: Filter engine and renderer used when the column does not force
    #: one. Concrete column classes override it.
    datatable_type: str = FILTER_TEXT

    #: How values are coerced before reaching the ORM. Mostly mirrors
    #: ``datatable_type``, except for datetimes which filter through the
    #: ``date`` engine but compare against day boundaries.
    datatable_value_type: str = "string"

    #: Whether an export has to go through ``to_representation`` to get
    #: a writable value. True for a column whose raw attribute is not a
    #: plain value - a related manager, for instance.
    export_representation: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        option_names = {
            field.name for field in dataclasses.fields(ColumnOptions)
        }
        option_values = {
            name: kwargs.pop(name)
            for name in list(kwargs)
            if name in option_names
        }

        self.datatable = ColumnOptions(**option_values)

        super().__init__(*args, **kwargs)

    # -- resolution ---------------------------------------------------

    def resolve_filter_type(self, options: ColumnOptions) -> str:
        return options.filter_type or self.datatable_type

    def resolve_display_type(self, options: ColumnOptions) -> str:
        return options.display_type or self.datatable_type

    def resolve_facetable(self, options: ColumnOptions) -> bool:
        """Whether the filter editor may list this column's values."""
        if options.facetable is not None:
            return bool(options.facetable)

        return self.resolve_filter_type(options) != FILTER_TEXT

    def resolve_title(
        self,
        field_name: str,
        options: ColumnOptions,
    ) -> str:
        if options.title:
            return force_str(options.title)

        label = getattr(self, "label", None)

        if label:
            return force_str(label)

        return prettify_field_name(field_name)

    def resolve_autocomplete_url(
        self,
        options: ColumnOptions,
    ) -> str | None:
        if options.autocomplete_url:
            return options.autocomplete_url

        if options.autocomplete_route:
            return reverse(options.autocomplete_route)

        return None

    # -- output -------------------------------------------------------

    def build_column(
        self,
        field_name: str,
        options: ColumnOptions | None = None,
    ) -> dict[str, Any]:
        """Build the JSON column configuration for the client."""
        options = options or self.datatable

        column: dict[str, Any] = {
            "data": field_name,
            "name": options.order_field or field_name,
            "title": self.resolve_title(field_name, options),
            "type": self.resolve_display_type(options),
            "filterKey": field_name,
            "searchable": options.filterable,
            "orderable": options.orderable,
        }

        # Sent when forced, or when the display type no longer says it:
        # a date column drawn as a link would otherwise be filtered as
        # text, with operators its engine refuses. In the common case the
        # client keeps inferring the filter from the display type.
        filter_type = self.resolve_filter_type(options)

        if options.filter_type or filter_type != column["type"]:
            column["filterType"] = filter_type

        if not options.visible:
            column["visible"] = False

        # A choice field is the commonest multiselect column. Sending
        # its choices lets the client build the dropdown directly,
        # instead of needing an autocomplete route for a fixed list.
        choices = getattr(self, "choices", None)

        if choices:
            column["choices"] = [
                {"value": json_safe(value), "label": force_str(label)}
                for value, label in choices.items()
            ]

        optional = {
            "linkUrl": options.link_url,
            "linkField": options.link_field,
            "linkTarget": options.link_target,
            "tagUrl": options.tag_url,
            "autocompleteUrl": self.resolve_autocomplete_url(options),
            "placeholder": options.placeholder,
            "minimumInputLength": options.minimum_input_length,
            "width": options.width,
            "className": options.class_name,
            "step": options.step,
        }

        column.update(
            {
                key: value
                for key, value in optional.items()
                if value is not None
            }
        )

        if not options.exportable:
            column["exportable"] = False

        if options.filterable and self.resolve_facetable(options):
            column["facets"] = True

        # Several values per row: the editor offers "has all of".
        if options.filterable and options.filter_many:
            column["filterMany"] = True

        return column

    def build_filter(
        self,
        field_name: str,
        options: ColumnOptions | None = None,
    ) -> FilterSpec:
        """Build the server side filtering entry for this column."""
        options = options or self.datatable

        return FilterSpec(
            field=options.filter_field or field_name,
            type=self.resolve_filter_type(options),
            value_type=(options.value_type or self.datatable_value_type),
            many=options.filter_many,
        )

    def build_search_field(
        self,
        field_name: str,
        options: ColumnOptions | None = None,
    ) -> str | None:
        """ORM path the global search box should look into."""
        options = options or self.datatable

        if not options.searchable:
            return None

        # An explicit search path is trusted as is: that is how a
        # relation column searches the related model's text.
        if options.search_field:
            return options.search_field

        # Otherwise only text-ish columns take part in a free text
        # search; ``icontains`` on a numeric or date column errors out
        # on PostgreSQL.
        if self.resolve_filter_type(options) not in {
            FILTER_TEXT,
            FILTER_MULTISELECT,
        }:
            return None

        return options.filter_field or field_name


class CharColumn(DataTableFieldMixin, serializers.CharField):
    datatable_type = FILTER_TEXT
    datatable_value_type = "string"


class IntegerColumn(DataTableFieldMixin, serializers.IntegerField):
    datatable_type = FILTER_INTEGER
    datatable_value_type = "integer"


class FloatColumn(DataTableFieldMixin, serializers.FloatField):
    datatable_type = FILTER_FLOAT
    datatable_value_type = "float"


class DecimalColumn(DataTableFieldMixin, serializers.DecimalField):
    datatable_type = FILTER_FLOAT
    datatable_value_type = "decimal"


class BooleanColumn(DataTableFieldMixin, serializers.BooleanField):
    datatable_type = FILTER_BOOLEAN
    datatable_value_type = "boolean"


class DateColumn(DataTableFieldMixin, serializers.DateField):
    datatable_type = FILTER_DATE
    datatable_value_type = "date"


class DateTimeColumn(DataTableFieldMixin, serializers.DateTimeField):
    # Declared as ``date``: the client renders and filters it by day,
    # which is what users of these tables expect. ``value_type`` is what
    # tells the filter engine to compare against day boundaries in the
    # active timezone rather than against a bare date.
    datatable_type = FILTER_DATE
    datatable_value_type = "datetime"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("format", table_datetime_format())
        super().__init__(*args, **kwargs)


def table_datetime_format() -> str:
    """How a table's date-and-time cells travel.

    ISO in the active time zone unless ``TABLE_DATETIME_FORMAT`` says
    otherwise: the row keeps a value a control can take back and a
    filter can compare, and the browser draws it in the reader's own
    language (``datatables/columns.js``). A strftime format there sends
    that text instead, drawn as it is, in every language.
    """
    from rest_framework.settings import ISO_8601

    from generic.conf import generic_settings

    return generic_settings.TABLE_DATETIME_FORMAT or ISO_8601


class ChoiceColumn(DataTableFieldMixin, serializers.ChoiceField):
    datatable_type = FILTER_MULTISELECT
    datatable_value_type = "string"


class MethodColumn(
    DataTableFieldMixin,
    serializers.SerializerMethodField,
):
    """Computed column.

    It is read only and cannot be filtered or ordered unless the
    declaration points ``filter_field`` and ``order_field`` at a real
    annotation.
    """

    datatable_type = FILTER_TEXT

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("filterable", False)
        kwargs.setdefault("orderable", False)
        kwargs.setdefault("searchable", False)
        super().__init__(*args, **kwargs)


class ManyRelatedColumn(DataTableFieldMixin, serializers.Field):
    """A many-to-many shown as its related labels, comma separated.

    Filtering it is a multiselect over the related primary keys, matched
    through a subquery so a row is never listed twice; see
    :class:`FilterSpec`. It cannot be ordered: there is no single value
    to order on.
    """

    datatable_type = FILTER_TEXT
    export_representation = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("read_only", True)
        kwargs.setdefault("orderable", False)
        kwargs.setdefault("filter_many", True)
        super().__init__(*args, **kwargs)

    def to_representation(self, value: Any) -> str:
        items = value.all() if hasattr(value, "all") else value or ()

        return ", ".join(force_str(item) for item in items)


class TagsColumn(DataTableFieldMixin, serializers.Field):
    """One or several values drawn as coloured tags.

    The value may be a related manager, a list, a single record or a
    choice; each item becomes ``{"label", "id", "color",
    "background", "title"}`` through ``tag_style``::

        tags = TagsColumn(
            tag_style=TagStyle(background="background", color="color"),
            tag_url="/tags/{id}/",
            filter_type="multiselect",
            filter_field="tags",
            filter_many=True,
            autocomplete_route="api:tag-autocomplete",
        )

    ``reader`` computes the items from the value instead - from the
    whole row, with ``source="*"``. ``choices`` maps stored values to
    labels, and feeds a multiselect filter like a choice column's.
    Exports get the labels, comma separated.
    """

    datatable_type = FILTER_TEXT
    export_representation = True

    def __init__(
        self,
        *args: Any,
        tag_style: TagStyle | None = None,
        reader: Callable[[Any], Any] | None = None,
        choices: Any = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("read_only", True)
        # Not "style": DRF fields already use that name.
        self.tag_style = tag_style or TagStyle()
        self.reader = reader
        #: Read by build_column, which sends them to the client.
        self.choices = dict(choices or {})
        super().__init__(*args, **kwargs)

    def __deepcopy__(self, memo: dict) -> "TagsColumn":
        # DRF copies every field per serializer instance, arguments
        # included. The reader is often a bound method of a resource and
        # the style may hold callables: shared, not copied.
        shared = ("reader", "tag_style", "validators")
        arguments = self._kwargs.items()  # type: ignore[attr-defined]
        kwargs = {
            key: value if key in shared else copy.deepcopy(value, memo)
            for key, value in arguments
        }

        return self.__class__(
            *copy.deepcopy(self._args, memo),  # type: ignore[attr-defined]
            **kwargs,
        )

    def resolve_display_type(self, options: ColumnOptions) -> str:
        return options.display_type or "tags"

    def to_representation(self, value: Any) -> list[dict[str, Any]]:
        if self.reader is not None:
            value = self.reader(value)

        return self.tag_style.describe_all(tag_items(value), self.choices)

    def to_export(self, value: Any) -> str:
        return tags_text(self.to_representation(value))


class FileColumn(FileValueMixin, DataTableFieldMixin, serializers.Field):
    """A stored file: ``{"name", "url", "size"}``, its name in exports.

    The cell links the name to the download endpoint the serializer
    context names (:data:`generic.api.files.FILE_URL`). ``size`` stays
    ``null``: asking the storage for it would be one request per row on
    a remote storage. Ordered by the stored name; not filtered or
    searched, since that name is a path of the storage's own.
    """

    datatable_type = FILTER_TEXT
    describe_size = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("read_only", True)
        kwargs.setdefault("filterable", False)
        kwargs.setdefault("searchable", False)
        super().__init__(*args, **kwargs)

    def resolve_display_type(self, options: ColumnOptions) -> str:
        return options.display_type or "file"

    def to_export(self, value: Any) -> str | None:
        return file_name(value) or None


def iter_datatable_fields(
    fields: Iterable[tuple[str, serializers.Field]],
    overrides: dict[str, dict[str, Any]],
) -> list[tuple[str, DataTableFieldMixin, ColumnOptions]]:
    """Select the table aware fields and apply subclass overrides.

    Ordered by ``position`` then by declaration order, which lets a
    subclass insert a column without redeclaring the inherited ones.
    """
    entries: list[tuple[int, str, DataTableFieldMixin, ColumnOptions]] = []

    for index, (field_name, field) in enumerate(fields):
        if not isinstance(field, DataTableFieldMixin):
            continue

        options = field.datatable

        if field_name in overrides:
            options = options.replace(**overrides[field_name])

        if not options.column:
            continue

        entries.append((index, field_name, field, options))

    entries.sort(key=lambda entry: (entry[3].position, entry[0]))

    return [
        (field_name, field, options)
        for _, field_name, field, options in entries
    ]

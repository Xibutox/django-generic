# Data tables

## A minimal table

```python
from generic.api import CharColumn, DataTableModelSerializer, \
    DataTableViewSet, IntegerColumn


class BookSerializer(DataTableModelSerializer):
    title = CharColumn(title="Title")
    pages = IntegerColumn(title="Pages")

    class Meta:
        model = Book
        fields = ("id", "title", "pages")


class BookViewSet(DataTableViewSet):
    serializer_class = BookSerializer
    queryset = Book.objects.all()
    export_file_name = "books"
```

Registered on a router, that endpoint supports pagination, per-column
filters, a global search, ordering, and `export` / `export-csv`.

## Column types

| Class | Filter engine | Notes |
| --- | --- | --- |
| `CharColumn` | `text` | Takes part in the global search |
| `IntegerColumn` | `integer` | Rejects fractional filter values |
| `FloatColumn` | `float` | |
| `DecimalColumn` | `float` | Needs `max_digits`, `decimal_places` |
| `BooleanColumn` | `boolean` | |
| `DateColumn` | `date` | Compares dates directly |
| `DateTimeColumn` | `date` | Compares against day boundaries |
| `ChoiceColumn` | `multiselect` | |
| `MethodColumn` | — | Computed; not filterable or orderable |
| `ManyRelatedColumn` | `text` | A many-to-many as its labels, comma separated; not orderable |
| `TagsColumn` | `text`, or as forced | One or several values as coloured tags — see below |

`DateTimeColumn` filters through the `date` engine on purpose: users of
these tables think in days, not timestamps. `value_type` is what tells
the engine to compare `2020-03-15` against the whole of that day in the
active timezone.

## Column options

Every option below is accepted by any column class.

### Presentation

| Option | Default | Meaning |
| --- | --- | --- |
| `title` | field label | Header text |
| `visible` | `True` | `False` starts hidden but selectable |
| `column` | `True` | `False` removes it from the table entirely |
| `position` | `0` | Sort key; ties keep declaration order |
| `width` | auto | CSS width |
| `class_name` | — | Extra CSS class on the cells |
| `display_type` | inferred | `link` renders an anchor, `tags` coloured labels, `icons` a list of `{"icon", "url", "label"}` as icons one clicks |
| `link_url` | — | `"/books/{id}/"`, interpolated from the row |
| `link_field` | — | Row field holding the URL |
| `link_target` | `_self` | |
| `tag_url` | — | For a tags column: `"/tags/{id}/"`, interpolated from each tag |

### Filtering and ordering

| Option | Default | Meaning |
| --- | --- | --- |
| `filterable` | `True` | Expose a per-column filter |
| `orderable` | `True` | Allow ordering |
| `searchable` | `True` | Include in the global search |
| `exportable` | `True` | Include in exports |
| `filter_type` | inferred | Force an engine |
| `filter_field` | field name | ORM path to filter on |
| `order_field` | field name | ORM path to order on |
| `search_field` | `filter_field` | ORM path for the global search |
| `value_type` | per class | Coercion; `integer` for multiselect ids |
| `filter_many` | `False` | The path crosses a many-valued relation: matched through a subquery, and "has all of" is offered |
| `facetable` | auto | Offer the column's values with their counts in the filter editor; choices, relations, booleans, numbers and dates do by default, free text does not |

### Multiselect dropdowns

| Option | Meaning |
| --- | --- |
| `autocomplete_route` | Named route returning Select2 results |
| `autocomplete_url` | Literal URL, when the route is not reversible |
| `placeholder` | Dropdown placeholder |
| `minimum_input_length` | Characters before searching |

## Tag columns

A column holding one or several labels, each with its own colours, read
from the data:

```python
from generic.api import TagsColumn, TagStyle


class TicketSerializer(DataTableModelSerializer):
    # A many-to-many: each Tag record holds a colour and a background.
    tags = TagsColumn(
        tag_style=TagStyle(color="color", background="background"),
        tag_url="/tags/{id}/",
        filter_type="multiselect",
        filter_many=True,
        autocomplete_route="api:tag-autocomplete",
        orderable=False,
    )
    # A choice: colours by value; the choices also feed the filter.
    status = TagsColumn(
        tag_style=TagStyle(colors={
            "open": "#2563eb",
            "urgent": {"background": "#dc2626", "color": "#ffffff"},
        }),
        choices=Ticket.Status.choices,
        filter_type="multiselect",
    )
    # Computed from the whole row.
    flags = TagsColumn(
        source="*",
        reader=lambda ticket: [
            {"label": "Late", "color": "#b45309"} if ticket.is_late else None,
            {"label": "VIP", "background": "#7c3aed"} if ticket.vip else None,
        ],
        filterable=False,
        orderable=False,
    )
```

Each tag travels as `{"label", "id", "color", "background", "title"}`,
keys left out when empty. The value may be a related manager, a list,
one record, one choice, or dicts already in that shape; `None` items
are skipped. With **one colour** the tag is tinted, and follows the
theme; with **a background** it is drawn exactly, the text in `color`
or in black or white, whichever reads.

| `TagStyle` option | Meaning |
| --- | --- |
| `label`, `color`, `background`, `title` | Attribute names of the value, or callables taking it |
| `colors` | Fixed colours by value or label: a colour, or `{"color", "background"}` |
| `default` | The colour of a tag nothing else colours |

Colours are checked against a strict CSS colour pattern on the server
and again in the browser; anything else is dropped. Exports and copies
write the labels, comma separated. On a resource, `tag_fields` builds
these columns for you — see [Sites](sites.md#tags).

## Columns whose ORM path differs

A column showing a related value needs three things: where to read it,
where to filter it, where to order it.

```python
author = CharColumn(
    source="author.name",        # where to read
    filter_field="author__name", # where to filter
    order_field="author__name",  # where to order
    title="Author",
    read_only=True,
)
```

The public name stays `author`; the ORM path is never exposed.

## Adjusting inherited columns

A subclass changes an inherited column without redeclaring it:

```python
class TimeTrackingSerializer(SubtasksSerializer):
    datatable_overrides = {
        "colonne": {"visible": False},
        "pages": {"position": -10},
    }
```

Overrides merge along the MRO, so a subclass states only what it
changes. An unknown option raises `TypeError` at build time rather than
being silently ignored.

## Aggregated tables

When a row is not a model instance — a grouped, annotated queryset —
use `AggregatedDataTableViewSet` with a plain `DataTableSerializer`:

```python
class AuthorSummarySerializer(DataTableSerializer):
    author = CharColumn(title="Author", read_only=True)
    book_count = IntegerColumn(title="Books", read_only=True)


class AuthorSummaryViewSet(AggregatedDataTableViewSet):
    serializer_class = AuthorSummarySerializer
    model = Author
    base_exclusions = {"is_active": False}
    filter_parameters = {"name": "name__icontains"}
    ordering = ("author",)

    def get_values(self):
        return {"author": F("name")}

    def get_aggregations(self):
        return {"book_count": Count("books")}
```

The pipeline is: base queryset → `apply_filters` → `annotate_extra` →
`values(*group_by_fields).annotate(**values, **aggregations)` →
`order_by(*ordering)`, then the filter backends.

Advanced filters work on aggregates too, because they are applied after
the annotation.

## Rows that are not in the database

When the rows are a list of dicts — an external API's answer — use
`RowsDataTableViewSet` with a plain `DataTableSerializer` and return
them from `get_rows()`. Filters, search, ordering, paging, facets and
exports work as above, worked out in Python. On a site, a
`DataResource` declares the same thing and adds the pages: see
[Rows from elsewhere](data.md).

## The wire protocol

Request parameters:

| Parameter | Meaning |
| --- | --- |
| `draw` | Echoed back as an integer |
| `start`, `length` | Offset and page size; `length=-1` means all |
| `search[value]` | Global search term |
| `columns[i][data]` | Public column name at index `i` |
| `order[i][column]`, `order[i][dir]` | Ordering |
| `filters` | JSON filter tree, see below |
| `advanced_filters` | The older flat payload, still accepted |
| `ordering` | `-title,pages` — a non-DataTables alternative |

### The filter tree

Conditions, grouped with `all` or `any`, groups nested up to four
levels, at most 50 conditions:

```json
{
  "match": "all",
  "conditions": [
    {"column": "genre", "operator": "any_of", "value": ["essay", "poetry"]},
    {"column": "released_at", "operator": "last_days", "value": 90},
    {"match": "any", "conditions": [
      {"column": "pages", "operator": "between", "value": {"from": 100, "to": 300}},
      {"column": "rating", "operator": "empty"}
    ]}
  ]
}
```

Several conditions may target one column (`pages > 100` and
`pages < 300`). A condition whose value is empty is ignored, as an empty
control is; operators that take no value are not.

| Engine | Operators | Value |
| --- | --- | --- |
| `text` | `contains`, `not_contains`, `equals`, `not_equals`, `starts_with`, `not_starts_with`, `ends_with`, `not_ends_with` | a string, or a list: any of them matches (a negated operator: none may) |
| `integer`, `float` | `equals`, `not_equals`, `gt`, `gte`, `lt`, `lte` | a number |
| | `between` | `{"from", "to"}` or `[low, high]`, either side optional |
| `date`, `datetime` | `on`, `not_on`, `before`, `after`, `on_or_before`, `on_or_after` | `YYYY-MM-DD`; a datetime is compared by whole days in the active timezone |
| | `between` | `{"from", "to"}`, both required |
| | `today`, `yesterday`, `tomorrow`, `this_week`, `last_week`, `next_week`, `this_month`, `last_month`, `next_month`, `this_quarter`, `last_quarter`, `next_quarter`, `this_year`, `last_year`, `next_year` | none |
| | `last_days`, `next_days` (today included), `older_than_days` | a number of days |
| `boolean` | `is_true`, `is_false` | none |
| `multiselect` | `any_of`, `none_of`, `all_of` (several values on one row, many-valued columns) | a list of keys |
| every engine | `empty`, `not_empty` | none — for text, an empty string is empty too |

Across a many-valued relation every condition goes through a subquery on
the primary key: a row is never listed twice, and a negation means *has
none*. Every name is resolved through the column declarations; anything
else is refused with a 400.

The older `advanced_filters` payload — one condition per column, all
required — is read as a tree. Its operator names still work: `exact`,
`not_exact`, `starts`, `ends`, `greater_than`, `greater_or_equal`,
`less_than`, `less_or_equal`, `include`, `exclude`, and `after` /
`before` with `{"from"}` / `{"to"}`. Errors in it keep the
`advanced_filters` key.

### Facets

`GET <endpoint>/facets/?column=genre` answers with the values of one
column among the rows the table would show — the search, `_related` and
every *other* condition applied — with their counts:

```json
{"column": "genre", "kind": "values", "more": false,
 "values": [{"value": "fiction", "label": "Fiction", "count": 2},
            {"value": null, "label": "Empty", "count": 1}]}
```

A number or a date answers with its range: `{"kind": "range", "min",
"max", "empty"}`. `q` searches the labels — for a relation, the related
record's label — and `ids=1,2` asks for the labels of known values. A
tag column adds each value's `tag`, colours included. Only columns that
are filterable and facetable answer; an `AggregatedDataTableViewSet` has
no facets (`facets_enabled = False`).

Response:

```json
{
  "draw": 3,
  "recordsTotal": 1200,
  "recordsFiltered": 42,
  "data": [ … ]
}
```

`recordsTotal` costs a second `COUNT` per draw. On a table large enough
for that to matter, set `table_total_count = False` on the viewset and
the two counts coincide.

## Errors

With `?format=datatables`, a rejected request is rewritten to the only
error shape DataTables surfaces:

```json
{"draw": 3, "recordsTotal": 0, "recordsFiltered": 0,
 "data": [], "error": "Filtering is not allowed on publisher__name."}
```

Without that format, the ordinary DRF error body is returned. Without
the rewrite a rejected filter shows an empty table and says nothing.

## Exports

Both actions stream the **filtered** queryset, ignoring pagination:

- `GET /api/books/export/` — Excel, dates written as real dates
- `GET /api/books/export-csv/` — CSV, semicolon-separated, UTF-8 with a BOM

`?columns=title,pages` narrows the export. Unknown names are dropped
rather than rejected, since a client may hold a stale column list after
a deployment.

`EXPORT_MAX_ROWS` (default 250 000) refuses an oversized export instead
of timing out.

## Autocomplete

```python
class AuthorAutocomplete(AutocompleteView):
    queryset = Author.objects.all()
    search_fields = ("name", "email")
    label_field = "name"
```

`search_fields` is a fixed whitelist: the client only ever sends a term,
never a field to search in. The response is Select2-shaped, and
`pagination.more` is computed by fetching one extra row rather than
paying for a `COUNT`.

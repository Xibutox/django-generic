# Rows from elsewhere

Not everything worth a table is in the database. An external API
answers with a list of dicts; a file, a computation, another system
does too. A `DataResource` gives those rows what a model gets — a list
page and a page per row — and nothing to write: they are read, not
edited, so there is no form, no add and no delete.

```python
# myapp/resources.py
import datetime

from django.utils.translation import gettext_lazy as _

from generic.api import CharColumn, FloatColumn, TagsColumn
from generic.sites import DataResource, TagStyle, register_data

from myapp import statuspage


@register_data
class ServiceResource(DataResource):
    name = "services"                     # data/services/
    label = _("service")
    label_plural = _("services")
    icon = "cloud"
    group = _("Support")
    permission = "myapp.view_ticket"      # None: any signed-in user

    key = "id"                            # data/services/<id>/
    ordering = ("name",)
    columns = {
        "name": CharColumn(title=_("Service")),
        "status": TagsColumn(
            title=_("Status"),
            choices={"up": _("Operational"), "down": _("Outage")},
            tag_style=TagStyle(colors={"up": "#16a34a", "down": "#dc2626"}),
            filter_type="multiselect",
        ),
        "uptime": FloatColumn(title=_("Uptime (%)")),
        "checked_at": datetime.datetime,  # a type is enough
    }

    def get_rows(self, request):
        return statuspage.services()      # [{"id": ..., "name": ...}, ...]
```

That is the whole declaration. It gives:

- **a list page** at `data/services/`, in the navigation and on the
  dashboard for whoever has the permission: the columns, the search box,
  the filters of every kind with their values and counts, the row of
  fields under the headers, sorting, paging, saved layouts, the Excel
  and CSV exports, a link from the first column to the row's page;
- **a page per row** at `data/services/<key>/`, laid out as a record's
  summary page: figures at the top, sections of values drawn by type —
  a date as a date, a status as its coloured tag, an address as a link;
- **an endpoint** at `api/data/services/`, speaking the same protocol
  as a model's table: `facets/`, `export/`, `export-csv/`, and
  `<key>/summary/` for one row.

The example's *External services* (`example/external.py`,
`ServiceResource` in `example/resources.py`) is a status API's answer
served this way, with each service's incidents as a tab of its page —
see [Rows of other resources](#rows-of-other-resources).

## The rows

`get_rows(request)` returns every row: dicts, or objects — a key of a
dict or an attribute of an object is read the same way. It is called on
every request the table makes, each draw, sort, filter and export, so
**cache what is slow to fetch**. The example keeps the API's answer a
minute:

```python
def services():
    return cache.get_or_set("myapp.services", fetch_services, 60)
```

Nothing has to be converted first. What an API sends as text is read as
what its column says: `"2026-09-25T08:15:00Z"` filters and shows as a
date and time — in the active time zone and the reader's language, as
a model's timestamps — `"99.95"` as a number, `"yes"` as a boolean. A list is
several values, as a many-to-many is — `"regions": ["eu", "us"]` —
filtered with *is any of*, *has all of*, *is none of*. A missing key
and `null` are *empty*.

A nested value is reached with `__`, like an ORM path: a column with
`filter_field="owner__name"` filters on `row["owner"]["name"]`; its
`source="owner.name"` reads it.

`get_row(request, key)` finds one row for its page by scanning the rows;
override it when the source can fetch one on its own. A key must not
contain `/`.

The addresses: `data/<name>/` the list, `data/<name>/<key>/` a row, and
`data/<name>/<key>/<page>/` its pages of the project's own, where it has
some ([Pages of a resource's own](pages.md)).

## Columns

`columns` maps each field to its column, in the table's order. A column
is one of the [data table columns](tables.md#column-types), with every
option they take — `title`, `visible=False`, `choices`, `tag_style`,
`filter_type`, `searchable`… — or simply the type of its values:

| Type | Column |
| --- | --- |
| `str` | `CharColumn` |
| `int` | `IntegerColumn` |
| `float` | `FloatColumn` |
| `Decimal` | `DecimalColumn` |
| `bool` | `BooleanColumn` |
| `datetime.date` | `DateColumn` |
| `datetime.datetime` | `DateTimeColumn` |
| `list` | `TagsColumn`, filtered as several values |

A type gives the column the field's name as its title, in English: use a
column with a translated `title` for anything a user reads.

As on a model, **only what is declared can be filtered, searched or
sorted**: a condition on any other name is refused with a 400. A column
the table should not show but the row's page and the search should,
takes `visible=False`.

## Rows of other resources

Rows point at each other: an incident belongs to a service, a service
has incidents. Declare the incidents as a data resource of their own —
a list and a page per incident — then say how the two meet:

```python
from generic.sites import DataResource, RelatedRows, RowLink, register_data


@register_data
class ServiceResource(DataResource):
    name = "services"
    ...
    # A tab of the service's page: the incidents whose "service" holds
    # this service's key.
    related_tables = (
        RelatedRows("incidents", resource="incidents", field="service"),
    )


@register_data
class IncidentResource(DataResource):
    name = "incidents"
    show_in_navigation = False            # reached from its service
    links = {"service_name": RowLink("services", key="service")}
    columns = {
        "title": CharColumn(title=_("Incident")),
        "service_name": CharColumn(title=_("Service")),
        ...
    }

    def get_rows(self, request):
        return statuspage.incidents()     # every incident, with its "service"
```

**`RelatedRows`** puts a tab on the service's page holding the
incidents' own table — its columns, filters, search, sorting and
exports — narrowed to that service, each row opening on the incident's
page. The tab's title and icon are the incidents' (`title=`, `icon=`
change them), its count is how many belong to the service, and the
column naming the service is left out, since it would say the same thing
on every line. `columns=("title", "status")` chooses what shows at
first; `page_length` the rows per page (10).

The rows are the related resource's, whose `field` holds this row's key.
When the API answers per parent — `GET /services/<id>/incidents` — ask
it instead:

```python
RelatedRows(
    "incidents",
    resource="incidents",
    rows=lambda request, service: statuspage.incidents_of(service["id"]),
)
```

The table asks for the rows with `_related=services.incidents:<key>`:
the parent's name, the tab's, the row's key. The endpoint resolves it
through the parent's declaration — a tab that is not declared, or that
does not hold this resource's rows, is refused with a 400, an unknown
key is a 404 — and the reader needs the parent's permission as well as
the incidents'.

**`RowLink`** makes a field lead to another resource's row: here the
service's name, shown in the incidents' table and on an incident's page,
leads to the service whose key is in `service`. `{"service": "services"}`
is enough when the field holding the key is also the one shown. A
reader who may not open the other resource sees the text, not a link.

Every resource these name must be registered; that is checked when the
URLs are built, and a name nobody registered raises
`ImproperlyConfigured` then.

## Pages of its own

A data resource takes pages of the project's own like any resource -
a runbook, a map of its rows, a report - declared with `@page` or
`ResourcePage`: the example's services have a *Runbook* page, at
`data/services/<id>/runbook/`, whose text the API answers on its own and
is fetched when the page opens. See [Pages of a resource's own](pages.md).

## Options

| Attribute | Default | Meaning |
| --- | --- | --- |
| `name` | the class name | The piece of address: lower case, digits, dashes |
| `label`, `label_plural` | from `name` | What the rows are called |
| `icon`, `group`, `order`, `description` | | Navigation and dashboard, as on a model |
| `show_in_navigation` | `True` | |
| `permission` | `None` | A permission string, several (all needed), `callable(user)`, or `None` for any signed-in user |
| `key` | `"id"` | The field naming a row in its address |
| `columns` | required | Field → column or type |
| `list_display_links` | the first column | Columns linking to the row's page |
| `ordering` | none | The order when the reader asks for none: `("-uptime", "name")` |
| `list_per_page` | `TABLE_PAGE_SIZE` | The user's own choice wins |
| `show_export` | `True` | |
| `filter_row` | `"open"` | The fields under the headers: `"open"`, `"toggle"`, `False` |
| `presets` | `{}` | Layouts offered to everyone in the **Views** menu, beside each user's saved views - as on a [resource](sites.md#views) |
| `table_options` | `{}` | Client options merged over the defaults |
| `label_field` | the first column | What a row is called on its page |
| `detail_fieldsets` | one section of every column | Sections of the row's page, fieldsets style; any key of the row may appear |
| `detail_stats` | none | Figures shown as tiles above the sections |
| `related_tables` | none | Tabs of other data resources' rows: `RelatedRows(name, resource=, field= or rows=)` |
| `links` | none | Fields leading to another data resource's row: `{"field": RowLink("resource", key="its key field")}` |
| `pages` | none | Pages of the project's own, and `@page` methods: see [Pages of a resource's own](pages.md) |

## What it is not

The rows are read only — nothing is added, changed or deleted, and there
are no bulk actions. They are not in the command palette, keep no
history, and cannot be watched: nothing announces that an external API
changed its mind. A table of them refreshes when the reader reloads it.

Sorting, filtering and counting happen in Python, on every request:
fine for the hundreds or thousands of rows an API answers with, not for
millions — those belong in a table of their own.

## Underneath

The endpoint is a `RowsDataTableViewSet` (`generic.api.rows`), usable
without a site, as `DataTableViewSet` is:

```python
from generic.api import DataTableSerializer, RowsDataTableViewSet


class ServiceViewSet(RowsDataTableViewSet):
    serializer_class = ServiceSerializer   # a DataTableSerializer
    ordering = ("name",)

    def get_rows(self):
        return statuspage.services()
```

The filter tree goes through the same whitelist and the same engines as
a queryset's. They build a `Q`; `generic.api.rows.matches` reads that
`Q` against a row instead of sending it to the database, so a condition
means the same thing on both — *does not contain* keeps the rows with no
value, a negation over a list means *none of them*, a date compares by
whole days in the active time zone.

A project overrides the pages with `generic/data/<name>/list.html` and
`generic/data/<name>/detail.html`; by default they are the resource
templates a model's pages use.

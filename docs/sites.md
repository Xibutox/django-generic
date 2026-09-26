# Sites and resources

`generic.sites` is the admin-like layer: declare how a model should
appear, once, and get

- a **list page** backed by DataTables, with per-column filters, a
  multi-word search, saved views, exports, bulk actions and live
  updates,
- a **summary page** for each record: its figures, its values with
  links to the related records, and a tab per table of related records,
- **charts** computed by the database, above the list, on the summary
  page or anywhere else — see [Charts](charts.md),
- **coloured tags** for the values that read best as labels: a status,
  the tags of a record,
- **add and change pages** drawn in the browser from the form schema,
  with Select2 relations, related-record popups and inlines,
- a **delete page** previewing what would go with the record,
- **one REST endpoint** behind all of them,
- a **sidebar entry** and **command palette** results.

It reads like `django.contrib.admin` on purpose — `list_display`,
`search_fields`, `fieldsets`, `inlines`, `actions` mean what they mean
there — with one difference that shapes everything else: **every page
talks to the server through the REST API, in JSON**. The HTML is a
frame; the data is DRF's. See [Architecture](architecture.md#the-ui-drf-first)
for why.

## Mounting

```python
# urls.py
from django.views.i18n import JavaScriptCatalog
from generic.sites import site

urlpatterns = [
    path("admin/", admin.site.urls),        # optional, kept for staff
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic"]),
        name="javascript-catalog",          # optional: translated controls
    ),
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("wiki/", include("generic.wiki.urls")),   # optional: the wiki
    path("", site.urls),                    # last: it owns the root
]
```

```python
# settings.py
LOGIN_URL = "site:login"
```

`site.urls` provides the dashboard, sign in and out, the account and
notification pages, and every resource's pages and endpoint. Its
namespace is `site`.

## Declaring a resource

Put resources in a `resources.py` module of any installed app. Those
modules are imported at start-up, the way `admin.py` is.

Rows that are not a model's — an external API's answer — are declared
with a `DataResource` instead: a list and a page per row, read only.
See [Rows from elsewhere](data.md).

A resource may also have pages of its own beside the generated ones — a
map, a timeline, a report, any content — declared with `@page` or
`ResourcePage`. See [Pages of a resource's own](pages.md).

```python
from generic.sites import (
    Chart, ModelResource, RelatedTable, TabularInline, TagStyle,
    action, display, register,
)


class CommentInline(TabularInline):
    model = TicketComment
    fields = ("author", "body", "position")
    extra = 1


@register(Ticket)
class TicketResource(ModelResource):
    icon = "confirmation_number"          # Material Symbols name
    group = _("Support")                  # sidebar group

    list_display = ("reference", "title", "customer", "tags", "status", "age")
    search_fields = ("reference", "title", "description")
    tag_fields = {
        "tags": TagStyle(color="color", background="background"),
        "status": TagStyle(colors={"open": "#2563eb", "closed": "#64748b"}),
    }
    charts = (Chart("by_status", type="donut", group_by="status"),)
    list_charts = ("by_status",)
    fieldsets = (
        (None, {"fields": ("reference", ("title", "team"), "description")}),
        (_("Billing"), {"fields": ("is_billable",), "classes": ("collapse",)}),
        (_("History"), {"fields": ("opened_at",), "classes": ("tab",)}),
    )
    readonly_fields = ("opened_at",)
    inlines = (CommentInline,)
    actions = ("close", "delete_selected")

    detail_stats = ("hours_logged",)
    related_tables = (RelatedTable("time_entries"), RelatedTable("comments"))

    @display(description=_("Age"), ordering="opened_at")
    def age(self, ticket):
        return ticket.age_in_days

    @display(description=_("Hours logged"))
    def hours_logged(self, ticket):
        return ticket.time_entries.aggregate(total=Sum("hours"))["total"]

    @action(description=_("Close"), icon="task_alt",
            confirm=_("Close the selected tickets?"))
    def close(self, request, queryset):
        count = queryset.update(status="closed")
        announce(self, "bulk")            # update() sends no signal
        return _("%(count)s closed.") % {"count": count}
```

`site.register(Model, ResourceClass, **options)` works too, and
keyword options build a subclass on the fly:
`site.register(Tag, search_fields=("name",))`.

**The short way.** `auto(Model, related=(...))` registers an
`AutoResource`, which works out from the model everything above that is
not declared — the columns, the search, the tags of the choices, the
form, a table and a form tab per related relation — and gives a related
model nobody declared pages of its own. See
[Pages from the model](auto.md).

### Attributes

| Attribute | Meaning |
| --- | --- |
| `icon`, `label`, `label_plural`, `description` | How the model is named and drawn |
| `group`, `order`, `show_in_navigation` | Sidebar placement; `group` defaults to the app's name |
| `list_display` | Columns: fields, `related__paths`, resource methods, model attributes, `"__str__"` |
| `list_display_links` | Columns linking to the record's page; the first by default |
| `list_select_related`, `list_prefetch_related` | Extra joins; the ones the columns need are added for you |
| `list_per_page` | First page size, before the user's own preference |
| `search_fields` | What the search box, the autocomplete and the palette match |
| `ordering` | Default order of the table |
| `presets` | Named layouts offered to everyone — see below |
| `actions` | Bulk actions; `("delete_selected",)` by default |
| `show_export`, `show_full_result_count` | Export menu; counting the whole table on every draw |
| `filter_row` | The row of search fields under the column headers: `"open"` (default), `"toggle"` behind a button, `False` not offered — see [Filters](#filters) |
| `table_serializer`, `table_options` | A hand-written table serializer; client options |
| `tag_fields` | Fields drawn as coloured tags, in the table and on the summary page: `{"name": TagStyle(...)}` |
| `charts` | `Chart` declarations, served at `api/<app>/<model>/charts/<name>/` |
| `list_charts` | Charts drawn above the list, following its filters, by name |
| `detail_charts` | Charts on the summary page: `"<related table>.<chart>"`, narrowed to the record |
| `object_page` | Where a record opens: `"detail"` (its summary, default) or `"change"` |
| `detail_fieldsets` | The summary page's sections; the form's fieldsets by default |
| `detail_stats` | Figures shown as tiles on the summary page |
| `related_tables` | `RelatedTable` declarations: the summary page's tabs |
| `fields`, `exclude`, `fieldsets`, `readonly_fields` | The form, admin style |
| `form_overrides` | Presentation per field: `width` (1-12), `rows`, `placeholder`, `label`, `helpText` |
| `form_serializer` | A hand-written `FormModelSerializer`, replacing the generated one |
| `inlines` | `TabularInline` / `StackedInline` classes |
| `view_on_site` | Link to `get_absolute_url()` on the record's pages |
| `editable_fields` | Columns that *may* be edited in a table; a name may walk relations (`"customer__name"`). Turns nothing on by itself: a table asks ([Editing in the table](editable.md)) |
| `list_editable` | `False`. Whether this resource's own list page offers those cells |
| `grids` | `Grid` declarations: sets of rows corrected many at once, each shown by a `GridView` ([Editing in the table](editable.md#any-set-of-records-declared-grids)) |
| `form_field_kwargs` | Serializer options per field, as DRF's `extra_kwargs`: `{"token": {"write_only": True}}`. What the field does, where `form_overrides` is how it is drawn |
| `realtime` | Publish every change so open tables and summaries refresh |
| `watchable` | Offer the *Watch* button, and answer its endpoint ([Watching](watch.md)) |
| `history` | Keep a version of every record, read back by its History tab ([History](history.md)) |
| `history_exclude` | Fields left out of that version, by name |
| `viewset_class` | The DRF viewset the endpoint is built from |

### Methods worth overriding

| Method | Default |
| --- | --- |
| `get_queryset(request)` | The model's default manager |
| `get_list_queryset(request)` | `get_queryset` plus the joins the columns need; annotate here |
| `get_search_fields(request)` | `search_fields` |
| `get_detail_fieldsets(request)`, `get_detail_stats(request)` | The attributes |
| `has_module_permission(request)` | Any permission on the model |
| `has_view_permission(request, obj=None)` | `view` or `change`, as in the admin |
| `has_add_permission`, `has_change_permission`, `has_delete_permission` | The model permission |
| `save_model(request, serializer, change)` | `serializer.save()` |
| `delete_model(request, obj)` | `obj.delete()` |
| `get_actions(request)` | `actions`, filtered on each action's permissions |
| `get_record_links(request, obj)` | `[]`. `ToolbarItem`s for pages built around this record, shown first on its summary; as many as needed — what does not fit folds into the toolbar's ⋯ menu |
| `can_edit_column(request, column, obj=None)` | `True`. Freeze an editable column per row or per reader |
| `save_editable(request, obj, changes)` | Resolve, validate with the form's serializer, save in one transaction ([Editing in the table](editable.md)) |
| `create_editable(request, values, fixed)` | A row added in a grid: validate with the form serializer, save through `save_model`, return the record ([Adding rows](editable.md#adding-rows)) |

The endpoint enforces the same methods as the pages: hiding a button is
never the only protection.

## The list page

Columns are derived from the model, so `list_display` is usually all a
table needs:

- a **choice field** is shown by its label and filtered by picking
  among its values, with how many rows hold each,
- a **foreign key** is shown by the related record's name, links to
  that record's page when the user may open it, and is filtered by
  picking among the related records present — searched by their label,
  never shipped whole to the browser,
- a **many-to-many** is shown as a comma-separated list and filtered
  without listing a row twice, with *has all of* besides *any* and
  *none*,
- text, numbers, booleans and dates get their own operators — see
  [Filters](#filters),
- a field named in `tag_fields` is drawn as **coloured tags** and keeps
  its filter — see below,
- each row stays on one line; long text wraps, with room.

A method column is sortable when `@display(ordering=...)` names an ORM
path — typically an annotation made in `get_list_queryset` — and
filterable when `@display(filter_field=...)` does.

### Tags

A value that reads best as a label — a status, a record's tags, a
priority — is drawn as a small coloured tag. The colours come from the
data: the related record's own fields, or fixed colours by value.

```python
from generic.sites import TagStyle

class TicketResource(ModelResource):
    list_display = ("reference", "title", "tags", "status", "priority")
    tag_fields = {
        # A many-to-many: each Tag record holds its colours.
        "tags": TagStyle(color="color", background="background"),
        # A choice: colours by value.
        "status": TagStyle(colors={"open": "#2563eb", "closed": "#64748b"}),
        # A background and its text, for the one that must stand out.
        "priority": TagStyle(colors={
            "urgent": {"background": "#dc2626", "color": "#ffffff"},
        }),
    }
```

Two ways to draw a tag:

- **one colour** (`color` alone): the tag is *tinted* — its text mixes
  the colour with the theme's text, its background with the surface — so
  it stays readable in the light and the dark scheme whatever colour the
  record holds;
- **a background** (`background`, with or without `color`): drawn
  exactly; without a text colour, black or white is picked for contrast.

| `TagStyle` option | Meaning |
| --- | --- |
| `label` | Attribute (or callable) giving the text; `str()` or the choice label by default |
| `color` | Attribute holding the text colour — alone, the tint |
| `background` | Attribute holding the background colour |
| `title` | Attribute giving a tooltip |
| `colors` | Fixed colours by value or label: `"#hex"` or `{"color", "background"}` |
| `default` | The colour of a tag nothing else colours |

Each of `label`, `color`, `background` and `title` may be a callable
taking the value. Works on a many-to-many or a reverse relation (several
tags), a foreign key or a choice (one tag), and on a method:

```python
@display(description=_("Flags"), tags=TagStyle(color="color"))
def flags(self, ticket):
    return ticket.flags.all()          # records, values, or dicts
```

A method may also return dicts — `{"label": "Late", "color": "#b45309"}`
— with `tags=True`. Filters stay what the field had: a Select2 over the
related records, the choices of a choice field. A tag of a record links
to that record's page when the user may open it. Exports and copies get
the labels, comma separated. On the summary page, the same fields are
drawn as the same tags.

Colours reach a `style` attribute in the browser, so each one is checked
on the server and again in the browser against a strict pattern — a hex
value, a named colour, `rgb()`, `hsl()`, `oklch()` and their kin — and
dropped otherwise.

### Charts above the list

```python
charts = (
    Chart("by_status", title=_("By status"), type="donut", group_by="status"),
    Chart("opened", group_by="opened_at", split_by="priority",
          stacked=True, period="week", periods=("week", "month")),
)
list_charts = ("by_status", "opened")
```

The charts named in `list_charts` sit above the table and **follow its
filters and search**; a click on a bar or a slice filters the table on
it. See [Charts](charts.md) for every option.

### Filters

Filters take no room until something filters. Those in force are chips
in a bar under the toolbar — *Status is any of Open, Pending*, *Opened
at is in the last 30 days* — each one opening its editor, each one
removable, with *Clear all* at the end. There are five ways in:

| Where | Does |
| --- | --- |
| **Filter** in the toolbar, or the **F** key | Pick a column, then set its filter |
| The **funnel** of a column header (on hover) | That column's filter; the header is underlined while it filters |
| **The search row** under the headers | A field per column: type, pick values, choose yes or no — the button beside *Filter* hides it and brings it back — see below |
| **The search box** | Free words search every column; `name:value` words become filters — see below |
| **A right click** on a cell | *Only this value*, *anything but this value*, and for a number or a date *at least* / *on or after* |

The editor fits the column:

| Column | Offers |
| --- | --- |
| Choice, relation, tags | The values present under the other filters, searchable, with a count beside each and tags in their colours; *is any of*, *is none of*, *has all of* (many-valued), *is empty* |
| Text | *contains*, *does not contain*, *is*, *is not*, *starts with*, *ends with* — several values with commas, any of which may match — with the column's values suggested when it offers them |
| Number | *=*, *≠*, *>*, *≥*, *<*, *≤*, *is between*, with the column's range as a hint |
| Date | *is on*, *before*, *after*, *on or before*, *on or after*, *between*, and relative periods: today, this week, last month, this quarter, this year, in the last or next N days, more than N days ago |
| Boolean | *is yes*, *is no* |
| Every column | *is empty*, *is not empty* |

The editor applies as it changes, while it stays open: a value ticked,
a condition or a column picked at once, words, numbers and dates as the
typing pauses. Its button says *Done*, and also applies a condition
complete from the start (*is yes*); *Cancel* puts the filters back as
they were when the editor opened. Emptying the value — unticking every
value, clearing the field — removes the filter.

Several filters may target the same column. With two or more, *All of*
turns into *Any of* at the start of the bar; **groups** — *Add a group:
any of several* in the column picker — hold conditions of their own, so
*status is open AND (priority is urgent OR opened more than 30 days
ago)* is two clicks away.

**The search row.** One short line of fields under the column titles,
there from the start; the button beside *Filter* (the magnifier with
lines) hides it and brings it back, and the table remembers that choice
once it is made. A field filters its column as soon as the typing
pauses, or on Enter; Escape empties it.

| Column | The field |
| --- | --- |
| Text | Words it contains; `=Invoice` the exact value, `^SD-10` a start, `a,b` any of several |
| Number | `5`, `>10`, `<=2.5`, `2..8` |
| Date | `2026-01-01`, `>=2026-01-01`, `2026-01-01..2026-03-31`, `30d` (the last 30 days), `+7d`, `this-month`; the calendar opens the full editor |
| Boolean | A list: *All*, *Yes*, *No*, *Empty* |
| Choice, relation, tags | A button showing what is picked, opening the values with their counts |

In a text, number or date field, `empty` matches rows without a value,
and `!` before the text excludes it: `!billing`, `!empty`. Text a field
cannot read is outlined in red when Enter is pressed, and filters
nothing.

A field edits the condition on its column at the top level of the
filters — the one its chip shows — so the row, the chips and the funnels
always agree: remove a chip and its field empties. When a column holds
something one field cannot say — two conditions, *more than N days ago*
— the field shows it in words and opens its editor instead. Conditions
inside a group are left to the group.

```python
@register(Tag)
class TagResource(ModelResource):
    filter_row = "toggle"        # behind its button; False removes it
```

`filter_row` is the declaration; what a user chose with the button wins
over it, for that table and that browser only.

**Typed filters.** In the search box, a word shaped `name:value` becomes
a chip as soon as it is followed by a space or Enter. While typing, a
list suggests the columns, then their values with their counts.

| Typed | Means |
| --- | --- |
| `status:open,pending` | Status is any of Open, Pending (labels or values) |
| `-tags:billing` | Tags is none of billing |
| `team:front` | Team is the one whose name matches *front* |
| `hours:>=2`, `hours:2..8` | at least 2; between 2 and 8 |
| `opened:30d`, `due:+7d` | in the last 30 days; in the next 7 |
| `opened:this-month`, `opened:last-year` | a relative period |
| `due:2026-01-01..2026-03-31`, `due:<2026-06-01` | a date range; before a date |
| `billable:yes`, `assignee:empty`, `-assignee:empty` | booleans and blanks |
| `title:"password reset"`, `title:=Invoice` | a phrase; an exact value |

A column is named by its key or its title, or any unambiguous start of
either word: `opened`, `hours`, `billable`.

**Links.** On a list page the address carries the filters and the
search, so a filtered table can be bookmarked, shared or reached with
the back button; the related tables of a summary page leave it alone.
Saved views and presets store the same tree.

The editor asks the endpoint's `facets/` action for the values and
their counts: see [Data tables](tables.md#facets). A column whose ORM
path is an annotation offers no list, only its operators.

### Search

Every word must match, in any of `search_fields`:

| Typed | Finds |
| --- | --- |
| `invoice blank` | rows matching both words |
| `invoice !blank` or `invoice -blank` | *invoice*, without *blank* |
| `"password reset"` | the phrase as written |
| `SD-1000` | the reference: a dash inside a word is not a negation |

A search through a many-valued path (`tags__name`) never duplicates
rows.

### Views

The **Views** menu offers the resource's `presets` to everyone and each
user's own saved views beside them:

```python
presets = {
    _("Needs attention"): {
        "columns": ["reference", "title", "assignee", "due_on"],
        "filters": {
            "match": "all",
            "conditions": [
                {"column": "status", "operator": "any_of", "value": ["open"]},
                {"match": "any", "conditions": [
                    {"column": "priority", "operator": "any_of", "value": ["urgent"]},
                    {"column": "opened_at", "operator": "older_than_days", "value": 30},
                ]},
            ],
        },
        "order": [["due_on", "asc"]],
    },
}
```

`filters` is a filter tree ([Data tables](tables.md#the-filter-tree));
the older flat form, one condition per column, still works.

A user saves the current layout under a name, marks one as their
default, and gets it back on any device: views are stored on the
server (`SavedView`), not in the browser. Whether a table also comes
back as it was left is a per-user preference.

### Exports

*Excel* and *CSV* export **every row matching the filters and the
search**, not the page on screen, with the visible columns in their
current order. *Copy* and *Print* take the page on screen. CSV uses
semicolons, which is what Excel expects outside English locales.

### Selection and bulk actions

Tick rows, or tick the header box and choose *every matching row*.
The menu lists the actions the user may run; an action with `confirm`
asks first. An action receives a plain queryset of the chosen rows —
never the annotated list queryset — and may return nothing, a message,
`{"message": ..., "level": ...}`, or a DRF `Response`.

```python
@action(
    description=_("Mark as billable"),
    icon="payments",
    permissions=("change",),     # view, add, change, delete, or "app.codename"
    confirm=None,
    variant="default",           # or "danger"
)
def mark_billable(self, request, queryset): ...
```

### Row menu

Each row has a menu — also on right-click — with *Open* (the summary
page), *Edit* and *Delete* as the user's permissions allow. A
double-click opens the row.

### Live updates

With `realtime = True`, saving or deleting a record publishes a
`resource.changed` event on the topic `resource.<app>.<model>`. Every
open table of that model reloads itself, debounced, and so does the
summary page of the record. `QuerySet.update()` sends no signal, so a
bulk action using it calls `announce(self, "bulk")`.

## The summary page

A record opens on its summary page — `<app>/<model>/<pk>/` — rather
than on its form: its figures, its values, and a table for each kind of
related record. It is the page for a record that has many of them: a
customer and its hundreds of tickets, a ticket and its time entries.

```python
@register(Customer)
class CustomerResource(ModelResource):
    detail_stats = ("open_tickets", "hours_logged")
    detail_fieldsets = (...)              # the form's fieldsets by default
    related_tables = (
        RelatedTable("tickets"),          # a reverse foreign key
        RelatedTable(
            "time_spent",
            model=TimeEntry,
            lookup="ticket__customer",    # any path back to the customer
            title=_("Time spent"),
        ),
    )

    @display(description=_("Open tickets"))
    def open_tickets(self, customer):
        return customer.tickets.filter(status="open").count()
```

- **Figures** (`detail_stats`) are fields, resource methods or model
  attributes, labelled with `@display` and shown as tiles.
- **Sections** show every value read-only and typed: a choice by its
  label, a relation as a link to the related record's page when the
  user may open it, several related records as chips, a date in the
  user's format, long text with its line breaks, and the fields of
  `tag_fields` as their coloured tags.
- **Charts** (`detail_charts`) cover the record's related rows, between
  the figures and the sections; a related table may carry its own
  (`RelatedTable(..., charts=(...))`), drawn in its tab and following
  its filters.
- **Related tables** sit in tabs, each with its count. A table is the
  related resource's own table — columns, filters, search, exports,
  bulk actions, live updates — narrowed to the record's rows. It starts
  the first time its tab is shown, so a record with five related tables
  costs one request, not five.
- **However many tabs there are.** The bar draws as many as fit and
  puts the rest behind a `+N` button at its end: a menu listing them
  with their counts, which marks itself as the open one when the tab
  you are on is inside it. It is measured, not counted — the same
  record shows seven tabs on a wide screen and one plus a menu on a
  telephone — and it measures again when the window changes, when the
  navigation is pinned, or when a table reports a total wider than the
  badge that held it. Nothing is declared for this; the example's
  customer page, with six related tables and the history, is there to
  be resized.
- **Actions**: the resource's bulk actions apply to the record too, as
  buttons; deleting keeps its own.
- **Live**: when the record changes, the page fetches its summary again.

| `RelatedTable` option | Meaning |
| --- | --- |
| `name` | A reverse foreign key or a many-to-many of the model, by accessor name |
| `model`, `lookup` | Any other path: the related model, and the ORM path back to the record |
| `title`, `icon`, `description` | Defaults from the related resource |
| `columns` | The columns shown at first; the others stay in the column picker |
| `hide_lookup_column` | Leave out the column naming the record (default) |
| `page_length` | Rows per page (10) |
| `allow_add` | An *Add* button that fills the record in, and comes back to this tab |
| `charts` | Charts of the related resource, by name, drawn above the table in its tab |

```python
related_tables = (
    RelatedTable("tickets", charts=("by_status",)),
    RelatedTable("time_spent", model=TimeEntry, lookup="ticket__customer",
                 charts=("hours_by_agent",)),
)
detail_charts = ("time_spent.hours_by_month",)   # <related table>.<chart>
```

A related table's rows come from the related resource's endpoint with a
`_related=<app>.<model>.<name>:<pk>` parameter. The endpoint resolves
the name through the declaration — a client cannot filter on a path of
its own choosing — and checks that the user may see the record.
Exports and "every matching row" bulk actions carry the parameter too,
so they stay within the record.

The related model needs a registered resource: register it with
`show_in_navigation = False` when it has no page of its own, like the
example's ticket comments.

Where records open is `object_page`: `"detail"`, the default, or
`"change"` for the admin's behaviour. Table rows open there, and so do
the command palette, the watches page and the delete page's *Cancel*. From
a change page, *Save* returns to the summary.

## The form

Add and change pages load the schema and the record from the endpoint,
draw the form, and send JSON back:

- `fieldsets` become sections; `("collapse",)` starts one folded — it
  unfolds by itself if a field in it has an error — and `("tab",)`
  gives it a tab,
- a tuple of fields in a fieldset — or in `fields` — shares a row,
- `form_overrides = {"color": {"widget": "color"}}` gives a text field a
  colour picker beside it, which may stay empty,
- `readonly_fields` may name resource methods or model attributes:
  shown, never sent,
- a relation is a **Select2**: searched through the related resource's
  autocomplete when it has `search_fields`, otherwise from embedded
  choices (capped by `FORM_CHOICES_LIMIT`, with a warning when cut),
- beside it, a pencil edits the chosen record and a plus creates one,
  in a popup that hands the result back — each only when the user may,
- *Save*, *Save and continue editing*, *Save and add another*; Ctrl+S
  saves; leaving with unsaved changes asks first,
- an add page opened with values in its address — `?customer=3` — is
  filled in with them, and with `_next=/a/page/` it goes back there
  once saved,
- errors come back from DRF and land on their field, their inline row,
  or the top of the form.

The record's own primary key travels with it but is never drawn.

### Inlines

```python
class AgentInline(StackedInline):   # one card per record
    model = Agent
    fields = ("name", "email", "is_active")
    extra = 0
```

| Attribute | Meaning |
| --- | --- |
| `model`, `fk_name` | The related model, and its key to the parent when there are several |
| `fields`, `exclude`, `readonly_fields`, `form_overrides` | As on the resource |
| `extra`, `min_num`, `max_num`, `can_delete` | Blank rows on a new record; bounds |
| `verbose_name`, `verbose_name_plural`, `description` | Naming |
| `classes` | `("tab",)` for a tab of its own, `("collapse",)` to start folded |
| `serializer_class` | A hand-written `FormModelSerializer` |

`TabularInline` draws a table row per record. An inline answers to its
own model's permissions, as in the admin: a user who may change tickets
but only view comments sees the comments, read-only.

The parent and its rows travel in one request, under `_inlines`, and
land in one transaction. Removals run before the remaining rows are
validated, so one save can free a unique position and reuse it. See
[Forms and inlines](forms.md#tabular-inlines) for the wire format.

Inlines suit a handful of rows edited with their parent. For a record
with many related records, a related table on the summary page is the
better tool.

## The endpoint

| Request | Does |
| --- | --- |
| `GET api/<app>/<model>/` | Rows, in the DataTables protocol; `filters` (a tree), `search`, and `_related` to narrow them to a record's |
| `GET .../facets/?column=` | A column's values and their counts under the other filters, or its range |
| `POST api/<app>/<model>/` | Create, with `_inlines` |
| `GET api/<app>/<model>/<pk>/` | One record, with `_display` labels, `_label` and `_inlines` |
| `PATCH api/<app>/<model>/<pk>/` | Update, with `_inlines` |
| `DELETE api/<app>/<model>/<pk>/` | Delete; refused with the reason when protected |
| `GET .../<pk>/summary/` | The summary page, as JSON: figures, typed values, related tables |
| `GET .../form-schema/` | The form, as JSON |
| `GET .../<pk>/deletion-preview/` | What a delete would take with it |
| `GET .../export/`, `.../export-csv/` | Every filtered row |
| `POST .../actions/` | Run a bulk action: `{"action", "ids"}` or `{"action", "all": true}` |
| `GET .../autocomplete/` | Select2 results: `?q=` and `?page=`, or `?ids=1,2` to label known values |
| `GET .../charts/<name>/` | One chart's data, over the rows the table's parameters select; `?period=` |

Route names are `site:api_<app>_<model>-<action>`; the pages are
`site:<app>_<model>_list`, `_add`, `_detail`, `_change` and `_delete`.

## Navigation and the dashboard

The sidebar lists, by group, the resources the user may reach, then
any extra links:

```python
site.add_link(_("Reports"), route="reports:index", icon="bar_chart",
              group=_("Analysis"), permission="reports.view_report")
```

or, without code, in settings:

```python
GENERIC = {
    "NAVIGATION": [
        {"title": "Analysis", "items": [
            {"title": "Reports", "route": "reports:index",
             "icon": "bar_chart", "permission": "reports.view_report"},
        ]},
    ],
}
```

The dashboard lists the same resources with *Open* and *Add*, under the
wiki pages pinned to it. Point `site.index_template` at your own
template to change it, and feed it with:

```python
@site.index_context
def figures(request):
    return {"open_tickets": Ticket.objects.filter(status="open").count()}
```

### The hub

Above all of it sits a row of cards pointing at whatever is worth going
to first — a filtered list, a page of the project's own, or something
outside the application entirely:

```python
site.add_shortcut(
    _("Open tickets"),
    # A filter tree in the address: the list opens already narrowed.
    url='/example/ticket/?filters={"match":"all","conditions":[...]}',
    icon="confirmation_number",
    description=_("Everything the desk has not answered yet."),
    count=lambda request: Ticket.objects.filter(status="open").count(),
    permission="example.view_ticket",
)

site.add_shortcut(
    _("Weekly report"),
    url="https://reports.example.test/weekly",
    icon="bar_chart",
    group=_("Elsewhere"),      # a heading; ungrouped cards come first
)

site.add_shortcut(_("Log a ticket"), route="site:example_ticket_add")
```

| Option | Means |
| --- | --- |
| `url` / `route` (+ `route_args`) | where it goes; a route that is not mounted here drops the card rather than breaking the page |
| `icon`, `description` | what the card shows, beside the label |
| `count` | a value or `callable(request)`, drawn as a badge — what makes the hub worth reading rather than only clicking |
| `group`, `order` | headings, and the order inside one |
| `permission` | a string, several, `callable(user)`, or nothing for any signed-in user |
| `external` | opens in a new tab; `None` decides from the address |

The same thing from settings, for a project that would rather
configure than declare:

```python
GENERIC = {"SHORTCUTS": [
    {"label": "Handbook", "url": "https://wiki.example.test/",
     "icon": "book", "group": "Elsewhere"},
]}
```

And, for a hub curated at runtime, the hook that lets a project back it
with a model of its own without the framework shipping one:

```python
@site.shortcut_provider
def bookmarks(request):
    return [
        Shortcut(label=row.title, url=row.url, icon=row.icon)
        for row in Bookmark.objects.filter(team=request.user.team)
    ]
```

Three rules worth knowing. A card a user may not open **never
appears** — the permission is the same kind a navigation link takes. An
address is **checked where it is written**: anything that is not a path
of this site, `http`, `https`, `mailto` or `tel` raises
`ImproperlyConfigured` naming the shortcut, because it would end up in
an `href`. And a `count` that raises is **no badge rather than no
dashboard**: a signpost must not be able to take the page down.

The section is the `dashboard_shortcuts` block of
`generic/site/index.html`, above `dashboard_intro`; a project that
wants it lower moves the block.

A chart any resource declares can be drawn there, or on any page
extending `generic/base.html` — nothing is drawn for a user who may not
see it:

```django
{% load generic_ui %}
<div class="chart-grid">
  {% generic_chart "example.ticket" "opened" %}
  {% generic_chart "example.timeentry" "hours_by_month" height="20rem" %}
</div>
```

**Ctrl+K** opens the command palette: it searches the pages and every
resource the user may view (`SEARCH_RESULTS_PER_RESOURCE` records
each), plus whatever `@site.search_provider` functions add — the wiki
adds its pages that way.

## Accounts

| Page | Holds |
| --- | --- |
| `/login/`, `/logout/` | Sign in and out |
| `/account/` | Profile, appearance, preferences, what you watch, password |
| `/notifications/` | The notification history |

**Appearance** and **preferences** — theme and colours, rows per page,
how to be notified, whether tables remember their layout — are stored
on the account (`UserPreferences`), so they follow the user from one
browser to the next, and apply before the first paint.

The **profile** edits the user's name and address. An account without
a usable password is treated as externally managed (LDAP, SSO): its
identity is shown read-only, since the provider would overwrite it.

**Watching**: the account page lists what the user is being told about,
and the *Watching* page beside it is where each watch's changes and
channels are chosen. See [Watching](watch.md).

All of it is REST, under `api/generic/`: `account/preferences/`,
`account/profile/` (each with a `schema/` sibling), `watches/` with
`status/` and `toggle/`, and `saved-views/`.

## The frame and theming

| Setting | Default | Meaning |
| --- | --- | --- |
| `SITE_TITLE` | `"Generic"` | Browser title and brand |
| `SITE_HEADER` | `None` | Brand text, when it differs from the title |
| `SITE_ICON` | `"dataset"` | Brand icon |
| `SITE_URL` | `None` | Where the brand links; the dashboard by default |
| `SHOW_ADMIN_LINK` | `True` | Link staff to the Django admin, when mounted |
| `THEME` | `{}` | Appearance parameters or design tokens, such as `{"--ui-hue": "150"}` |

`THEME` values are checked against a strict pattern — a number, a
colour, a length, plain words — before they reach the page; anything
else is dropped.

### Appearance

Every colour is computed in `tokens.css` from the colour scheme and five
parameters — the approach Linear takes to its themes: a few inputs, a
hundred derived colours, rather than a hundred hand-picked ones.

| Parameter | Range | Default | Moves |
| --- | --- | --- | --- |
| `--ui-hue` | 0 – 360 | 262 (blue) | The accent: buttons, links, selection |
| `--ui-colorfulness` | 0 – 1.3 | 1 | How saturated colours are; 0 is greys only |
| `--ui-tint` | 0 – 1 | 0.35 | How much of the hue the backgrounds carry |
| `--ui-contrast` | -1 – 1 | 0 | Text and lines away from the backgrounds |
| `--ui-stripes` | 0 – 1 | 0.6 | Alternate table rows |

Colours are written in OKLCH, whose lightness is perceptual: the
contrast worked out for one hue holds for all of them, and body and
secondary text stay at WCAG AA even at the softest setting.
`light-dark()` picks the variant for the scheme, and the operating
system's *more contrast* setting raises the default contrast. Browsers
without `light-dark()` — older than 2024 — get a fixed light palette.

Each user moves the parameters as sliders on the account page, starting
from presets if they like — *Soft*, *High contrast*, *Neutral*,
*Forest*… — and sees the whole page follow as they drag. Saved, the
values ride on `<html>` from the next page on. A value equal to the
project's default is stored as empty, so changing the default through
`THEME` still reaches everyone who never moved that slider.

Every page extends `generic/base.html`. Its blocks: `title`,
`sidebar`, `breadcrumbs`, `page_header` (with `page_eyebrow`,
`page_title`, `page_subtitle`, `object_tools`, `toolbar`), `content`,
`styles`, `components` (Alpine components, loaded before Alpine) and
`scripts`. The classic views of `generic.views` extend it too, so they
share the frame.

## The browser side

Vendored under `generic/static/generic/vendor/`, so nothing is fetched
from a CDN: jQuery 4, DataTables 3, Select2 4.1, Alpine.js 3, Quill 2
(for the wiki), Apache ECharts 6 (for the charts, loaded only on a page
that draws one) and the Material Symbols font.

Small Alpine components drive the frame — `themeMenu`,
`notificationBell`, `commandPalette`, `watchControl`,
`appearanceEditor`, and `apiResource` for any block that lists and
changes records through the API; `recordSummary` draws the summary
page, `recordHistory` its History tab and `genericChart` a chart. They are registered on `alpine:init`;
the rest is plain JavaScript under the `Generic` namespace:
`Generic.api` (JSON requests with the CSRF token), `Generic.toast`,
`Generic.dialogs`, `Generic.select2`, `Generic.events`,
`Generic.appearance`, `Generic.colors` (checking and resolving colours)
and `Generic.charts`.

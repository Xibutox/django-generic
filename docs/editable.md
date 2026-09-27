# Editing in the table

A table where a dozen small corrections are the work — a timesheet, a
set of lines under one record, a price list — should not ask for a page
each.

Two steps, on purpose. The resource says which columns **may** be
edited; a table says whether it **offers** that. Most tables are read
on the way to somewhere else, and the page built for correcting rows is
usually a different page.

```python
@register(TimeEntry)
class TimeEntryResource(ModelResource):
    list_display = ("spent_on", "ticket", "ticket__status", "agent",
                    "hours", "is_billable", "note")
    # What may be edited. On its own this turns nothing on.
    editable_fields = ("spent_on", "hours", "is_billable", "note",
                       "agent", "ticket__status")
```

| A table asks for it with | Where |
| --- | --- |
| `bound.get_table_config(request, obj, editable=True)` | a page about one record, over its related rows — [below](#a-page-about-one-record) |
| `Grid(...)` on the resource, shown by `GridView` | any set of rows you choose: many records corrected at once — [below](#any-set-of-records-declared-grids) |
| `get_table_config(request, editable=True)` | the resource's own rows, on a page of your own |
| `RelatedTable(..., editable=True)` | a tab on a record's summary |
| `list_editable = True` on the resource | its own list page. Off by default |

Whichever it is, the grid can also **add rows**: see [Adding rows](#adding-rows).

## A grid, not a list

A table that asks to be editable is where the work happens, the whole
set in view. So it becomes a grid:

- **Every cell that may be written is its control from the start** —
  the one the *form* would have used: an input for text and numbers, a
  date box, a select for a choice, a Select2 autocomplete for a
  relation, a switch for a boolean. Nothing is declared about widgets:
  the table asks the server for the same field schema the form renderer
  reads.
- **Nothing in it leads anywhere.** No cell is a link — neither the
  row's own nor a relation's — no row opens on a double click, and
  there is no row menu. A cell that was a link keeps the type it would
  have had, so a date still reads as a date.
- **Selection and bulk actions stay**: they act on the set in view,
  which is what the page is for.

The server does the stripping (`generic.sites.editable.as_grid`), so a
grid looks the same whoever opens it; only the controls depend on what
the reader may write. A grid keeps its own saved layout, apart from the
same resource's list.

| Doing | Writes |
| --- | --- |
| Picking from a list, ticking a switch, choosing a date | at once |
| Typing, then `Enter` | and moves down a row, as a sheet does |
| Typing, then leaving the cell | when you leave it |
| `Escape` | nothing: the cell goes back to what is saved |

One request per cell. The answer is the whole row: the read-only cells
beside it are drawn again, the other controls take their new value
unless you are in them, and a column of another record — the ticket's
status on a timesheet — follows on **every row pointing at that
record**, since it is the same value.

A cell that will not save keeps the typing, outlines itself and shows
the reason underneath. A cell that saved tints green for a second — a
toast per cell would be unreadable on a table being corrected row by
row.

A grid wider than the page scrolls sideways **inside its card**, never
the page itself. A column drawn as coloured tags (`tag_fields`) is
edited like any other: a choice's tag carries its value beside its
label, and the control starts from it.

### Live, without pulling the grid from under you

A resource table refreshes itself when someone changes a row. In a grid
that would rebuild every control and take whatever was being typed with
it, so the grid holds the refresh back while it is in use — a control
has the focus, a list is open, or a cell is on its way to the server —
and lets it run once the reader puts the grid down. Its own saves are
not refreshes at all: it already has the rows the server sent back.

The hooks are the table controller's (`holdsReload`, `skipsChange`,
`releaseReload`, `requestReload` in `realtime.js`), for any other
feature that needs the same courtesy.

## Adding rows

A grid offers **Add a row** in its toolbar to whoever may add records of
its model. The row appears at the top, as a draft:

- its cells are the controls of the columns a **new** record writes,
  starting from the model's defaults — today's date for
  `default=timezone.localdate` — or from what the grid says;
- the other cells are empty: a column of another record
  (`ticket__status`) has nothing to write to until the row exists;
- **✓** or `Enter` in a typed control sends it; **✕** discards it. A
  draft is sent whole, not cell by cell: a record that does not exist
  yet cannot be written one cell at a time;
- what is wrong is said under its cell — *this field is required* —
  and what the row does not show (a required field the grid left out,
  a rule about the whole record) on a line under the row.

Once added, the grid reloads, the new row tints green and a toast says
so. Several drafts can be open at once; they stay on top across pages,
reloads and columns shown or hidden, with what was typed in them.

What a new row writes and what it gets without asking come from where
the grid is, never from the browser:

| The grid | A new row writes | And gets |
| --- | --- | --- |
| a record's related rows (`_related`) | the resource's own editable columns, **except** the field pointing at the record | that field: the timesheet row belongs to the ticket at once |
| a declared `Grid` (`_grid`) | its editable columns of the model itself, plus `add_fields` | what `add_values` returns for the columns it does not show |
| the resource's own rows | its own editable columns | nothing |

A relation that is not a plain foreign key back to the record — a
many-to-many, a longer path such as the customer's *Time spent* through
the tickets — has nothing to attach a new row by, and adds none.

The creation is the resource's `create_editable`, reprogrammable like
the write:

```python
class TicketResource(ModelResource):
    def create_editable(self, request, values, fixed):
        """`values` by column name; `fixed` by field name."""
        fixed = {**fixed, "opened_by": request.user.pk}

        return super().create_editable(request, values, fixed)
```

The default validates with **the resource's form serializer** — a new
row is refused exactly where the add page refuses one — and saves
through `save_model`, so the history, the watchers and the live tables
all hear of it.

## A page about one record

The shape this is usually for: not a list everybody reads, but a page
about one record showing the rows that belong to it, several of their
fields writable. The framework has the pieces — the parent already
declares the relation — so the page is a view and a template:

```python
class TicketWorkView(SiteViewMixin, TemplateView):
    template_name = "example/ticket_work.html"   # extends generic/datatable.html

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            resource = site.get_resource(Ticket)
            self.ticket = get_object_or_404(
                resource.get_queryset(request), pk=kwargs["pk"]
            )

        return super().dispatch(request, *args, **kwargs)

    def has_permission(self):
        # Both models: the page is a ticket's, its table the entries'.
        return (
            site.get_resource(TimeEntry).has_view_permission(self.request)
            and site.get_resource(Ticket).has_view_permission(self.request)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bound = site.get_related_table("example.ticket.time_entries")

        context["table_config"] = bound.get_table_config(
            self.request, self.ticket, editable=True
        )

        return context
```

```html
{% extends "generic/datatable.html" %}
```

That is the whole page. The table is the time entry resource's own —
its columns, filters, search, exports, live refresh — narrowed to the
ticket, with the cells open. `editable=True` overrides whatever the
`RelatedTable` declares, so the same relation can be **read** in the
tab on the ticket's summary and **corrected** here.

The example ships it at `/demo/tickets/<pk>/work/`.

A page built around a record is only useful if the record says where it
is. The resource hands its summary page the link:

```python
class TicketResource(ModelResource):
    def get_record_links(self, request, ticket):
        if not site.get_resource(TimeEntry).has_view_permission(request):
            return []    # a button leading to a refusal is worse than none

        return [ToolbarItem(
            url=reverse("example:ticket-work", args=[ticket.pk]),
            label=gettext("Work on the hours"),
            icon="edit_note",
            variant="ghost",
        )]
```

Those links come first in the record's toolbar, before *Delete* and
*Edit*: they are why somebody opened the record. There may be as many
as the record needs — the toolbar folds what does not fit into its
**⋯** menu, starting from the end (see [ui.md](ui.md#the-page-toolbar)).

## Any set of records: declared grids

The other usual shape is a page for correcting **many records at once**
that are not one record's rows: every open ticket to triage, this
month's timesheets to check, the agents whose capacity is to plan. The
resource declares the grid; a `GridView` shows it:

```python
from generic.sites import Grid

@register(Ticket)
class TicketResource(ModelResource):
    editable_fields = ("team", "assignee", "priority", "status", "due_on")

    grids = (
        Grid(
            "triage",
            title=_("Triage"),
            description=_("Every open ticket: assign it, prioritise it."),
            icon="assignment_ind",
            # The columns shown at first; the others stay in the picker.
            columns=("reference", "title", "customer", "team", "assignee",
                     "priority", "status", "due_on"),
            # Which rows: any queryset you like.
            scope="triage_rows",
            # A new ticket also writes these, never changed afterwards.
            add_fields=("reference", "title", "customer"),
            # Where a new ticket starts.
            add_values="new_triage_ticket",
            page_length=25,
        ),
    )

    def triage_rows(self, request, queryset, team):
        rows = queryset.filter(status__in=("open", "pending"))

        return rows.filter(team=int(team)) if team else rows

    def new_triage_ticket(self, request, team):
        values = {"reference": next_reference(), "status": "open"}

        if team:
            values["team"] = Team.objects.get(pk=int(team))

        return values
```

```python
# urls.py
from generic.sites.views import GridView

path("triage/", GridView.as_view(site=site, grid="example.ticket.triage"),
     name="triage"),
# The grid's argument, from the address: one team's tickets.
path("teams/<str:argument>/triage/",
     GridView.as_view(site=site, grid="example.ticket.triage")),
```

| `Grid(...)` | Means |
| --- | --- |
| `name`, `title`, `description`, `icon` | the grid, and its page's title and subtitle |
| `columns` | the columns shown at first — any of `list_display` |
| `editable` | which of the resource's `editable_fields` this grid writes; `None`: all. The endpoint refuses the others |
| `scope` | a method name or a function `(request, queryset, argument)` returning the rows; `None`: every row the reader may see |
| `allow_add` | whether rows may be added (to readers who may add). `True` |
| `add_fields` | fields a new row writes although the grid never changes them afterwards |
| `add_values` | a method name or a function `(request, argument)` returning `{field: value}` — where a shown control starts, or what is set on a column the row does not show. Records or keys |
| `page_length`, `requires_argument` | rows per page; refuse the page without an argument |

The **argument** is whatever follows the grid's name after a colon —
`_grid=example.ticket.triage:3` — read by `GridView` from the address
(`argument` in the URL pattern; override `get_argument()` to read it
elsewhere). It comes from the browser: the scope treats it like any
query parameter. Whatever it raises on one it cannot read — `int("x")`,
a team that is not there — is a **404**, on the page and on the
endpoint (`ARGUMENT_ERRORS`).

**The scope says which rows are shown, not which may be written.** A
ticket closed from the triage stays on screen until the grid reloads,
and stays writable for whoever may change tickets: the permissions
decide what is written, on every request.

The page is `generic/grid.html`. Override
`generic/grid/<app>/<model>/<grid>.html` for one grid — its
`grid_intro` block, wrapped in `<div class="grid-intro">`, is where to
say what the work is — or subclass `GridView` for more context, as the
example does to offer its teams. The example ships it at
`/demo/triage/`, and in the navigation.

A grid is declared once and checked at start-up: a column that is not
in `list_display`, an editable column the resource does not declare, an
added field of another record or a scope that is not a method raises
`ImproperlyConfigured`.

## Fields of another model

A column may belong to a record the row *points at*:

```python
editable_fields = ("hours", "ticket__status")
```

`ticket__status` is a field of **Ticket**, reached from the timesheet
row. The path may walk any single-valued relation, as deep as it likes
(`ticket__customer__segment`).

Three things follow, and they are the point of the feature:

- **The other model's permission decides.** A reader who may change
  timesheets but not tickets gets every other cell and sees that one as
  plain text — and the endpoint refuses it even if they ask anyway.
- **One row, one save.** Cells of several models sent together are one
  transaction: either all of them land or none does.
- **A validation error names the column, not the field.** `status` is
  refused under the name `ticket__status`, so the message lands on the
  cell it was typed in.

A many-valued path is refused at start-up: a row has one record to
write to, and `tickets__title` has none in particular.

## What may not be edited

`editable_fields` raises `ImproperlyConfigured` when it names:

- a column that is not in `list_display` — a cell has to be on the
  table before it can be edited;
- a computed column, a `@display` method or a property — there is
  nothing to write to;
- a field the model does not allow to be written (`editable=False`, an
  automatic key);
- a file field — a cell writes JSON; a file is chosen on the record's
  form ([Files](forms.md#files)).

Each refusal names the resource and the column, at start-up rather
than on a Friday.

## Deciding per row, per reader

```python
class TimeEntryResource(ModelResource):
    def can_edit_column(self, request, column, obj=None):
        # An entry that has been invoiced is not corrected here.
        if column == "hours" and obj is not None and obj.is_invoiced:
            return False

        return True
```

Asked twice: once to decide whether the table offers the column at all,
and again on the way in with the record in hand. The model's change
permission is checked separately and always.

## The write itself

Everything above is the default of one method. Replace it and you
replace the write:

```python
class TimeEntryResource(ModelResource):
    def save_editable(self, request, obj, changes):
        """`changes` is keyed by public column name."""
        if "hours" in changes and obj.is_locked:
            raise serializers.ValidationError(
                {"hours": _("This week is closed.")}
            )

        super().save_editable(request, obj, changes)

        if "ticket__status" in changes:
            notify_the_desk(obj.ticket)
```

The default resolves each column against its record, validates it with
**the same serializer the form uses** — so a cell refuses exactly what
the form refuses — and saves, all inside one transaction. An override
that calls `super()` keeps that and adds to it; one that does not
replaces it entirely.

Because it is an ordinary save, everything downstream still happens:
the change is announced to open tables, the watchers are told, and a
version is recorded in the record's history with the name of whoever
typed it.

## The endpoint

```
PATCH api/<app>/<model>/<pk>/cells/?_grid=example.ticket.triage
{"priority": "urgent", "assignee": 7}

POST api/<app>/<model>/rows/?_related=example.ticket.time_entries:12
{"agent": 7, "hours": "1.25", "spent_on": "2026-09-24"}
```

Both carry the grid they were written in — `_grid` or `_related`, as
the table's rows do — and read from it what the grid allows. The
answer is the **whole row**, as the table would draw it now: changing
one cell often moves another — a total, a tag, a computed column.

| Answer | Means |
| --- | --- |
| `400` | the errors, keyed by column name; for a new row, `detail` holds what the row does not show. Also a column the grid does not edit, or one a new row may not set |
| `403` | a reader who may not change the row, or not add one; a grid that adds no rows |
| `404` | a model with no editable column; a grid nobody declares, or an argument its scope refuses |

## What this is not

It is not a spreadsheet. There is no fill-down, no multi-cell
selection, no undo beyond the history tab. Rows are added one draft at
a time and removed with the *Delete* bulk action; for a handful of
fields on one record, the record's own form still exists and is one
click away.

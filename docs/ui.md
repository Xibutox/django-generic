# The UI layer

Five class-based views, one page layout, one stylesheet. The point is
that a new screen costs a class and a URL, not a template.

```python
from generic.views import GenericListView


class BookListView(GenericListView):
    model = Book
    list_display = ("title", "author", "pages", "is_available")
    search_fields = ("title", "author__name")
    detail_url_name = "book-detail"
    create_url_name = "book-add"
```

That is a complete page: title, breadcrumbs, an "Add book" button that
appears only for users holding `add_book`, a search box, sortable
column headers, pagination, and the light/dark theme.

## The views

| View | Template | Default permission |
| --- | --- | --- |
| `GenericListView` | `generic/list.html` | `<app>.view_<model>` |
| `GenericDetailView` | `generic/detail.html` | `<app>.view_<model>` |
| `GenericCreateView` | `generic/form.html` | `<app>.add_<model>` |
| `GenericUpdateView` | `generic/form.html` | `<app>.change_<model>` |
| `GenericDeleteView` | `generic/delete_confirmation.html` | `<app>.delete_<model>` |
| `DataTableView` | `generic/datatable.html` | `<app>.view_<model>` |

Every one requires authentication. Permissions are derived from the
model, matching Django's own names, so naming the model is usually the
whole configuration. Override with `permission_required`, or set
`require_permission = False` when being signed in is enough.

`require_permission = False` does **not** disable the login check. They
are separate concerns: a page open to every colleague is still not open
to the internet.

## Listings

### Columns

`list_display` works like the admin's. An entry may be a model field, a
method on the view, or `"__str__"`:

```python
list_display = ("title", "author", "published_year")

def published_year(self, book):
    return book.published_on.year if book.published_on else ""

published_year.short_description = _("Published")
```

Labels come from `short_description`, then the model field's
`verbose_name`, then a prettified attribute name. Values render through
the same formatter the detail view uses: booleans become Yes/No, `None`
becomes an em dash, related managers are joined, and everything is
escaped.

### Sorting

Only real model fields among `list_display` are sortable, and only
through a whitelist:

```python
ordering_fields = {"author": "author__name"}   # public name -> ORM path
ordering = ("title",)                          # the default
```

The client sends `?o=-pages`. A name absent from the whitelist is
ignored rather than rejected, so a stale bookmark still renders. Header
links cycle ascending → descending → default, and changing the sort
returns to page 1.

### Search

```python
search_fields = ("title", "author__name")
```

One `icontains` per field, OR'd together, from `?q=`.

### Bulk actions

```python
bulk_actions = (("archive", _("Archive selected")),)

def bulk_action_archive(self, request, queryset):
    queryset.update(archived=True)
```

The handler receives the selected rows and may return a response to
redirect somewhere else, or `None` to return to the listing.

The header checkbox selects the rows **on screen**. Acting on every row
the current filters match is a second, explicit click — the two mean
very different things on page 1 of 400, and conflating them is how
people delete more than they meant to. Either way, "select all" is
bounded by the current filters, never the whole table.

## Detail pages

```python
class BookDetailView(GenericDetailView):
    model = Book
    display_fields = ("title", "author", "genre", "price")
    list_url_name = "book-list"
    update_url_name = "book-change"
    delete_url_name = "book-delete"
```

`display_fields` defaults to every concrete field except the id. A
choice field shows its label, not its stored value. The toolbar builds
Change and Delete buttons from the route names, each hidden unless the
user holds the matching permission.

## Forms

Plain Django `ModelForm` handling, with an admin-style layout on top.

### Fieldsets

```python
class BookUpdateView(GenericUpdateView):
    model = Book
    fields = ("title", "author", "publisher", "price")
    readonly_fields = ("last_indexed",)

    fieldsets = (
        (None, {"fields": ("title", ("author", "publisher"))}),
        ("Commercial", {
            "fields": ("price",),
            "description": "Pricing and availability.",
            "classes": ("collapse",),
        }),
    )

    def last_indexed(self, book):
        return book.index_run.finished_at

    last_indexed.short_description = _("Last indexed")
```

A tuple inside `fields` puts those fields on one row. `classes:
("collapse",)` starts the fieldset closed — **unless it contains a
field with an error**, because hiding the reason a form was rejected is
the one thing collapsing must never do.

Read-only values resolve in order: a method on the view (called with
the instance), a method on the form, then the model — including
`get_FOO_display`.

Without `fieldsets`, every visible field lands in one unnamed group.

### Buttons and redirects

| Button | Name | Goes to |
| --- | --- | --- |
| Save | `_save` | the detail page, else the listing |
| Save and continue editing | `_continue` | back to the form |
| Save and add another | `_addanother` | a blank form |

Set `show_save_and_continue` / `show_save_and_add_another` to `False`
to hide either.

### Pre-filling from a link

`?author=12` on a create URL seeds that field. Only real model fields
are read, so an arbitrary query parameter cannot reach the form.

### Related objects in a popup

A select can open a small window to create the missing option. On save
the window hands the value back to its opener and closes, so a deep
form does not lose what has already been typed. The payload travels
through `json_script`, never interpolated into a script tag.

Inside a popup there is no sidebar, no breadcrumbs, and no "continue
editing" — there is nowhere to continue to.

## Deletion

The confirmation page runs Django's own cascade collector, so what it
lists is what the database would actually do:

- what would be deleted with it, nested;
- a per-model count;
- whether a `PROTECT` or `RESTRICT` relation blocks it.

When something is protected, the confirm button is not rendered and the
page names the culprits. The check runs **again** on POST: the page may
have been open a while, and a relation can appear in the meantime.

## Interactive tables

`DataTableView` renders an empty table plus a configuration, and the
browser fills it from the REST API:

```python
class BookTablePage(DataTableView):
    model = Book
    viewset = BookTableViewSet     # supplies the columns
    api_url_name = "book-list"     # supplies the data
```

The columns come from the same serializer declaration the API filters
against, so the header, the filter controls and the server agree by
construction. See [Data tables](tables.md) for the column options.

The configuration is emitted with `json_script` and read from the DOM.

### What the table gives you

- a search box spanning every searchable column;
- a filter control per column, matched to its type, and a row of search
  fields under the headers on demand;
- a column selector, with the choice remembered per view;
- Excel and CSV exports of **every filtered row**, not just the page;
- saved state — ordering, page length, hidden columns.

### Supplying DataTables

DataTables 3, jQuery and Select2 are vendored and linked by
`generic/datatable.html`. To use another build, or to add a DataTables
extension, replace the `datatable_vendor` block (and the
`datatable_styles` block for the stylesheet); the integration detects
an extension that is present.

```django
{% extends "generic/datatable.html" %}
{% load static %}

{% block datatable_vendor %}
  {{ block.super }}
  <script src="{% static 'vendor/datatables/dataTables.fixedHeader.min.js' %}" defer></script>
{% endblock %}
```

jQuery is there for Select2 only.

If DataTables is missing, the page says so in the error box rather than
showing an empty table with no explanation.

### Translating the controls

The operator labels, the date popover and the placeholders go through
`gettext`. Without Django's JavaScript catalog they fall back to their
English source strings; to translate them, serve the catalog and load
it in the `datatable_i18n` block:

```python
path(
    "jsi18n/",
    JavaScriptCatalog.as_view(packages=["generic"]),
    name="jsi18n",
),
```

```django
{% block datatable_i18n %}
  <script src="{% url 'jsi18n' %}"></script>
{% endblock %}
```

### Filters

The table shows its filters as chips in a bar under the toolbar, added
from the **Filter** button, a column header's funnel, the search row
under the headers, `name:value` words in the search box, or a right
click on a cell. The search row — a field per column — is there from the
start; the button beside *Filter* hides it. `filter_row = "toggle"` on a
`DataTableView` or a resource starts it hidden, `False` removes it. The
editor fits the column type — see
[Sites › Filters](sites.md#filters) for what it offers and the typed
syntax, and [Data tables](tables.md#the-filter-tree) for the tree sent
to the server.

A `ChoiceColumn` sends its choices with the column, so its filter and
its cells both show the label rather than the stored value. Lists of
values come from the endpoint's `facets/` action when the column offers
it, else from its choices, else from its autocomplete route.

Date filters always ask for a **date**, never a time, including on a
datetime column: the server compares a timestamp against the whole of
the chosen day, and offering a time would promise a precision the
filter does not have.

### Overriding the scripts

`datatable_scripts` holds the integration files. Replace the block to
substitute your own build:

```
generic/js/datatables/core.js       translation, operators, defaults, features
generic/js/datatables/columns.js    normalisation and cell renderers
generic/js/datatables/query.js      the filter tree: build, describe, typed syntax
generic/js/datatables/toolbar.js    search, views, columns, exports
generic/js/datatables/filterbar.js  the filter bar, editor, header funnels
generic/js/datatables/filterrow.js  the search row under the headers
generic/js/datatables/selection.js  row selection and bulk actions
generic/js/datatables/rowactions.js the row menu, with quick filters
generic/js/datatables/realtime.js   live refresh
generic/js/datatables/table.js      the controller, which holds the filters
generic/js/datatables/init.js       finds the tables and starts them
```

A page can drive a table's filters through its controller,
`table.genericDataTable`: `addCondition(condition)`,
`setColumnCondition(condition)`, `removeCondition(id)`,
`setFilters(tree)`, `clearFilters()`, then `redraw()`. Every change
dispatches `generic:filters-change` on the table. `setFilterRow(true)`
shows the search row, `setFilterRow(false)` hides it.

A feature (`core.registerFeature`) may add a header row of its own from
`header(controller, thead)`, before DataTables starts — DataTables then
hides and shows its cells with their columns — and keep something in
the table's remembered state with `saveState(controller, data)` and
`loadState(controller, data)`.

They expose `window.GenericDataTables` and, for pages that build a
table by hand, `window.DrfDataTable`.

### Events

| Event | When |
| --- | --- |
| `generic:datatable-ready` | a table finished initialising |
| `generic:datatable-error` | it failed to start, or a request was rejected |
| `generic:datatables-loaded` | on `document`, once `window.GenericDataTables.start` exists - for a script deferred before the tables' own |

Both bubble, so one listener on `document` covers every table.

## Templates

```
generic/
├── base.html                     layout, header, sidebar, messages
├── list.html  detail.html  form.html
├── delete_confirmation.html  datatable.html
├── sidebar.html                  override this for your navigation
├── popup_response.html
└── components/
    ├── breadcrumbs.html  messages.html  toolbar.html  toolbar_item.html
    ├── search_form.html  actions.html   pagination.html
    ├── object_table.html fieldset.html  submit_row.html
    ├── deletion_tree.html theme_toggle.html
```

Every page extends `generic/base.html`. Useful blocks: `title`,
`branding`, `usertools`, `sidebar`, `breadcrumbs`, `page_header`,
`content`, `extrastyle`, `extrahead`, `scripts`, `extrajs`.

To restyle one thing everywhere, override the component: a
`templates/generic/components/toolbar.html` in your project wins over
the packaged one.

### The page toolbar

The buttons beside the title are `ToolbarItem`s — a view's
`get_toolbar_items()`, a record's `get_record_links()` plus *View on
site*, *Delete* and *Edit*. However many there are, they stay on **one
line**: what does not fit goes behind a **⋯** button, as a menu.

- Buttons fold from the **end of the list backwards**, so the first
  ones — the pages a project built around the record — are the last to
  go, and *Delete*, near the end, the first.
- The **primary** button never folds, and the ⋯ button sits just
  before it, so *Edit* keeps the end of the bar.
- The header gives the toolbar what the title leaves. When even the
  pinned buttons do not fit beside the title, the toolbar moves under
  it, and has the whole line. On a phone it always does.

`placement` overrides this for one button:

```python
ToolbarItem(url=..., label="Board", placement="bar")    # never folds
ToolbarItem(url=..., label="Audit", placement="menu")   # always in ⋯
ToolbarItem(url=..., label="Edit", variant="primary")   # "auto": pinned
```

The server draws every button, and those that may fold a second time
in the menu. The browser only chooses which of the two shows, by
measuring (`pageToolbar`, in `ui.js`), again whenever the header's
width changes. Without script the bar wraps onto several lines, as it
used to.

Navigation is yours. Override `sidebar.html`, or supply
`sidebar_sections` from a context processor:

```python
{"sidebar_sections": [
    {"label": "Catalogue", "items": [
        {"label": "Books", "url": "/books/", "is_current": True},
    ]},
]}
```

### Context vocabulary

Every generic view provides the same names, so a template never has to
ask which view rendered it: `page_title`, `page_subtitle`,
`breadcrumbs`, `toolbar_items`, `is_popup`, `show_sidebar`. Listings add
`table`, `search_term`, `ordering_state`, `bulk_actions`, `total_count`.

## Styling

```
css/tokens.css      every colour, space and radius
css/base.css        reset, layout, header, sidebar, breadcrumbs
css/components.css  buttons, modules, messages, callouts, icons
css/forms.css       fieldsets, inputs, validation, submit row
css/tables.css      listings, sorting, actions, pagination
css/datatables.css  DataTables skin
```

Nothing outside `tokens.css` hard-codes a colour. To rebrand, redefine
the tokens — no override stylesheet fighting specificity, no forked
templates:

```css
:root {
  --color-accent: #6b46c1;
  --border-radius: 2px;
}
```

Three theme states: light, dark, and system. An explicit choice wins
over `prefers-color-scheme` in both directions. The stored preference is
applied to `<html>` inline in `base.html` before first paint, so the
page never flashes the wrong theme — the same trick keeps a collapsed
sidebar from flashing open.

**One control height.** `--control-height` is what a button, a select,
a Select2 field and a text input all measure. A text input used to be
the exception — its padding made it 39px against everyone else's 36 —
so two fields side by side did not line up. Single-line controls now
take the token as their `height` and keep their padding horizontal;
textareas, multiple selects and file inputs keep theirs, because their
content is not one line.

Two tokens exist for text on a filled surface, and the difference
matters. `--text-inverse` is text on an accent or danger fill, and
flips with the theme. `--text-on-header` is text on the header, which
is dark in *both* themes — using `--text-inverse` there renders dark on
dark and the header disappears.

The sidebar's default differs by width: above 1024px it sits beside the
content and starts open; below, it overlays the content and starts
closed. That is why two classes exist (`sidebar-open` and
`sidebar-closed`) rather than one — with neither, each breakpoint still
gets the right default, including with JavaScript disabled. The
remembered choice belongs to the wide layout and is applied there only:
carried onto a phone it would open the menu over the page.

`prefers-reduced-motion` is respected.

### Size

Every token is in `rem`, and the root font size is the browser's own:
the type, the spacing, the controls and the frame - `--sidebar-width`
and `--header-height` included - follow a reader who asked their
browser for larger text, and the browser's zoom enlarges the rest. The
application has no size setting of its own; a system that scales its
display (125%, 150%) is answered by the layout's breakpoints, as it
should be.

A project that wants its whole interface a little smaller or larger
sets the root size in its own stylesheet:

```css
html { font-size: 95%; }
```

### The frame: name, navigation, pin

The top bar carries the application's name and icon on every page,
linking home — `GENERIC["SITE_HEADER"]`, or `SITE_TITLE` — beside the
breadcrumbs. Override the `topbar_brand` block to put something else
there.

The navigation answers two questions, remembered apart in the browser:

| State | Class on `<html>` | Means |
| --- | --- | --- |
| open / closed | `sidebar-open` / `sidebar-closed` | Is the column on screen — the button in the bar |
| pinned / not | `sidebar-unpinned` when not | Does it hold the page open, or float over it |
| peeking | `sidebar-peeking` | The floating panel is out |

**Pinned** (the default) it is a column: the page starts beside it, and
the button in the bar hides and shows it.

The pin sits **in the top bar**, beside that button, and not inside the
navigation: floating, the navigation is exactly what is missing, and a
pin that travelled with it could only be reached once it was already
open. For the same reason the floating panel stops below the bar rather
than covering it.

Pinning also saves `UserPreferences.navigation`, so the choice follows
the user to another machine, and the preferences page offers the same
choice in words. The browser's own last choice wins over it, the way
the theme works.

**Unpinned** — the pin beside the navigation's title — the page takes
the whole width and the navigation becomes a panel parked outside the
viewport. Two ways bring it back, and they differ in how long it stays:

- The strip along the left edge (`.sidebar-edge`) slides it out on
  hover, for as long as the pointer stays within its width. A grip on
  the border marks where the strip is.
- The button in the bar opens it and **holds** it there. A click
  elsewhere, Escape, or the button again dismisses it.

A click on the strip pins the navigation back, as does the pin in the
bar.

Open and closed describe the pinned column only. Unpinned, the panel is
never hidden outright — `display: none` would leave the strip nothing to
bring back, and take the pin away with it. That is enforced in the
stylesheet, not only in the script, so a "closed" remembered from a
pinned visit cannot strand the navigation.

Floating is a wide-screen idea: below the breakpoint the navigation is
already a panel the bar's button opens over the page, so the pin and the
strip are not drawn there and `sidebar-unpinned` changes nothing.

Both states are written onto `<html>` before the first paint, so a page
never opens with the navigation in the wrong place. `ui.js` changes
them and `localStorage` remembers: `generic.sidebar` and
`generic.sidebar-pinned`.

What decides whether a peek stays out is where the pointer *is*, not
what it entered: the panel slides out to meet a pointer that need not
move again, and a browser only hit-tests on a move, so waiting for
`mouseenter` on the panel closed it under a pointer already resting on
it.

### Help, licence and changelog

Two pages the frame offers from the account menu, both reading files the
project already keeps rather than asking for the same thing twice:

- **Help** (`site:help`) — the application's name and version, a
  paragraph of its own (`HELP_TEXT`), links (`HELP_LINKS`), the licence
  read from `LICENSE` at the root of the project, the newest release,
  and the keyboard shortcuts.
- **What changed** (`site:changelog`) — every release of every
  `CHANGELOG.md` found, the application's first and the framework's
  after it, parsed as [Keep a Changelog](https://keepachangelog.com):
  `## [1.4.0] - 2026-09-18`, then `### Added`, then the items. An item
  wrapped over two lines stays one item; a paragraph between headings
  stays with its release; anything unrecognised is kept rather than
  dropped.

```python
GENERIC = {
    "VERSION": "1.4.0",
    "LICENSE_FILE": None,        # LICENSE, LICENSE.md, LICENSE.txt, LICENCE
    "CHANGELOG_FILES": None,     # CHANGELOG.md at the root, then the framework's
    "HELP_LINKS": [{"label": "Handbook", "url": "...", "icon": "book"}],
}
```

Nothing is rendered as HTML: the files are shown as the text they are,
so a changelog is never a way into the page.

## JavaScript

Small files, no build step, no framework:

| File | Does |
| --- | --- |
| `core.js` | `window.Generic`: config, api, toasts, theme, appearance, colours |
| `ui.js` | the frame: navigation, its pin, the filter, Alpine components |
| `events.js` | the shared WebSocket |
| `maintenance.js` | the banner of a planned restart, and its countdown |
| `theme.js` | cycles light → dark → system, remembers the choice |
| `messages.js` | dismisses; auto-hides success and info only |
| `actions.js` | bulk selection and the select-across step |
| `collapse.js` | collapsible fieldsets, never over an error |
| `datatables/` | the DataTables integration, eleven files |
| `forms/` | the schema form, its inlines and its widgets |

Warnings and errors never auto-hide: they usually describe something
the user still has to act on.

Every `localStorage` access is wrapped — a private window or blocked
site data must not break the page, only lose the preference.

## Accessibility

- A skip link, and one `<h1>` per page.
- Sortable headers carry `aria-sort`; the arrow is decorative.
- Messages live in an `aria-live` region.
- Toolbar buttons that are disabled use `aria-disabled`, not a dead
  link.
- Icon-only buttons carry an `sr-only` label.
- Focus is always visible, through a token so the ring is themeable.
- Wide tables scroll inside their own box; the page never scrolls
  sideways.

## What this layer is not

It is not a replacement for `django.contrib.admin`. Keep the admin for
staff and DBA work. These views are for the screens your users see,
where you control the wording, the permissions and the workflow.

# Pages from the model: `auto`

A `ModelResource` says everything by hand — the columns, the search, the
form, the related tables — and that is the way to a page shaped exactly
as the work needs it. `auto` is the other way: **one line, and the model
says the rest.**

```python
# myapp/resources.py
from generic.sites import auto

auto(Supplier, related=("equipment",))
auto(Equipment, related=("maintenances",))
```

Each line gives the model what a hand-written resource does:

- the five pages — **list**, **summary**, **add**, **change**,
  **delete** (the delete page previews what goes with the record, and
  refuses when something protected depends on it);
- its REST endpoint, its place in the navigation, the command palette,
  the history of every record, the live updates, the *Watch* button;
- and a declaration worked out from the model — below.

The example's *Equipment* group is exactly these two lines
(`example/resources.py`), over three models nobody wrote a page for.

## What is worked out

| Declaration | From the model |
| --- | --- |
| `list_display` | the field that names a row first — `name`, `title`, `label`, `reference`, `code`… or else the first plain text field — then the others in the model's order, at most `max_columns` (7). Left out: long text, JSON, files, UUIDs, anything named like a secret (`password`, `token`, `secret`, `api_key`, `hash`), values nobody writes — except a date the application keeps, such as `created_at` |
| `search_fields` | the text fields (the naming one first), then the name of each record a row points at: `supplier__name` |
| `tag_fields` | every field with choices, drawn as a coloured tag — one colour a choice, in the order they are declared |
| `fieldsets` | the naming field alone, then the short fields **two a row**, long text and many-to-many fields the whole width underneath |
| `detail_fieldsets` | the form's rows, plus the dates the application keeps |
| `icon` | from the words of the model's name — `Equipment` is `devices`, `MaintenanceVisit` is `build`, `Invoice` is `receipt_long`; `table_rows` otherwise |
| `related_tables`, `inlines` | from `related` — below |

The columns keep every filter, sort and export a declared column has:
they *are* declared columns, only by the framework.

## Related rows: the one thing to say

The framework never guesses which related rows matter: a model is
reached by relations it does not care about. `related` names them, by
the name the model reaches them by — a reverse foreign key's
`related_name`, a many-to-many:

```python
auto(Equipment, related=("maintenances",))
```

For each one:

- **A table on the summary page** — the related model's own table, its
  columns, filters, search and export, narrowed to the record, with an
  *Add* button filling the record in.
- **A tab of rows on the form**, for a reverse foreign key: the related
  rows added, changed and removed with the record, in one save. The row
  shows every field it cannot be saved without — long text included —
  then the others that fit, up to six.
- **Pages of its own for the related model**, if nobody declared it:
  worked out the same way, and kept **out of the navigation** — a
  maintenance visit is reached from its equipment. Declared by hand or
  with `auto` anywhere in the project, it keeps its own declaration:
  this is decided once every `resources.py` has been read.

A relation with hundreds of rows per record is a table, not a tab: a
form should not carry them all.

```python
auto(Customer, related=("tickets", "invoices"), related_inlines=("invoices",))
```

A name that is not a relation is an error at start-up, listing the ones
the model has; so is a relation to one record (`supplier` — it is a
column already).

## Saying a little more

Anything declared wins over what is worked out, and the rest is still
worked out:

```python
auto(
    Equipment,
    related=("maintenances",),
    group=_("Equipment"),         # the navigation group
    exclude=("notes",),           # out of the list, the search and the form
    list_display=("name", "state", "supplier"),
)
```

Or as a class, for a method or two:

```python
from generic.sites import AutoResource, register

@register(Equipment)
class EquipmentResource(AutoResource):
    related = ("maintenances",)
    icon = "laptop"

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(state="retired")
```

| `AutoResource` attribute | Default | Means |
| --- | --- | --- |
| `related` | `()` | relations shown as tables, and edited as tabs |
| `related_inlines` | `None` | which of `related` are tabs on the form: `None` every reverse foreign key, `()` none |
| `max_columns` | `7` | columns the list shows at first |
| `tag_choices` | `True` | choices drawn as coloured tags |

Every `ModelResource` attribute and hook is there too — `actions`,
`charts`, `editable_fields`, `grids`, permissions. An `AutoResource` *is*
a resource: when the page needs to be shaped by hand, declare what it
needs and keep the rest, or move to a `ModelResource` when little is
left worked out.

`site.auto(...)` does the same on a site of your own; `auto(...,
site=...)` too.

## When to use which

| `auto` | `ModelResource` |
| --- | --- |
| reference data, back-office tables, the first version of anything | the screens the application is used through |
| "a list and a form will do" | columns chosen for the work, computed values, charts, presets |
| a model that changes often: nothing to keep in step | a page whose shape is a decision |

Both live side by side in one project, and in one `resources.py`: the
example's support desk is declared by hand, its equipment with `auto`.

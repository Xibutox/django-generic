# Custom fields

Fields people add to a model while the application runs, without a
developer or a migration: a warranty end on the equipment, a colour, a
weight in kilograms. Whoever holds the model's *customize* permission
adds them from the list's *Customize fields*; every screen and endpoint
of the model then treats them as its own:

- a control in the add and edit forms, in a section of their own;
- a line of the record's summary page;
- a column of the table - shown, filtered, sorted, searched, counted in
  the filter editor, exported;
- a key of the record in the API, validated like a field of the model;
- a part of the record's history: a save changing the title and a
  custom value is **one** version listing both, and *Undo* puts the
  values back with the rest of the record.

```python
from generic.sites import ModelResource, auto, register
from generic.customfields import CustomFields


@register(Equipment)
class EquipmentResource(ModelResource):
    custom_fields = True


# or, with options
@register(Supplier)
class SupplierResource(ModelResource):
    custom_fields = CustomFields(
        section=_("Characteristics"),        # the form's and summary's section
        types=("text", "decimal", "date", "choice"),   # the types offered
        max_fields=30,                       # default CUSTOM_FIELDS_MAX_PER_MODEL
        permission=None,                     # default <app>.customize_<model>
    )


# in auto mode, the same option
auto(Equipment, related=("maintenances",), custom_fields=True)
```

Off by default, `auto` included. A value other than `True`, `False` or
a `CustomFields(...)` raises where it is declared; so does an unknown
type in `types`.

## Who does what

| Who | May |
| --- | --- |
| Holder of `<app>.customize_<model>` (*Can customize &lt;model&gt;*) | add, change, reorder, archive, restore and delete that model's fields |
| A superuser | the same, on every model open to them |
| A reader of a record | see its custom values, except a field whose *permission to see it* they lack |
| An editor of a record | change its custom values, except a field whose *permission to change it* they lack |

The permission is created after every `migrate` for each model open to
custom fields, on the model's own content type: a group's form lists it
beside *Can change &lt;model&gt;*. `CustomFields(permission="app.codename")`
names another one instead, and then none is created.

A field's own *permission to see it* and *permission to change it*
work like [`field_permissions`](field-permissions.md): a field the reader
may not see is left out of the table, its filters, the search, the
exports, the form, the summary, the history and the API; one they may
not change is read only, and refused by every write.

## The fields

*Customize fields*, a button of the model's list shown only to whoever
holds its *customize* permission, opens the list
of its fields: `/generic/customfield/`, filtered on the model, with the
filters, exports and history of any list. Its form asks:

| Question | Meaning |
| --- | --- |
| Model | the records it is added to; fixed once created |
| Type | below; fixed once records hold values (add a new field instead) |
| Key | how tables, the API and the history call it, after `cf_`: lowercase letters, digits and `_`; fixed once created |
| Label, help text | one of each per language of `LANGUAGES`; the label is required in the project's language |
| Required, default value | asked at every save from a form - records saved before are left as they are; what a new record's form starts with |
| Shortest, longest | for the texts |
| Minimum, maximum | for numbers, dates and times (`0`, `2026-01-31`, `08:30`) |
| Decimal places, unit | a decimal's places (0 to 6); a unit shown after numbers (`kg`, `h`, `%`) |
| Choices | a choice's list, below |
| Position, shown in the table | its order; whether the table shows it from the start or only offers it in the column selector |
| Permission to see it, to change it | `app.codename`, empty for the record's own |
| Archived | hidden everywhere, values and history kept; *Restore* brings it back |

| Type | Control | Column | Filter |
| --- | --- | --- | --- |
| Text, long text, e-mail address, web address | input, textarea | text | contains, is, starts with, empty; in the search |
| Whole number, decimal number | number | number, with the unit in its title | comparisons, between, empty |
| Yes/no | switch | yes/no | yes, no, empty |
| Date, date and time | date picker | date | between, relative periods, empty |
| Time | time | text | none (ordered only) |
| Choice | list | coloured tag | any of, none of, with counts |

A choice's list is written a line per choice: its value, its label, its
label in other languages and its colour, separated by `|`:

```
black  | Black  | fr: Noir   | #1f2937
silver | Silver | fr: Argent | #94a3b8
white
```

A line of one word is its own value and label; a choice without a colour
takes one of the palette. The value is what is stored: a label may be
renamed at any time, a value still held by a record cannot be removed.

Deleting a field deletes its values for good (the records' history
keeps what they were); archiving is what to do first.

## Where the values live

Two tables of the framework, whatever the number of models:
`generic.CustomField`, a row per field, and `generic.CustomValue`, a row
per field and record holding the value in a column of its type
(`value_text`, `value_integer`, `value_decimal`, `value_bool`,
`value_date`, `value_time`, `value_datetime`). An empty value is no
row. Nothing is added to the project's own tables.

A table's queryset carries each custom field it shows as an annotation
named like its column (`cf_<key>`, a subquery on an indexed pair): the
cell, the filter, the order and the facets read it, and a page of rows
costs no query more. A record read on its own - a form, a summary -
loads its values in one query.

```python
from generic.customfields.values import load, write

resource = site.get_resource(Equipment)
write(resource, laptop, {"warranty_ends": date(2028, 3, 1), "colour": None})
load(resource, laptop)          # {"warranty_ends": date(2028, 3, 1)}
```

`write` sets the keys given (empty clears) and records the change in
the record's history, folded into the unit of work it belongs to - a
request, an `acting_as` block. A record deleted takes its values with
it; its last version keeps them, and *Undo* puts them back.

In a version of the record, a value is kept under `cf:<key>`. A save of
the record carries the custom values forward, like many-to-many fields;
so do bulk writes and, on PostgreSQL, the
[`generic_history` trigger](history.md#writes-outside-the-application-postgresql).
A value written straight into `generic_customvalue` from outside the
application is not versioned.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `CUSTOM_FIELDS` | `True` | `False` turns custom fields off everywhere; the values written are kept |
| `CUSTOM_FIELDS_MAX_PER_MODEL` | `50` | the most fields a model may have; `CustomFields(max_fields=)` per resource |

`manage.py check` warns (`generic.W013`) when a resource opens its model
to custom fields but keeps no history.

## Not yet

Editing custom values in a table's cells and grids, bulk edit, imports,
comparing records, the chart builder and outlines do not offer them
yet. A record's primary key is matched as text: integer and text keys
everywhere, UUID keys on PostgreSQL.

## In the example

The equipment (`auto(Equipment, ..., custom_fields=True)`) is seeded
with two fields: *Warranty ends*, a date, and *Colour*, a choice in the
column selector. Sign in as `admin`, open *Equipment*, then
*Customize fields*.

The ISO 27001 apps (`iso/README.md`) open the main record of each app
to custom fields; `seed_iso` adds *Warranty ends* on the assets and
*Where the data is kept* on the suppliers.

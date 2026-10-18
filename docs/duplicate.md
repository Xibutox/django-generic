# Duplicating records

A record copied into a new one: *Duplicate* opens the add form already
filled with the record's values, every one still editable, and a *Copy
with it* section where the reader ticks which related records come
along. Nothing is written until the form is saved.

```python
from generic.sites import Duplicate, ModelResource, register


@register(Ticket)
class TicketResource(ModelResource):
    # The form's fields, its many-to-many values and its inline rows.
    duplicate = True


@register(Article)
class ArticleResource(ModelResource):
    duplicate = Duplicate(
        exclude=("unit_cost",),        # left to its default in the copy
        related=("bom_lines",),        # copied on request, server side
        values={"kind": "assembly"},   # or callable(request, obj) -> dict
        permission=None,               # besides the add permission
    )
```

Off by default on a `ModelResource`, on by default on an `AutoResource`
(`auto(Equipment)` duplicates; `auto(Equipment, duplicate=False)` does
not).

## Where it is offered

- A record's summary page: *Duplicate* beside *Delete* and *Edit*.
- Each row's menu in the list (and in a related table of the record).
- The change form, when records open on their form
  (`object_page = "change"`).

To readers holding the add permission and the record's view permission
(`can_duplicate(request, obj)`), plus the declaration's `permission`:
a permission string, or `callable(request, obj) -> bool`.

The page is `<app>/<model>/<pk>/duplicate/` (`site:<app>_<model>_duplicate`,
`resource.get_duplicate_url(pk)`). A page of the project's own named
`duplicate` on a record is refused at registration while `duplicate`
is on.

## What the form opens with

The record as the reader's own form serializer reads it
(`get_form_serializer_for(request)`), so `field_permissions` apply: a
field they may not see, or may see but not change, is not copied - the
copy takes its default, as a new record would. Also left out:

- unique fields (a reference, a code): the copy would be refused - the
  reader types the new one;
- files: the copy would share a stored file nobody chose for it;
- read-only fields, `transitions` state fields, `exclude`.

`values` then overrides what it names. For more, override the hook:

```python
def get_duplicate_initial(self, request, obj):
    initial = super().get_duplicate_initial(request, obj)
    initial["values"]["title"] = f"{obj.title} (2)"
    return initial
```

`initial` holds `values` and their `display` labels by field, `inlines`
rows by inline name, and the `copies` offered.

## Copy with it

One box per relation the copy may hold, its count beside it:

| Kind | What it is | Ticked | Unticked |
| --- | --- | --- | --- |
| a many-to-many field of the form | the record's values (tags...) | the field holds them, editable | the field is emptied |
| an inline | the record's rows (milestones, comments...) | the form holds them as new rows, editable, removable | no rows |
| a `related` relation | records the form does not carry (a bill of materials, hundreds of lines) | copied once the new record is saved | nothing copied |

Many-to-many fields and inlines start ticked; `related` relations start
unticked, since they may be many. A relation of more than
`MAX_COPIED_ROWS` (500) records is shown, disabled. A relation is
offered only to readers who may add its records (the related
resource's add permission), and only the records they may see are
copied (its `get_queryset(request)`).

`related` names reverse foreign keys - the `related_name` of a key
pointing at the model - whose model is registered. An inline cannot be
named there (its rows are on the form already); anything else raises
`ImproperlyConfigured` at registration.

## The write

The form posts to the resource's own endpoint, like any new record,
naming its source:

```json
POST api/example/article/
{"reference": "BK-2", "name": "City bicycle, blue", ...,
 "_inlines": {...},
 "_duplicate": {"source": 12, "related": ["bom_lines"]}}
```

The endpoint finds the source in `get_queryset(request)` (404), asks
`can_duplicate(request, source)` (403) and refuses a relation the
declaration does not name (400), before anything is written. Then, in
one transaction: the record through its form serializer and
`save_model`, its inline rows, and `save_duplicate(request, source,
target, related)`, which copies each ticked relation's records through
the related resource's own form serializer and `save_model` - unique
fields and files left out there too, the key pointing at the new
record. A related record its form refuses (`ValidationError`), or a
missing add permission, rolls everything back, the new record with it;
the answer names the records refused under `_duplicate`.

`save_duplicate` is the reprogrammable step: override it to copy
something else too, or to refuse.

## Wikis

A wiki page and a whole wiki are duplicated too - see
[the wiki](wiki.md#duplicating).

## Example

- *Support › Tickets*: a ticket's page, *Duplicate* - its tags and
  comments ticked, the reference to fill in.
- *Manufacturing › Articles*: *City bicycle*, *Duplicate*, tick *BOM
  lines*: the copy has the same bill of materials. Signed in as an
  account without `change_article`, the unit cost is not copied.
- *Equipment*: every device, through `auto()`.

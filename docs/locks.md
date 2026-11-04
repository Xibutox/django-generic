# Locking records

A record that locks: once one of its fields says so - *released*,
*sent*, *closed* - its values can no longer change, nor its related
records, nor can it be deleted, until that field says otherwise. One
declaration on the resource, and every screen and endpoint obeys it.

```python
from generic.sites import Lock, ModelResource, register


@register(Article)
class ArticleResource(ModelResource):
    # Released: nothing changes but the cost (and the flag itself), the
    # bill of materials locks with it.
    lock = Lock("released", exclude=("unit_cost",), related=("bom_lines",))


@register(Invoice)
class InvoiceResource(ModelResource):
    lock = Lock(
        "status",                         # the field that decides
        values=("sent", "paid"),          # locked in these states
        fields=None,                      # what freezes: None = all
        exclude=("notes",),               # still written while locked
        related=("lines", "payments"),    # their records lock too
        delete=True,                      # nor may it be deleted
        permission="billing.unlock_invoice",  # who it does not hold back
        message=_("A sent invoice cannot be changed."),
    )


@register(TimeEntry)
class TimeEntryResource(ModelResource):
    # Read on the record it points at: a closed ticket's time is final.
    lock = Lock("ticket__status", values=("closed",))
```

Off by default (`lock = None`). The example locks its released
articles: *Manufacturing › Articles*, tick *Released* on one.

## The declaration

| Option | Default | Meaning |
| --- | --- | --- |
| `field` | (required) | The field saying whether the record is locked: one of its own, or a path through foreign keys (`"order__is_closed"`) - never through a many-valued relation. |
| `values` | `None` | The values that lock it. `None`: any value set - `True` for a boolean, neither null nor empty otherwise (a `sent_at` date, a `signed_by` key). |
| `fields` | `None` | What freezes while locked: field names, many-to-many fields, and inlines by their name (the related name). `None`: every one of them. |
| `exclude` | `()` | What is still written while locked: a comment, a cost. |
| `related` | `()` | One-to-many relations (their related names) whose records lock with it - see below. |
| `delete` | `True` | A locked record is not deleted. `False` lets it go (its related records still refuse their own delete). |
| `permission` | `None` | Who the lock does not hold back: a permission string, or `callable(request, obj) -> bool` (`obj` is None for a record being created). |
| `message` | *This record is locked: it cannot be changed.* | What every refusal says, and what the record's page and form show. |

Checked at registration (`resource.get_lock()`): an unknown field, a
path through a value or a many-valued relation, a name in `fields` or
`exclude` the model does not have, a `related` name that is not a
foreign key pointing at the model, or a string where a tuple is
expected raise `ImproperlyConfigured`.

**The lock's own field is never frozen**: unlocking is changing it. So
who may lock and unlock is whoever may change that field - guard it
with [`field_permissions`](field-permissions.md) to keep it for a few:

```python
field_permissions = {"released": (None, "example.release_article")}
```

A `transitions` state field as the lock's field keeps its transitions:
`Lock("status", values=("closed",))` leaves *Reopen* on a closed ticket.

## What it refuses

While a record is locked for a reader, every write of the framework
refuses to change a frozen field, with the lock's message under it:

| Write | What happens |
| --- | --- |
| The form (`PATCH`/`PUT api/<app>/<model>/<pk>/`) | 400, the message under each frozen field that changed. Values sent unchanged pass: a whole form sent back is no change. |
| The change page | Frozen fields and inlines drawn read only, the message on top; a record locked whole opens read only and its page has no *Edit*. |
| Inline rows of the form | Read only; rows sent anyway are refused (400). |
| A grid's cells (`cells/`), a board or calendar move | Refused (400) - the column is not writable on that row. A column through a relation (`customer__name`) obeys the lock of the record it writes. |
| A bulk edit | The record counted *refused*, named with the fields it keeps. |
| An import (update mode) | The row refused, with the message. |
| A transition | Not offered, and refused (403), when the lock freezes its state field. |
| Delete (API, delete page, *Delete* in a selection) | 403 with the message; a selection holding a locked record deletes nothing and says how many are locked. The record's page offers no *Delete*. |
| *Duplicate* | Allowed - nothing changes. The copy starts unlocked: the lock's own field takes its default. |

The check sits in the form serializer every write validates through
(`get_form_serializer_for(request)`, and a cell's serializer), so a
project's own `save_model`, `save_editable` or `create_editable`
override is covered as long as it validates through them.
`may_write_column(request, column, obj)` answers False for a frozen
column, `may_delete(request, obj)` False for a record the lock keeps.

## Related records

`related=("bom_lines",)` locks each BOM line of a locked article, as if
the line's own resource declared `Lock("parent__released")`: all of its
fields freeze, it is not deleted, and its page has nothing left to
edit. The same relation as an inline of the form is read only.

A record *put under* a locked one is refused on the key that does it:
a new BOM line pointing at a released article, or a line moved to it,
is refused under `parent` (400) - from the form, a grid's *Add a row*
or a calendar drop. A lock read through a relation
(`Lock("ticket__status", values=("closed",))`) refuses the same way.

## Reading it

| Method | Answers |
| --- | --- |
| `resource.get_record_lock(request, obj)` | A `LockState`: false when nothing holds the record; `message`, `delete`, `everything` (nothing at all may be written), `freezes(name)`, `as_client()`. |
| `resource.is_locked(request, obj)` | Whether a lock holds `obj` back from this reader. |
| `resource.may_delete(request, obj)` | `has_delete_permission`, and not a record its lock keeps. |
| `resource.unlocked(request, queryset, delete=False)` | The queryset without the locked records (with `delete`: without the ones kept from deletion). |

The summary JSON carries `lock` (`null`, or `{locked, message,
fields, except, delete, everything}`: `fields` null means every field
but `except`); the change form's config carries the same.

## What it does not cover

A lock is the framework's rule, not the database's. A
`queryset.update()` in a bulk action of the project's own, a shell, a
migration or the Django admin still write. An action narrows its
selection first:

```python
@action(description=_("Reprice"))
def reprice(self, request, queryset):
    count = self.unlocked(request, queryset).update(unit_cost=F("unit_cost") * 2)
    announce(self, "bulk")
    return _("%(count)s repriced.") % {"count": count}
```

The lock is per record and per reader; the list's cells of a locked
row still look editable, and refuse the write with the message.

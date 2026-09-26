# History

Every record of every registered model keeps its versions. A **History**
tab on the record's page reads them back: what changed, who changed it
and when, and — on demand — the whole record as any earlier version
held it.

Nothing is declared to make this work. A model that is registered has a
history; `history = False` on its resource takes it away.

## What a user sees

A line at the top of the record's summary:

> *Changed by Camille Rousseau, 21 September 2026 09:57* — See the history

and, in the tabs beside the related tables, **History**:

```
Changed   admin   21 September 2026 09:57   version 2
    Responsible   —              → Yanis Bertrand
    Status        Closed         → Open
    Show this version in full

Created   Camille Rousseau   9 September 2026 21:45   version 1
    Show this version in full
```

*Show this version in full* lists every recorded field as that version
held it. *Show older* fetches the next page; the tab fetches nothing at
all until it is opened.

There is also a **Changes** page, under *History* in the navigation:
every recorded change of every model, with the filters, the search and
the exports of any other table. It is a different door with a different
key — see [Who may read it](#who-may-read-it).

## A version is a snapshot

An entry holds the record's fields **as they were**, not the difference
from the version before. The difference is worked out when the history
is read, by comparing an entry with the one before it. Two things
follow, and both are the reason for it:

- A field the project starts or stops tracking never rewrites the past.
  Old entries simply hold fewer fields.
- Any version can be shown in full, which a stored diff could not do
  without replaying every entry since the first.

A page of history therefore asks the database for one entry more than
it shows, so the oldest one on the page still has something to be a
change from.

## What is recorded

The model's **own** fields: its columns and its many-to-many fields. Not
its reverse relations — a ticket's comments are records of their own,
each with a history where they live.

| Written when | Kept as |
| --- | --- |
| A record is created | `created`, version 1, every field |
| A record is saved with something different on it | `updated`, the next version |
| A record is saved with nothing different on it | *nothing* |
| A many-to-many field is added to, removed from or cleared | the field's new state |
| A record is deleted | `deleted`, holding what it last was |

A deletion's entry outlives the record, which is the point: it is the
one thing nobody can go and look at.

### One unit of work is one version

A form that saves a record and then its tags made **one** change, and a
history saying so twice is a history nobody reads. Every save inside one
request, or inside one `acting_as` block, folds into a single entry.
Outside either, each save stands alone.

### What leaves no history

`QuerySet.update()`, `bulk_create()` and `bulk_update()` fire no signal,
so they record nothing — the same caveat as the live tables and the
watches. Save the rows, or write the entry yourself with
`generic.history.record`.

A many-to-many set from the far end (`tag.tickets.add(ticket)`) records
nothing either: the record that changed is at the other end of the
relation, and reaching back to it would cost a query per row on every
link. Set it from the record's own side.

## Who did it

A signal has no request. The acting user is ambient, and there are two
ways to set it:

```python
# settings.py — after the authentication middleware
MIDDLEWARE = [
    ...
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "generic.middleware.CurrentUserMiddleware",
    ...
]
```

```python
from generic.history import acting_as

with acting_as(user, source="Nightly import"):
    ticket.status = "closed"
    ticket.save()
```

Without the middleware the framework still records *what* changed and
*when*; only the *who* is missing, which is most of the point. A task
run sets it for you — whatever a `@managed_task` writes is recorded as
that task's doing, and as the person's where one asked for it.

The person's name is copied onto the entry as well as linked, so a
deleted account still leaves a readable history.

## From code

```python
from generic.history import HistoryEntry, acting_as, history_of, prune

history_of(ticket)              # every entry, newest first
history_of(ticket).count()

HistoryEntry.objects.of(Ticket) # every entry of every ticket
prune(days=365)                 # delete what is older than a year
```

## Turning it off, or trimming it

```python
class TicketResource(ModelResource):
    # Keep versions of this model at all. False for models the
    # application writes constantly, whose history is noise.
    history = True

    # Fields left out of the version. A field nobody should read twice
    # belongs here: the tab shows what was recorded, whatever the form
    # shows.
    history_exclude = ("api_token",)
```

`history_exclude` is also how a churning column is kept from writing a
version of its row every few seconds. The framework does it to the
scheduler's own screens:

```python
class PeriodicTaskResource(ModelResource):
    history_exclude = ("last_run_at", "total_run_count", "date_changed")
```

Those three change on every tick; the rest — who disabled a schedule,
who changed its hour — is exactly what a history is for. Because a save
that changes nothing recorded writes nothing, excluding them means the
ticks leave no trace at all.

Project-wide:

| Setting | Default | Means |
| --- | --- | --- |
| `HISTORY` | `True` | Record anything at all. `False` also removes the *Changes* page |
| `HISTORY_RETENTION_DAYS` | `None` | Keep everything. A number is what `prune()` deletes beyond |

Nothing prunes on its own. Call `generic.history.prune()` from a task
or a cron job if the retention is set.

## Who may read it

Two doors, two keys:

| What | Who |
| --- | --- |
| A record's History tab, and `<pk>/history/` | Whoever may **view that record** — it shows that record's own fields and nothing else |
| The *Changes* page, and its endpoint | Whoever holds `generic.view_historyentry` |

The second is the wider one: a single table of everything is a table of
records the reader may not be allowed to open. It is an administrator's
permission, granted deliberately, and it is not in any group the example
seeds.

## What it costs

Two queries per recorded write — one to read the last version, one to
insert the next — inside a savepoint of the caller's own transaction.
That means a change that is rolled back takes its history with it, and
a failure to record is logged rather than raised: recording must never
break the save.

Relations are stored as keys, so nothing here reads a record's
relations on the way in. They are named on the way out, in one query per
related model per page of history.

Many-to-many values are carried forward from the previous version and
re-read only when `m2m_changed` says they changed, which is the only
moment they can have.

## Endpoint

```
GET api/<app>/<model>/<pk>/history/?limit=20&offset=0
```

```json
{
  "count": 12,
  "limit": 20,
  "offset": 0,
  "hasMore": false,
  "results": [
    {
      "id": 88, "version": 2, "action": "updated",
      "actionLabel": "Changed", "who": "admin", "source": "",
      "at": "2026-09-21T09:57:00+02:00", "when": "21 September 2026 09:57",
      "changes": [
        {"name": "status", "label": "Status",
         "from": "Closed", "to": "Open",
         "fromEmpty": false, "toEmpty": false}
      ],
      "values": [
        {"name": "title", "label": "Title",
         "display": "Login fails after password reset", "empty": false}
      ]
    }
  ]
}
```

`404` where the model keeps no history, `403` where the reader may not
view the record. The summary endpoint carries the same address and the
last entry, which is what draws the line at the top of the page:

```json
"history": {"url": "/api/example/ticket/1/history/",
            "last": {"version": 2, "action": "updated",
                     "actionLabel": "Changed", "who": "admin",
                     "at": "...", "when": "21 September 2026 09:57"}}
```

# Watching

Being told when a record changes. A user watches one record, or every
record of a model, and chooses how they hear about it — per model and
per record.

Nothing is declared to make this work: every registered resource is
watchable, and the button appears on its pages.

## What a user does

| Where | What it offers | What it means |
| --- | --- | --- |
| A record's page or its form | *Watch* | Tell me when **this** changes or is deleted |
| The arrow beside it | *This one* / *All of them, including new ones* | Both watches, from the record's own page |
| A list page | *Watch every record* | Tell me when **any** record is created, changed or deleted |
| *Watching*, in the account menu | — | One card per watch: which changes, and through which channels |

A record and its model are **two watches**, not one setting with two
values: watching every ticket does not stop you from also watching one
of them, and unwatching one leaves the other alone. The menu shows
both ticked independently for that reason.

The button only turns a watch on and off. The *Watching* page is where
the format is chosen, and it is chosen per row — so *every ticket, by
e-mail* and *this ticket, as a notification* are two independent
answers.

## Channels

The ones everything that tells a person something uses - tasks and
messages too ([Who hears what](events.md#who-hears-what)):

| Channel | What arrives |
| --- | --- |
| `notification` | A stored notification: the bell, the notifications page, and a toast on every page the reader has open |
| `mail` | An e-mail with the record's label and a link |
| (none chosen) | Whatever *Account settings › Notifications* says |

Leaving the channels empty is the useful default: the watch follows the
account's own preference, and keeps following it when that changes.

A page showing the record needs no channel to follow it: its tables,
summary and charts refresh by themselves when it changes, for everyone
who has it open, watching or not.

## From code

```python
from generic.watch import watch, unwatch, is_watching

watch(user, ticket)                                  # this ticket
watch(user, Ticket)                                  # every ticket
watch(user, Ticket, events=["created"], channels=["mail"])

is_watching(user, ticket)
unwatch(user, ticket)
```

`events` is any of `created`, `updated`, `deleted`. A watch on one
record never listens for `created` — it existed before the watch did —
and asking for it is dropped rather than stored.

## Where the messages come from

The same signal that already tells open tables to refresh
(`generic.sites.realtime`): one place where a save becomes news, one
definition of what a change is. Delivery waits for the transaction to
commit, so **a change that is rolled back is never announced**.

A bulk `queryset.update()` fires no signal and therefore tells nobody —
the same caveat as the live tables. Call
`generic.watch.notify.announce(resource, obj, "updated")` yourself
after one, or save the rows.

## Who may be told

Two rules, and the first one matters:

1. **A watcher is told only what they could have read anyway.** The
   model's view permission is checked again for every message, not
   only when the watch was made — permissions get taken away. A watch
   must never become a way to learn that a record exists.
2. Telling people cannot break the save. Everything runs after the
   commit and swallows its own failures: a mail server that is down
   does not roll back somebody's ticket.

Object-level rules are the part a signal cannot replay: `get_queryset`
needs a request, and there is none here. A resource that restricts rows
per user should say so again:

```python
class TicketResource(ModelResource):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(team=request.user.team)

    def may_watch(self, user, obj=None):
        return obj is None or obj.team_id == user.team_id
```

`may_watch` is asked for every message, after the model permission has
already passed.

## Turning it off

```python
class AuditEntryResource(ModelResource):
    watchable = False
```

The button disappears and the endpoint refuses, which is the point:
hiding a button is never the protection. Use it for models whose
changes are nobody's news — a log, a run, a counter.

## What it does not do

The message says *that* a record changed, not *what* changed: it names
the record and links to it. What changed is the other half, and it is
kept for every record anyway — see [History](history.md), whose tab the
link lands beside.

There was once a second way to keep a record within reach, a star
called *Favourites*. It answered the same question as a watch and
answered it worse, so it was removed: press *Watch* instead, and the
record is on your *Watching* page.

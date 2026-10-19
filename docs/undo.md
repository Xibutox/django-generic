# Undo

A delete, a bulk action or a bulk edit answers with an **Undo** button
beside its message. Pressed within ten minutes, it puts every record the
action touched back as it was - the deleted ones created again, with
what went with them, the changed ones given their values back.

```
✓ “Invoice PDF is blank” was deleted.          [↶ Undo]  ✕
```

Nothing is declared: every resource with a history offers it.

```python
class AuditTrailResource(ModelResource):
    undo = False        # this resource's actions offer no Undo
```

```python
GENERIC = {
    "UNDO_SECONDS": 600,        # None or 0: no Undo anywhere
    "UNDO_MAX_RECORDS": 1000,   # an action touching more offers none
}
```

## Where it is offered

| After | Where the button is |
| --- | --- |
| *Delete* in a row's menu, on a change form | the toast saying it was deleted (on the list page the form goes back to) |
| *Delete* on a record's page (the confirmation page) | the message on the page it goes back to |
| Any bulk action - *Delete selected*, a transition, an action of the project's own | the toast, or under the report of an action answering one |
| *Edit the selected …*, once applied | under its report |

A toast with an *Undo* stays fifteen seconds rather than five, and does
not go while the pointer or the focus is on it. The server accepts the
undo for `UNDO_SECONDS` after the action.

An action is offered no undo when it answers an error, opens another
page (`{"redirect": ...}`), or hands its work to a task run elsewhere:
what a worker writes is another unit of work. With a trash, a delete is
a move to the trash, and the undo brings the record out of it.

## How it works

Nothing new is stored. The [history](history.md) keeps every record as
it was, and each version carries the **batch** - the unit of work - it
was written in. The endpoint notes the batches the action wrote in
(`generic.history.capture.capture()`), and the answer carries a signed
token naming them:

```json
{
  "message": "2 tickets deleted.",
  "level": "success",
  "undo": {
    "token": "…",
    "url": "/api/example/ticket/undo/",
    "label": "Undo",
    "count": 4,
    "seconds": 600
  }
}
```

`count` is the number of records put back: two tickets and their two
comments here. `POST <url>` with `{"token": "…"}` undoes it. For each
record, the version written just before the action is the one put back:

| The action had | Undo |
| --- | --- |
| changed the record | writes back the version before it (`save(update_fields=...)`); fields stamped on every save (`auto_now`) are left to the database |
| deleted it | creates it again with the same key, its many-to-many values and its creation date |
| created it | deletes it - refused if that would delete other records with it |

Everything in one transaction, recorded like any change: the History
tab shows a version by the person, source *Undo*. Open tables reload,
and a record's page shows the record as it is again.

The API's `DELETE <pk>/` still answers 204; with `?undo=1` (what the
delete dialog sends) it answers 200 and `{"undo": {...}}` when there is
one. Bulk actions and bulk edits add the `undo` key to their answer.

## When it is not offered

An undo is offered only when it can be done whole. No button when:

- the resource keeps no history (`history = False`, `GENERIC["HISTORY"]
  = False`) or says `undo = False`;
- a deletion would bring back less than it took: it cascades to (or
  empties a link of) a model without a history, or the deleted model's
  resource keeps fields out of its versions (`history_exclude` - a
  password, a token: a record created again without them is not the
  same record). Deleting a *tag* is the usual case: the tickets' links
  to it are the tickets' own many-to-many, and their versions do not
  record a link removed from the far end;
- a record was changed with no version before it (written before the
  history began);
- more than `UNDO_MAX_RECORDS` records were touched.

## When it is refused

Nothing is undone, and the answer says why, when:

| Answer | Why |
| --- | --- |
| 400 *This can no longer be undone.* | the token expired, is somebody else's, belongs to another resource, or was altered |
| 409 *“…” has changed since.* | a record has a newer version than the action's - somebody changed it, or the undo already ran |
| 409 *“…” exists again.* | a deleted record's key was taken since |
| 403 | the reader no longer holds the permission: change to put a record back, add to create it again, delete to delete what was created - and the record must still be one `get_queryset(request)` gives them (or be in its trash) |
| 409 *Nothing was undone: …* | the database refused (a unique value taken since, a protected relation) |

## From code

```python
from generic.history.capture import capture
from generic.history.undo import offer, undo

with capture() as captured:
    run_my_bulk_change(request)

offered = offer(resource, request, captured)   # None, or the answer's "undo"
undo(resource, request, offered["token"])      # raises undo.Refused
```

A page of the project's own that deletes or changes records can answer
the same `undo` key, and `Generic.undo.toast(message, level, offer)`
draws the toast with its button (`Generic.undo.run(offer)` sends it;
the page then receives `generic:undone` and `generic:tables-reload`).
A page that redirects passes it on with
`messages.success(request, text, extra_tags=message_tags(offered))`.

## Security

- The token is signed (`django.core.signing`, salt
  `generic.history.undo`) and names the resource, the person and the
  batches; another person's token, or one sent to another resource's
  endpoint, is refused.
- The permissions and the reader's rows are checked again at the undo,
  record by record: an undo never does what the reader could not do by
  hand.
- The client sends the token, never a batch, a model or a key.

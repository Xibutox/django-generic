# State machines

A record that lives through states - a ticket opened, waiting,
resolved, closed - declares them once, on its model, with
[django-fsm-2](https://github.com/django-commons/django-fsm-2). The
resource names the state field, and each transition becomes:

- a **button on the record's page**, offered only from the states it
  leaves and only to a reader allowed to take it;
- a **bulk action on the list**, which takes it on every selected row
  that can, and says how many it skipped;
- an **endpoint**, which checks everything again under a row lock.

The state field itself becomes read only - in forms, in grids, in
imports: a state changes through its transitions, or not at all.

```bash
pip install "django-generic[fsm]"
```

## Declaring it

```python
# models.py
from django_fsm import FSMField, transition


class Ticket(models.Model):
    status = FSMField(_("status"), max_length=10,
                      choices=Status.choices, default=Status.OPEN)
    resolution = models.TextField(_("resolution"), blank=True, default="")

    class Meta:
        permissions = [("reopen_ticket", _("Can reopen a ticket"))]

    @transition(field=status, source=[Status.OPEN, Status.PENDING],
                target=Status.RESOLVED,
                custom={"label": _("Resolve"), "icon": "task_alt",
                        "fields": ("resolution",)})
    def resolve(self): ...

    @transition(field=status, source=[Status.RESOLVED, Status.CLOSED],
                target=Status.OPEN, permission="example.reopen_ticket",
                custom={"label": _("Reopen"), "icon": "undo",
                        "confirm": _("Reopen this ticket?"),
                        "variant": "danger"})
    def reopen(self): ...
```

```python
# resources.py
class TicketResource(ModelResource):
    transitions = ("status",)       # the state fields whose transitions are offered
    transition_actions = True       # also as bulk actions (the default)
```

Everything about a transition is django-fsm-2's own declaration - the
framework adds no second place to describe one. It reads the `custom`
dict:

| Key | Default | |
| --- | --- | --- |
| `label` | the method's name | the button, the bulk action |
| `icon` | none | a Material Symbols name |
| `confirm` | none | asked before it runs |
| `variant` | `default` | `danger` draws it red |
| `fields` | `()` | form fields asked for in a dialog first, validated by the resource's form serializer, written with the transition |

and django-fsm-2's own `permission` (a permission string, or
`callable(instance, user)`) and `conditions`.

`transitions` is checked when the resource is registered: a name that
is not an `FSMField`, a field with no `@transition`, a `fields` entry
the model does not have, an unknown `variant`, or django-fsm-2 missing,
raises `ImproperlyConfigured` naming the resource. A state field listed
in `editable_fields` raises too.

## Who may take one

All three, on the record, now:

1. the resource's `has_change_permission(request, obj)`;
2. the transition's `permission`;
3. its `conditions`, and the record being in one of its source states.

The page shows only the transitions that pass. The endpoint checks
again, on the record read under a row lock
(`select_for_update(of=("self",))`, a no-op on SQLite).

## What it answers

| Request | Does |
| --- | --- |
| `GET api/<app>/<model>/<pk>/transitions/` | the transitions this reader may take now: `[{name, label, icon, variant, confirm, fields: [{name, label, required, multiline, maxLength}], target}]` |
| `POST api/<app>/<model>/<pk>/transitions/<name>/` | the `fields` values in the body; runs it, saves, answers the record's summary |

| Answer | When |
| --- | --- |
| 404 | an undeclared name, a record out of the reader's reach |
| 403 | the change permission or the transition's permission missing |
| **409** | the record is no longer in a state the transition leaves, or a condition fails - someone moved it since the page was drawn |
| 400 | a value the form refuses, a required field left empty |

The client sends a transition's name, never a state value.

The summary endpoint carries the same list as `transitions` (and
`urls.transitions`), so the page draws its buttons without another
request; the record's other bulk actions no longer include the
transitions.

## The list

With `transition_actions` (the default), each transition that asks for
no field is a bulk action named `transition:<name>`, offered to readers
holding the change permission and the transition's permission. It runs
the transition on each selected row the same way the endpoint does,
row by row, and reports *Close: 12 done, 3 skipped* - the rows skipped
being those not in a state that allows it, or not allowed.

## What it leaves

Each transition saves the record inside `acting_as(user,
source="Transition: <label>")`, so its **History** tab says *Transition:
Resolve* beside the change, and the usual live update and watcher
messages follow. django-fsm-2's `pre_transition` and `post_transition`
signals fire as always.

## The example

The support desk's tickets: *Wait for the customer* (open → pending),
*Customer answered* (pending → open), *Resolve* (asks for the
resolution), *Close* (confirmed) and *Reopen* (only with
`example.reopen_ticket`, drawn red). The list's former hand-written
*Close* action is now the generated one.

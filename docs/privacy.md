# Personal data (GDPR)

A resource says once what its model holds about people. From that
declaration the framework finds where personal data lives, exports
everything kept about one person, anonymizes them - in the history
too - and keeps each model's rows only as long as declared.

```python
from generic.privacy import PersonalData, Retention


@register(Agent)
class AgentResource(ModelResource):
    personal_data = PersonalData(
        fields={"name": "pseudonym", "email": "email", "phone": "blank"},
        email=("email",),              # finds a person's rows by address
        export=("hired_on", "team"),   # more fields an export carries
    )


@register(PersonnelFile)
class PersonnelFileResource(ModelResource):
    personal_data = PersonalData(
        fields={"full_name": "pseudonym", "job_title": "blank"},
        subject="user",                # finds them through their account
        retention=Retention(
            days=5 * 365, after="ends_on", filter={"status": "left"}
        ),
    )
```

The user model needs nothing: its login becomes a pseudonym, its first
and last names and its address are emptied, and its rows are found by
the account and its address. A model no resource describes is declared
with `generic.privacy.register(Model, PersonalData(...))` - which also
overrides a resource's declaration, the user model's included.

## The declaration

| `PersonalData(...)` | Default | |
| --- | --- | --- |
| `fields` | `{}` | Field name -> what it becomes when anonymized (below) |
| `subject` | `None` | Path to the user a row is about: `"user"`, `"customer__account"` |
| `email` | `()` | Fields holding the person's address, matched ignoring case |
| `export` | `()` | Fields an export carries besides `fields` |
| `retention` | `None` | A `Retention`: how long the rows are kept |
| `marker` | `None` | A nullable `DateTimeField` set when a row is anonymized; the retention skips rows already done |
| `action` | `True` | The list's bulk action *Anonymize*, for whoever may delete |

What a field becomes:

| Strategy | Value | For |
| --- | --- | --- |
| `"blank"` | `""` for text, `None` otherwise; a file is deleted from the storage | text, files, anything nullable |
| `"null"` | `None` | nullable fields |
| `"pseudonym"` | `anonymous-<pk>` - unique, says which record, nothing of the person | text |
| `"email"` | `anonymous-<pk>@anonymized.invalid` - valid, unique, reaches nobody | text |
| a callable | `strategy(obj, field_name)` | anything else; give the same value twice |

`Retention(days, after, action="anonymize", filter={})`: `days` after
the date in `after` (a `DateField` or `DateTimeField`, or a path to
one), a row is anonymized - or deleted, with `action="delete"`.
`filter` narrows the rows concerned as keyword lookups. A row whose
date is empty is kept.

A declaration is checked when the resource is registered: a missing
field, a strategy the field cannot take (`"null"` on a field that is
not nullable), a `subject` that does not lead to the user model, a
retention date that is not a date, a filter that does not apply - each
raises `ImproperlyConfigured`, naming the resource and the attribute.

## The command

```bash
python manage.py personal_data inventory [--json]
python manage.py personal_data export --user alice [--output alice.json]
python manage.py personal_data export --email alice@example.com
python manage.py personal_data anonymize --user alice [--dry-run] [--no-input]
python manage.py personal_data retention [--dry-run]
```

**`inventory`** - where personal data lives, model by model:

| Kind | What |
| --- | --- |
| `declared` | a field a declaration names, and its strategy |
| `retention` | how long a declaration keeps its rows |
| `suspected` | a field nothing declares that looks personal - an `EmailField`, a `GenericIPAddressField`, a name such as `phone`, `birth_date`, `last_name`, `address`, `iban`: declare it, or write down why not |
| `account` | a relation to the user model: rows by or about a person, listed by an export, left pointing at an anonymous account |
| `framework` | the framework's own stores (history, access log, security events, notifications...) and what keeps each in check |

It is where the register of processing (GDPR Art. 30) starts, not the
register itself.

**`export`** - everything kept about one person, as JSON (right of
access and to portability, Art. 15 and 20): `records`, each row a
declaration finds - the account whole but its password, other rows
their `fields` and `export` - then `references`, every row anywhere
pointing at the account (up to 1000 per model, with the count).
`--user` finds rows through `subject` and the account's own address;
`--email` through the `email` fields; both may be given.

**`anonymize`** - the right to erasure (Art. 17). Every row found, in
one transaction:

- each declared field takes its value; with a `marker`, it is set;
- **the history is rewritten**: the same fields take the same values in
  every version kept of the record, and what the record was called -
  in the history and in the access log - is its new label. One more
  version says the anonymization happened, when, and by whom (source
  *Anonymization*);
- a blanked file is deleted from the storage, once the transaction
  commits;
- **the account** loses its password and is deactivated - which ends
  its sessions; where its name was copied (the history's *by*, the
  access log, the security events) the pseudonym replaces it; the
  addresses and browsers it came from are dropped; its notifications,
  watches, saved views, preferences and API tokens are deleted, and
  its access requests' messages emptied.

What the person did stays: their tickets, their changes, their
sign-ins, by an anonymous account. A record already anonymized is left
alone, so running it twice changes nothing. `--dry-run` lists the rows
and stops; without `--no-input`, the command asks before it writes.

**`retention`** - the rows past their declared retention, anonymized or
deleted (storage limitation, Art. 5(1)(e)). A deleted row's history is
rewritten the same way, so it says a record was deleted and nothing of
whom it was about; a row other records protect is kept, with a warning
in the log. `apply_retention` - and the managed task
`generic.apply_retention` - run it every night with the other
retentions ([History](history.md#retention)), its count under
`personal_data`.

From code, the same: `generic.privacy.export(Subject(user=..., email=...))`,
`anonymize_subject(subject, user=..., dry_run=...)`, `anonymize(obj)`,
`apply_retention(dry_run=...)`, `inventory()` in
`generic.privacy.inventory`.

## On the screens

A list whose resource declares personal data offers the bulk action
**Anonymize** - to whoever may delete its records, since it erases as
much. It asks first, and offers no *Undo*: the history it would come
back from has been rewritten. `PersonalData(action=False)` leaves it
out. Accounts are anonymized from the command, not from *People*.

## What it does not do

- Free text is not read: a person named in a ticket's description, a
  comment, a wiki page stays there. Declare such fields - `"blank"`
  empties them - or have someone edit them.
- Custom field values (`cf:<key>`) and files outside a declared
  `FileField` are not touched.
- Backups keep what they kept until they expire: say how long in the
  register, and restore with care.
- Notifications already sent, e-mails, logs on disk (`generic.logs`)
  are outside the database.

The example declares its agents (found by address) and its ticket
comments (their author kept three years); the ISO apps declare the
personnel files (found through the account, anonymized five years after
the person left), the suppliers' contacts and the ISMS contacts.

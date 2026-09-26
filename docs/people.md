# People, groups and permissions

Who may sign in, and what each of them may do — on the site itself,
rather than in `/admin/`. Three screens under **People** in the
navigation:

| Screen | Holds |
| --- | --- |
| **Users** | every account: its identity, whether it is active, its groups and its own permissions |
| **Groups** | a job, and what it is allowed to do — with the members and the count of each |
| **Permissions** | every permission the application declares, read-only |

Nothing is declared to get them. They appear where the framework is
installed, and only for whoever holds the ordinary
`auth.view_user` / `auth.view_group` permissions — so an application
whose users are all desk agents never shows them at all.

A fourth, **Messages**, sits beside them: telling some of these people
something, or all of them, as a notification or an e-mail - see
[Messages](events.md#messages).

## Why they are here

An application that manages its own accounts should not send its
administrators somewhere else for the one job that decides what
everybody else can do. These screens are ordinary resources: the same
table, the same filters, the same search, the same exports, the same
history tab. A group's page lists its members as a related table, an
account's page lists the changes that account has made.

The third screen is what makes the first two usable. A permission is a
record like any other, so the fields that point at it — a group's
permissions, an account's own — get the same Select2 autocomplete as
any other relation, instead of the four hundred checkboxes the admin
draws.

## Passwords

The password field on the user form is **write-only**: it is sent to
the server and never sent back, because the record's own endpoint
returns everything else and the hash would go with it.

| What you do | What happens |
| --- | --- |
| Leave it empty on an existing account | the password is untouched |
| Type one | it is checked, hashed, and replaces the old one |
| Leave it empty on a new account | the account has *no usable password* — for somebody who signs in through a directory or SSO |

What counts as an acceptable password is the project's own
`AUTH_PASSWORD_VALIDATORS`, checked before anything is written,
including the validator that compares a password against the name and
the address of the account it is for. **A project that declares no
validators accepts anything** — Django's `startproject` template
declares four, and the example project declares the same four.

## What these screens refuse

Editing an account is editing what somebody may do, so this is where a
mistake is worst. Django's own admin lets anyone holding `change_user`
tick *superuser*, which turns one narrow permission into every
permission. These screens refuse, on a single rule:

> **What you grant, you must already have.**

| Someone who is not a superuser | Result |
| --- | --- |
| ticks *superuser* on any account | refused, on the field |
| ticks *staff* while not staff themselves | refused |
| adds a group granting a permission they lack | refused, naming the permission |
| adds such a permission directly | refused, the same way |
| opens a superuser's form at all | refused — whoever may change an account may set its password, and so become it |

And two that apply to everybody, superusers included:

- **You cannot delete the account you are signed in as.** Neither from
  the record nor by selecting it in the table: both go through the same
  place, and a bulk delete holding one account nobody may delete
  deletes none of them.
- **You cannot deactivate your own account** — the one change only
  somebody else could undo. The bulk *Deactivate* leaves your account
  alone and says how many it skipped.

A superuser is exempt from the granting rule, holding everything by
definition. Everything is checked before anything is written, so a
refusal names the field and the form shows it there.

The rules live in `generic/accounts/guard.py`, on their own, so they can
be read in one sitting.

## Turning them off

```python
GENERIC = {"SHOW_PEOPLE": False}
```

Or simply register the user model yourself: these screens are only
added where the model is still free, so a project's own `UserResource`
in its `resources.py` wins without a setting.

```python
# myapp/resources.py - your own, instead of the framework's
@register(get_user_model())
class StaffResource(ModelResource):
    ...
```

## A field that is written and never read

The password is one case of something any project may need — an API
token, a secret — and the resource attribute is general:

```python
class ConnectionResource(ModelResource):
    form_field_kwargs = {
        "api_token": {"write_only": True, "required": False},
    }
    history_exclude = ("api_token",)
```

`form_field_kwargs` is DRF's `extra_kwargs`, per field: it says what the
field *does* — whether it may be written, whether it is required, what
it validates — where `form_overrides` only says how it is drawn. A
secret belongs in both: `write_only` here, so the endpoint never
returns it, and in `history_exclude`, so no version of the record keeps
a copy.

The form draws it as a password box with
`form_overrides = {"api_token": {"widget": "password"}}`, which also
tells the browser not to offer the person's own saved password for
somebody else's account.

## A custom user model

`AUTH_USER_MODEL` may have no `username`, no `first_name`, no
`is_staff`. Nothing here is declared against a field that might not be
there: the columns, the fieldsets, the search fields and the members
tab are worked out from the model when the screens are registered, and
what is missing is not offered. A model with no `groups` field simply
has no *Groups and permissions* section.

## What is recorded

An account's history is kept like any other record's, with two fields
left out:

- `password`, because a history of hashes is a list of hashes to attack
  offline, and no version of an account should hold one;
- `last_login`, because it changes on every sign-in and would write a
  version of the account each time.

So the history of an account is what somebody *decided* about it: the
groups it was put in, the day it was deactivated, who did it. See
[History](history.md).

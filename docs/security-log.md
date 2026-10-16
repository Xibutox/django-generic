# Security events

The [history](history.md) says what changed, the [access log](trash.md)
who read what. Neither says who signed in from where, that somebody
tried thirty passwords on one account, or that the customer table left
in one file - the first questions asked after an incident. The
framework records those as **security events**, with nothing to
declare:

| Event | When | About |
| --- | --- | --- |
| `signed_in` | Every sign-in: the password form, an SSO provider, `login()` in a project's view | The account; the authentication backend in *detail* |
| `sign_in_failed` | A wrong password | The name typed - the account when it exists; never the password |
| `locked_out` | The sign-in lock closes ([`LOGIN_MAX_ATTEMPTS`](settings.md)) | The name typed; how many failures, from the account or the address |
| `signed_out` | Signing out | The account |
| `password_changed` | On the account page, or set by an administrator on the People screens | The account; *by* the administrator |
| `token_created`, `token_deleted` | An [API token](api.md) made, revoked, or deleted once expired | Its owner; its name, "(expired)" |
| `access_granted`, `access_refused` | A [right on request](access-requests.md) decided | Who asked; *by* who decided; the right |
| `exported` | An Excel or CSV export, a scheduled mailing's attachment | Who; the table, the format and the number of rows - recorded once the last row has left |

Each event is written twice:

- **to the log**, on the `generic.security` logger - one line, a refusal
  (`sign_in_failed`, `locked_out`, `access_refused`) at `WARNING`, the
  rest at `INFO` - so it reaches the [log file](logging.md) and
  whatever collects it:

  ```text
  2026-10-15 21:12:03,412 WARNING generic.security [811] sign_in_failed account='alice' user_id=4 by='' address=203.0.113.9 detail=''
  ```

- **to the database**, `generic.audit.models.SecurityEvent`, read on
  *History > Security events*: filtered, searched and exported like any
  table, read-only, behind `generic.view_securityevent`.

The address is the one the server saw (`REMOTE_ADDR`), never a header a
client may write: behind a proxy, the server in front must set it (see
[Deployment](deployment.md)).

## From code

A project records its own events:

```python
from generic.audit import record

record("exported", request=request, detail="Yearly report (pdf)")
record("password_changed", user=account, actor=request.user)
```

`request` gives the address, the browser and - when `user` is not given
- the account. A failure to write the entry is logged, never raised: a
sign-in does not fail because its record did.

## Settings

| Setting | Default | Means |
| --- | --- | --- |
| `SECURITY_LOG` | `True` | Record the events at all. `False` also removes the screen |
| `SECURITY_LOG_RETENTION_DAYS` | `None` | Keep everything. A number is what `apply_retention` deletes beyond ([Retention](history.md#retention)) |

## Why

ISO/IEC 27001:2022 asks that events about access be logged, kept and
reviewed (A.8.15 Logging, A.8.16 Monitoring activities), and the GDPR
that a breach be reported within 72 hours (Art. 33) - which needs the
record of who got in. The events hold personal data (a name, an
address): choose their retention and write it in the register of
processing.

## What is not recorded

- **Copy and print** of a table: they happen in the browser, on the
  rows already shown.
- **Changes to accounts, groups and permissions**: they are in the
  [history](history.md) of the account, the group, the permission.

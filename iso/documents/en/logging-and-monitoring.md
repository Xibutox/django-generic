# POL-06 Logging and monitoring policy

| | |
| --- | --- |
| Code | POL-06 |
| Version | 1.0 |
| Owner | Chief information security officer (CISO) |
| Approved by | [Name, role, date] |
| Reviewed | Every 12 months |
| ISO/IEC 27001:2022 | 8.15, 8.16, 8.17, 8.10, 5.28; GDPR art. 5(1)(e), 30, 33 |
| Applies to | Every application built on django-generic, the ISO apps included |

> **Using this document.** It says what a django-generic application
> records, where, for how long and who reads it. Text in [brackets] is
> the organisation's to fill in. Values are those of the example
> project; a project that changes its settings changes this document.

## 1. Purpose

Keep a trustworthy record of who did what in the application, notice
abnormal activity, have the evidence an incident investigation needs,
and keep personal data in the logs no longer than necessary.

## 2. What is recorded

The application keeps five records. None needs anything declared,
except the access log, which a resource turns on.

| Record | What it holds | Where it is read |
| --- | --- | --- |
| **History of the records** | Every creation, change and deletion of every registered model - who, when, from where (a page, a task, an import), each version in full. Includes accounts, groups and permissions. Bulk writes (`update()`, `bulk_create()`) are recorded too; on PostgreSQL a database trigger also records writes made outside the application (by `psql`, another program), under the database role's name | A record's *History* tab; *History > Changes* |
| **Security events** | `signed_in`, `sign_in_failed`, `locked_out`, `signed_out`, `password_changed`, `token_created`, `token_deleted`, `access_granted`, `access_refused`, `exported` - with the account, the address the server saw, the browser, the time | *History > Security events*; the `generic.security` log |
| **Access log** | Who opened a record's page (once every ten minutes per person and record) and who downloaded which file, on the resources that ask for it - in the ISO apps, an incident's evidence | *History > Access log*; the record's *Access log* link |
| **Application log** | Every unexpected error with its traceback, the security events, the tasks, at `INFO` and above | Standard output (`docker compose logs`), and the file `/app/logs/app.log` in production |
| **Error mails** | Every error at `ERROR` mailed to `ADMINS` when `DEBUG` is off - the same error at most once every 10 minutes, the next mail saying how many were held back | The administrators' mailbox |

The password typed is never recorded, nor the password hashes, nor the
last sign-in date in an account's history.

What is **not** recorded: copying or printing a table (done in the
browser, on rows already shown), and a record merely listed in a table.

## 3. Who may read the records

| Record | Permission |
| --- | --- |
| A record's own history tab | Whoever may view that record - it shows only that record's fields, and hides the fields the reader may not see |
| *History > Changes* | `generic.view_historyentry` |
| *History > Security events* | `generic.view_securityevent` |
| *History > Access log* | `generic.view_accessentry` |
| Application log and mails | Those who reach the server [and the mailbox in `DJANGO_ADMINS`] |

These permissions are in no group the demos create. They are given to
[the CISO and the internal auditor], by name (POL-03).

## 4. Protection of the records

- Nobody adds or changes a history entry, a security event or an access
  log entry from the screens; access log entries cannot be deleted from
  them either.
- **Limit:** a holder of `generic.delete_historyentry` or
  `generic.delete_securityevent` - every superuser - can delete history
  entries or security events from the *History* screens, and that
  deletion leaves no entry of its own. Therefore:
  - these two permissions are given to nobody; superusers are few and
    reviewed (POL-03);
  - the application log, which carries every security event as a line
    written at the time, is copied off the server [to the log
    collector / SIEM named here], where the application cannot change
    it;
  - [on PostgreSQL, the database's own audit (`pgaudit`) covers what a
    database administrator does].
- Each entry keeps the person's name as it was, so the record stays
  readable after an account is deleted.
- The address recorded is the one the server saw (`REMOTE_ADDR`),
  never a header a client may write. Behind the proxy, the proxy sets
  it.

## 5. Clocks

Every record is stored in UTC and shown in the reader's time zone
(`USE_TZ = True`; `TIME_ZONE = "Europe/Paris"` in the example).
Containers read the clock of the host they run on, so the host's clock
is the one to keep right. [The hosts synchronise with NTP server(s)
... .]

## 6. Retention

The records hold personal data (names, addresses): each is kept for a
stated time, then deleted by `manage.py apply_retention` (or the
managed task `generic.apply_retention`), scheduled daily.

| Record | Setting | Example project | [Organisation] |
| --- | --- | --- | --- |
| History | `HISTORY_RETENTION_DAYS` | kept (None) | [kept for the life of the records / N years] |
| Access log | `ACCESS_LOG_RETENTION_DAYS` | 365 days | [365 days - CNIL: 6 months to 1 year] |
| Security events | `SECURITY_LOG_RETENTION_DAYS` | kept (None) | [365 days] |
| Notifications | `EVENTS_RETENTION_DAYS` | 90 days | [90 days] |
| Application log file | `logging_config(max_bytes, backups)` | 5 files of 10 MB | [and the collector's retention] |

`None` keeps everything. Each deletion is itself logged
(`generic.retention`). The periods chosen are written in the GDPR
register of processing.

## 7. Monitoring

| What | How | Who | When |
| --- | --- | --- | --- |
| Errors | Mails to `DJANGO_ADMINS`; `check --deploy` warns while it is empty | [Ops] | As they arrive |
| Server health | *Monitoring > Server status* (`generic.view_status`): processors, memory, disks, database, cache, Celery, migrations, tasks failed in the last 24 hours; the production stack's health checks | [Ops] | [Daily] |
| Sign-in failures and lockouts | *Security events*, filtered on `sign_in_failed` and `locked_out`; `WARNING` lines in the log | [CISO] | [Weekly] |
| Exports | *Security events*, filtered on `exported`: who exported which table, how many rows | [CISO / data owner] | [Monthly] |
| Rights granted | *Security events* `access_granted`, *People > Access requests* | [CISO] | [Monthly] |
| Changes to accounts and groups | *History > Changes*, filtered on the user and group models | [CISO] | [Monthly, and at the access review] |
| Downloads of evidence | *History > Access log* | [Incident manager] | During an incident |

Anything abnormal - a burst of failures, an export nobody expected, a
right given outside the procedure - is reported as a security event in
`iso.incidents` (POL-08).

## 8. Settings the application must have in production

- `generic.middleware.CurrentUserMiddleware` after the authentication
  middleware: without it the history records what changed, not who
  changed it.
- `GENERIC["SECURITY_LOG"]` left at `True` (the default).
- `LOGGING = logging_config(...)` with a file, and `ADMINS` set.
- `apply_retention` scheduled.
- On PostgreSQL, `HISTORY_TRIGGERS` left at its default.
- A shared cache (Redis) when there are several processes, so the
  sign-in lock counts every attempt.

## 9. Reviewing this policy

At each review, check that the settings in section 8 are still those
of the running application (`manage.py check --deploy`), that the log
copy still arrives off the server, and that the retention periods still
match the register of processing.

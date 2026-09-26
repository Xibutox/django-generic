# Scheduled mailings

From any list, the **Views** menu offers *Send by e-mail on a
schedule…*: the table as it is now - its filters, search, columns and
order - is sent as an Excel or CSV file every day, every weekday, every
week or every month, at a time of day, to the people and groups chosen.

**Each recipient receives the rows they may see**, computed as them, in
their own language. The file is the resource's own export, asked for
by a request signed in as the recipient: the export's column
whitelist, the resource's `get_queryset`, its view permission and
`EXPORT_MAX_ROWS` decide, exactly as on the page. A recipient who may
not see the list receives nothing.

## Who can use it

Nobody, until a project says so: the entry appears to holders of
`generic.add_scheduledmailing`, which out of the box only superusers
have. Grant it to a group:

| Permission | Gives |
| --- | --- |
| `generic.add_scheduledmailing` | the menu entry, and one's own mailings: create, change, send now, pause, delete |
| `generic.view_scheduledmailing` | everyone's mailings, read |
| `generic.change_scheduledmailing` / `delete_...` | everyone's mailings, changed / deleted |

A resource refuses to be mailed with `mailing = False`, and
`GENERIC["SHOW_MAILINGS"] = False` removes the whole feature: menu
entry, screen and dispatcher.

Recipients are accounts - people, groups, and the owner unless *send
it to me* is unticked - active and with an address, each once. There
are no free-text addresses: rows never leave the application for
someone it does not know.

## The mailing

Made from the list menu, which opens the mailing's form with the list
and its layout filled in; kept on the **Scheduled mailings** screen, in
the Tasks group.

| Field | |
| --- | --- |
| Name | the subject of every e-mail |
| Format | Excel or CSV |
| Frequency, time | every day / weekday / week (and its day) / month (and its day, 1 to 28), at a time in the project's `TIME_ZONE` - 08:00 stays 08:00 through summer time |
| Recipients | *send it to me*, people, groups |
| Send when empty | off: a list with no rows sends nothing |
| Active | paused when off |
| List, layout | the table (`site.<app>.<model>`) and its saved state, as a saved view holds it |

Saving checks the list as its owner: a table that cannot be mailed, or
one the owner may not see, is refused. The next sending is worked out
on every save.

## Sending

One task sends every mailing whose time has come:
`generic.send_scheduled_mailings`, declared with `managed_task`, so
every run is a `TaskRun` listing what was sent, empty, refused or
failed. Run it every few minutes:

- with Celery beat (`django_celery_beat`): a periodic task on
  `generic.send_scheduled_mailings`, every 5 minutes - the Schedules
  page makes one, and the example's seed does;
- without: a cron line, `*/5 * * * * python manage.py
  send_scheduled_mailings`.

Each mailing is claimed under a row lock and its next time moved on
before anything is sent, so two dispatchers never send it twice; a
sending that fails waits for its next time rather than being retried.

The e-mail, per recipient, in their language: the row count, a link to
the list with the same filters (`GENERIC["SITE_URL"]` makes it
absolute), and the file. Above `MAILING_MAX_ATTACHMENT_SIZE` (10 MB)
the file stays behind and the mail says so. It goes through
`generic.delivery.mail_with_attachment`, the default mailer - `MAILERS`
on Django 6.1, `EMAIL_BACKEND` before - and a failure is logged, never
raised.

**A mailing that no longer works pauses itself**: its table gone, or a
filter naming a column that no longer exists. Its owner gets a
notification saying why, and *Resume* on the screen starts it again
once corrected.

*Send now*, *Pause* and *Resume* are bulk actions of the screen.

## Settings

| Setting | Default | |
| --- | --- | --- |
| `SHOW_MAILINGS` | `True` | the feature at all |
| `MAILING_MAX_ATTACHMENT_SIZE` | `10 * 1024 * 1024` | bytes; above, the mail links the list |

## From code

```python
from generic.mailings.models import ScheduledMailing
from generic.mailings.sending import send

mailing = ScheduledMailing.objects.create(
    name="Open urgent tickets", owner=user, table="site.example.ticket",
    state={"filters": {...}, "columns": [...], "order": [["due_on", "asc"]]},
    frequency="weekdays", time="08:00",
)
send(mailing)          # now, whatever the schedule
```

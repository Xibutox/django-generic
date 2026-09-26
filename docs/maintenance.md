# Planned restarts

Somebody has to restart the server, and everyone using it has to hear
about it before their form disappears. One announcement does both: it
warns every connected person three times, and — unless a human is doing
the restart by hand — it restarts the server at the hour it announced.

```
Announced   as soon as it is saved:  a stored notification, a banner, a toast
Reminder    a minute before:         a toast, the banner counting down
Imminent    ten seconds before:      the banner turns red
Restarting  at the hour:             the server goes, or the operator does it
```

## Announcing one

*Plan a restart* in the account menu, for anyone holding
`generic.add_restartannouncement`. The form asks four things:

| Field | Means |
| --- | --- |
| **Restart at** | The hour the server goes down, in the announcer's own time zone |
| **Estimated duration** | How long it is expected to be unavailable — what the banner tells people |
| **Manual operation** | Ticked: the application only warns, you restart it yourself. Unticked: the server restarts itself at that hour |
| **Comment (English)** / **(French)** | What people read. Both have a default sentence; overwrite either |

The comment is stored in both languages because one announcement reaches
everyone, and the people it reaches do not read the same one: each
notification, banner and toast is served in its reader's own language
(see [Translation](i18n.md)).

The same thing from code:

```python
from generic.maintenance import announce_restart

announce_restart(
    scheduled_at=when,               # a datetime, in the future
    duration_minutes=10,
    is_manual=False,                 # the server restarts itself
    comment_en="Deploying the new filters.",
    comment_fr="Deploiement des nouveaux filtres.",
    created_by=request.user,
)
```

An hour already past is refused: it would warn nobody in time.

## What people see

A banner above the page, wherever they happen to be, counting down and
carrying the comment. It is not only for the people who were connected
when the announcement was made: the frame carries what is planned, so a
page opened five minutes later shows the same banner. Toasts mark each
warning; the first one is a stored notification as well, so it survives
a reload and waits in the bell.

*Call it off* on the same page cancels the whole thing — the timers go
and every page is told at once.

## Carrying it out

An announcement that is **not** a manual operation restarts the server
at the announced hour, by whichever means the deployment has:

1. `MAINTENANCE_RESTART_COMMAND`, when the project sets one —
   `"systemctl restart desk"`, or a list of arguments.
2. The development reloader, when `runserver` is what is running: the
   settings module is touched and the worker comes back.
3. `SIGTERM` otherwise, which is a restart only if systemd, Docker or a
   supervisor is watching the process.

`MAINTENANCE_RESTART = False` leaves the server alone whatever the
checkbox says: announcements become a warning system and nothing else.
See [Settings](settings.md#planned-restarts).

## How the timing works

The three warnings are `threading.Timer`s in the process that took the
announcement. That is deliberate: a restart notice lives for minutes and
dies with the process it announces, so a broker would be machinery
around something already over. What survives is the row — a process
starting up arms whatever is still ahead (`arm_pending`), which is what
makes the warnings outlive the restart they announced.

The consequence worth knowing: with several web workers, each one arms
its own timers, so the warnings are published once per worker. They are
broadcast events with the same payload, so a client sees one banner
either way; if that bothers you, announce from a single worker or move
`schedule()` onto your own queue.

## Permissions

Everything goes through the model permissions of
`generic.RestartAnnouncement`:

| Who | What |
| --- | --- |
| `generic.add_restartannouncement` | The page, the form, announcing, calling off |
| Any signed-in user | Reading what is planned (`GET api/generic/restart/`), and the banner |

The endpoint checks it too, not only the page: hiding the menu entry is
never the protection.

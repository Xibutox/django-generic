# Tasks

Work the application does on its own: declared once, announced when it
starts, recorded as it goes, and reported when it is done.

```python
# myapp/tasks.py
from django.utils.translation import gettext, gettext_lazy as _

from generic.tasks import managed_task


@managed_task(
    label=_("Nightly digest"),
    description=_("Counts what is late and tells the desk."),
    announce=("notification",),            # step 1: it is starting
    report=("notification", "mail"),       # step 4: how it went
    audience="staff",
)
def nightly_digest(run):
    run.note(gettext("Collecting"))
    run.add(gettext("Tickets"), 12)

    return gettext("12 tickets")
```

That is the whole declaration. It puts the task on the *Tasks* page
with a **Run now** button, lets a schedule point at it by name, and
gives every run a page of its own.

## The four steps

Every run goes through the same four, whoever started it:

| | | |
| --- | --- | --- |
| 1 | **Announce** | The declared audience is told it is starting, through the `announce` channels. |
| 2 | **Run** | The function is called with the run, and may write into it. |
| 3 | **Collect** | What it returned becomes one result: a headline and rows. |
| 4 | **Report** | The same audience is told how it went, through the `report` channels. |

A failure is a result like any other: the traceback's last line is kept,
the run is marked failed, and **step 4 still happens**. Silence is the
worst way for a task to fail.

The framework's own steps never fail the work. A notification backend
that is down is logged and stepped over; the run's page still holds
everything.

## Channels

`announce` and `report` each take any of:

| Channel | What it does |
| --- | --- |
| `notification` | A stored notification: the bell, the notifications page, and a toast on every page the reader has open |
| `mail` | An e-mail to each of the audience, with a link to the run |
| `page` | Nothing extra — the run's own page, which holds it all anyway |

`generic.tasks.ALL` is every channel that delivers something. A task
that should disturb nobody declares `("page",)` for both. The runs
table and a run's page refresh by themselves as the run moves on, for
whoever has them open.

Each message is written in the reader's own language, not the
announcer's: recipients are grouped by their `UserPreferences.language`
and each group's strings are built under that language.

## Audience

| `audience` | Who hears |
| --- | --- |
| `"trigger"` (default) | Whoever pressed the button — nobody, for a scheduled run |
| `"staff"` | Every active member of staff |
| `"superusers"` | Every active superuser |
| `"everyone"` | Every active user |
| a callable | `audience(run)` returns users |

## What a task may write

The run is the first argument, and it is a model instance:

```python
def nightly_digest(run):
    run.note("Collecting")            # one step, saved at once
    run.add("Tickets", 12)            # one line of the result
    run.arguments                     # what it was started with
```

`note()` saves immediately, so a task that takes ten minutes has a page
that fills up while it runs rather than one that appears at the end.

What the function returns is folded into the same result:

| Returned | Becomes |
| --- | --- |
| a string | the summary |
| `{"summary": ..., "results": [...]}` | both |
| a list | result rows, and the first one as the summary |
| `None` | whatever the function already wrote |

## Where the work happens

With Celery installed **and a broker configured**, the run is handed to
a worker: the row is written first, and its id is what travels. Without
one — a laptop, a test, a project that never set Celery up — the work
happens in the process that asked for it. The same code, the same four
steps, the same pages; only the waiting differs.

`CELERY_TASK_ALWAYS_EAGER` still counts as queued: it goes through
Celery, which is the point of eager.

The broker is the one of the Celery application the process has
loaded. A web server loads the project's only if the project's package
imports it, as Celery's guide for Django does:

```python
# mysite/__init__.py
from .celery import app as celery_app

__all__ = ["celery_app"]
```

Without it, only the worker has the application; the web server's
Celery has no broker, and every task started from a page runs in the
request while the worker waits.

## The pages

Three, in the **Tasks** group of the navigation:

- **Tasks** (`site:tasks`) — the catalogue: every declared task, what it
  does, who it tells, how its last runs went, and a button. Needs
  `generic.run_task`.
- **Runs** — every run as a table like any other, with a page each
  holding the result, the steps and the error. Read-only: a run is a
  record of something that happened. *Run again* starts another.
- **Schedules**, **Intervals**, **Crontabs**, **Clocked times** — the
  scheduler's own models, when `django_celery_beat` is installed.

`SHOW_TASKS` forces the pages on or off; left alone, they appear as soon
as there is something to show. `TASK_RECENT_RUNS` is how many runs the
catalogue lists under each task.

## Schedules

```bash
pip install django-celery-beat
```

```python
INSTALLED_APPS = [..., "django_celery_beat"]
```

Its models then appear as resources in the **Tasks** group — the same
tables, filters and forms as everything else, without sending anybody to
`/admin/`. A schedule names the task it runs (`myapp.tasks.nightly_digest`,
or whatever `name=` you gave it), and *Run now* starts a declared one
immediately.

Beat itself reads them with the database scheduler:

```bash
celery -A myproject.celery beat \
  --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Both Docker stacks (`docker/docker-compose.dev.yml` and
`docker-compose.prod.yml`) run it that way already, and the images
install it as below.

django-celery-beat's own metadata pins Django below 6.1. On a newer
Django install it with `--no-deps`; it works, and that pin is the only
thing in the way. It is a separate extra (`.[beat]`) for exactly that
reason, and the framework works without it — a project that has no
scheduler still gets the catalogue and the runs.

### The framework's own task

`generic.send_scheduled_mailings` sends the
[scheduled mailings](mailings.md) that are due. Give it a periodic
task every five minutes - or a cron line running
`manage.py send_scheduled_mailings`. It does not, on its own, make the
task pages appear: only a task the project declares does.

## Permissions

| Permission | Lets a user |
| --- | --- |
| `generic.run_task` | See the catalogue and start a run, by hand or from a schedule |
| `generic.view_taskrun` | Read the runs and their results |
| `django_celery_beat.*` | Manage the schedules, as for any other model |

A task may narrow it further with `permission="myapp.run_payroll"`.

## Testing a task

Call it through `launch()` — that exercises all four steps, in process:

```python
from generic.tasks.runner import launch


def test_it_counts_what_is_late(support_desk, staff_user):
    run = launch("example.overdue_digest")

    assert run.status == run.Status.SUCCESS
    assert run.results[0]["value"] == 1
```

`tests/test_tasks.py` has the rest: audiences, channels, failures, the
catalogue page and the schedules.

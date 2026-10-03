# Operations and reports

A page that simplifies things usually hides work that is not simple:
one button recomputes forty invoices, three customers have no address,
one invoice fails, and it may take minutes. Whoever pressed the button
needs to know **when it is done** - right away, or later if it ran in
the background - and **what went wrong**, readably: not a single
"Done.", not a traceback.

The framework gives that two pieces, used together or apart:

| Piece | What it is |
| --- | --- |
| **Report** (`generic.reports.Report`) | A tree of messages with a level (`info`, `success`, `warning`, `error`), grouped into sections that fold. Any code can write one. |
| **Operation** (`generic.tasks.operation`) | Work a page starts, done in the request or in the background, that keeps its report on a run and tells the person who started it when it ends. |

The browser side is built in: tables, summary pages and any custom page
draw the answer as a card in the toast area, with the tree in it.

```python
# myapp/tasks.py - imported at start-up by the framework and by Celery
from django.utils.translation import gettext, gettext_lazy as _

from generic.tasks import operation


@operation(label=_("Recompute invoices"), background=True)
def recompute_invoices(run, ids):
    for customer in Customer.objects.filter(pk__in=ids):
        # One section per customer: folded when fine, open otherwise.
        # isolated: an exception rolls this customer back, is written
        # as an error line, and the next customer goes on.
        with run.report.section(str(customer), isolated=True) as part:
            count = customer.recompute_invoices()
            part.success(gettext("%(count)s invoices recomputed.") % {"count": count})

            if not customer.address:
                part.warning(gettext("No address: nothing was sent."))

    return gettext("%(count)s customers") % {"count": len(ids)}
```

```python
# myapp/resources.py
from myapp.tasks import recompute_invoices


class CustomerResource(ModelResource):
    actions = ("recompute", "delete_selected")

    @action(description=_("Recompute invoices"), icon="calculate")
    def recompute(self, request, queryset):
        return recompute_invoices.start(
            request, ids=list(queryset.values_list("pk", flat=True))
        )
```

That is all. Select customers, run the action: the table answers at
once with a card saying the work is running; when it ends, the card
turns into the report - a section per customer, the ones with a warning
or an error open, the others folded with their counts - and the run
keeps all of it on a page of its own.

## Reports

```python
from generic.reports import Report

report = Report()
report.info("Read 120 rows")
report.success("118 imported")
report.warning("2 skipped", "Rows 14 and 37 have no code.")     # title, detail
report.error("SD-12 failed", url="/example/ticket/12/")           # a link

with report.section("Customer Acme") as section:                  # a section
    section.warning("No address")
    with section.section("Invoices") as invoices:                 # nested
        invoices.error("Invoice 12: the total is negative")
```

| Call | Does |
| --- | --- |
| `info / success / warning / error(title, detail="", **extra)` | One line. `detail` is a paragraph under it; `url` (a site path or http(s) address - anything else is dropped) makes the title a link; other keys travel with the line. |
| `section(title, detail="", *, isolated=False)` | A context manager; lines written inside are its children. A section shows the **worst level** inside it, so a folded one still says how it went. |
| `section(..., isolated=True)` | The block runs in a savepoint. An exception rolls it back, is logged, becomes the section's last line (`error`, the exception's own line) and **does not stop the work** - the pattern for "one item at a time". |
| `report.level` | `error` or `warning` when a line says so, `success` otherwise. |
| `report.counts()` | Lines per level (sections are not counted). |

A report holds at most 2000 lines; beyond, it says how many it left
out - work over a hundred thousand rows should report what went wrong,
not a line per row that went right.

Text only: a title or a detail is never HTML, in the card or on the
run's page.

### A report without an operation

An action that does its work in the request and keeps nothing can
return a report directly, and the page draws it the same way:

```python
@action(description=_("Audit"), icon="rule")
def audit(self, request, queryset):
    report = Report()

    for ticket in queryset:
        if not ticket.assignee_id:
            report.warning(ticket.reference, gettext("Nobody is on it."))

    return report            # or {"message": "...", "report": report}
```

## Operations

```python
@operation(
    name="",                  # default: the function's import path
    label=_("Recompute invoices"),
    description="",
    icon="bolt",
    background=False,         # the default for start()
    report=("notification",), # how a background run's end reaches its starter
    permission="",            # checked on every start, e.g. "billing.recompute"
)
def recompute_invoices(run, **arguments): ...
```

An operation is a [task](tasks.md) with three differences: the Tasks
page does not list it (it needs the arguments its page chose), it
reports only to **whoever started it**, and it is started from code:

```python
run = recompute_invoices.start(request, ids=[1, 2, 3])   # or a user
run = recompute_invoices.start(request, background=True, ids=[...])

from generic.tasks import start_operation
run = start_operation("billing.recompute_invoices", request.user, ids=[...])
```

Arguments are stored on the run and must be JSON - **primary keys, not
records**; anything else raises `TypeError` before anything starts.

Inside, the function gets the run: `run.report` is its report (saved as
it grows - once a second at most, and at the end of each section - so
the run's page shows long work as it goes), and everything a task has
is there too (`run.note()`, `run.add()`, `run.arguments`). What it
returns becomes the headline (a string, or `{"summary": ...}`); with
none, the headline counts the report: "1 error, 2 warnings".

### Where the work happens

| `background` | The request | The work | Its end |
| --- | --- | --- | --- |
| `False` (default) | waits | here, in the request | the answer carries the whole report; nobody is notified - the page is already showing it |
| `True` | answers at once | a Celery worker, when one can be reached | the page that started it is told (`operation.finished`, to that person only), and the person gets a notification leading to the run |
| `True`, no worker | answers at once | a thread of this process (`OPERATION_FALLBACK = "thread"`, the default), or the request (`"inline"`) | same as above |

"A worker can be reached" means Celery with a `broker_url` and not in
eager mode: eager runs in the request, which is exactly what background
work should not do. The thread fallback is what lets a project without
Celery - a laptop, a small server - still answer at once; it is not a
queue (the work is lost if the process stops), which is what a worker
is for. It starts after the transaction commits, so it finds its run.

The run is written in the language of whoever started it, wherever it
runs: `TaskRun.language`, active while the function runs.

### What the page is answered

Every answer has the shape any toast reads, plus the operation:

```json
{
  "message": "Recompute invoices is running in the background. You will be told when it is done.",
  "level": "info",
  "operation": {
    "id": 42, "label": "Recompute invoices", "finished": false,
    "status": "pending", "level": "info", "summary": "",
    "report": [], "counts": {"info": 0, "success": 0, "warning": 0, "error": 0},
    "error": "", "url": "/generic/taskrun/42/", "...": "..."
  }
}
```

A report node is `{"level", "title", "detail", "children", "url"?}`.
From an action, the answer also has `count`. A view of the project's
own answers the same way:

```python
from generic.tasks import operation_response

class RecomputeView(APIView):
    def post(self, request, pk):
        run = recompute_invoices.start(request, ids=[pk])
        return operation_response(run)      # 202 while it runs, 200 when done
```

`operation_response` and `operation_payload` also take a `Report`.

### In the browser

Tables (bulk actions) and summary pages (a record's actions) draw an
operation by themselves. Anywhere else:

```js
Generic.operations.post(url, body);      // POST, then draw the answer
Generic.operations.handle(answer);       // draw an answer already had
                                         // ({redirect: "/path/"} opens it)
Generic.operations.show(answer);         // the card, whatever it holds
```

The card (`js/operations.js`) shows the headline, a spinner while the
work runs, the tree - sections as `<details>`, open when something in
them is a warning or an error, closed with their counts otherwise - and
a link to the run's page. It stays until closed unless everything went
well. When the run ends elsewhere, the `operation.finished` event turns
the same card into the report; the bell does not toast the matching
notification a second time.

Without the WebSocket (`EVENTS_WEBSOCKET_URL: None`, the minimal
example) the card cannot be told: it says the work is running, and the
notification is there when the page next looks.

### The run's page

The notification leads to the run's page, which draws the report as
the same tree (`generic/components/report.html`) beside the result and
the steps. **Whoever started a run may open its page** without
`generic.view_taskrun`, which is still needed to list everybody's runs.

Operations alone - without any task of the catalogue - bring the Runs
pages, not the Tasks page. *Run again* leaves operations out: run on
what their page chose, they are started from that page.

## Settings

| Setting | Default | |
| --- | --- | --- |
| `OPERATION_FALLBACK` | `"thread"` | Where a background operation goes with no worker to reach: `"thread"` or `"inline"` |

## Testing an operation

Call it - in the request it is finished when `start()` returns:

```python
def test_it_warns_about_missing_addresses(user, customer):
    run = recompute_invoices.start(user, background=False, ids=[customer.pk])

    assert run.level == "warning"
    assert run.tree[0]["children"][-1]["title"] == "No address: nothing was sent."
```

`tests/test_operations.py` has the rest: isolation, the thread
hand-off (with a thread that runs when started), the events and
notifications, the run's page, and the example's two actions.

## In the example

*Support › Tickets*: select tickets, **Check** - done in the request, a
section per ticket. *Support › Customers*: select customers, **Review**
- in the background, the card turns into the report when it is done.
Both are in `example/tasks.py`.

# Calendars: records on their days

Tickets on the day they are due, maintenance visits on the day they are
planned, bookings from the day they start to the day they end: records
with a date, shown where that date falls. A resource declares the
calendar once, with `Calendar`, and gets:

- a page of its own, `<model>/<name>/`, with a button on the list (and,
  with `navigation=True`, an entry in the sidebar);
- ways of looking: a **month**, a **week** (every record of each day,
  with its values), a **day**, and a **list** of the month's days that
  hold something - with `hours=`, the week and the day are drawn **on
  the hours**, each record as long as it lasts;
- the search box and filter editor of the resource's own table above
  it - every column, the same chips and `status:open` syntax as the
  list - choosing what the calendar shows;
- each record coloured by one of its tag fields, linking to its page;
- with `editable=True`, records **dragged to another day** (or another
  time, and stretched longer or shorter), written through the table's
  own cell writer;
- with `allocate=`, a panel of related records - tasks, tickets - to
  **drop on a time**, each drop creating a record pointing at it;
- a refresh by itself when a record of the resource changes.

```python
from generic.sites import Allocate, Calendar, ModelResource, register


@register(Ticket)
class TicketResource(ModelResource):
    editable_fields = ("team", "assignee", "priority", "due_on")

    calendars = (
        Calendar(
            "due",
            date="due_on",
            title=_("Due dates"),
            icon="event",
            description=_("Every ticket on the day it is due."),
            color="priority",
            fields=("customer", "status", "assignee"),
            editable=True,
            navigation=True,
        ),
    )


@register(Booking)
class BookingResource(ModelResource):
    # A date and time, and a record lasting several days.
    calendars = (Calendar("plan", date="starts_at", end="ends_at"),)


@register(TimeEntry)
class TimeEntryResource(ModelResource):
    # A timesheet: entries on the hours, tasks dropped on a time.
    editable_fields = ("started_at", "ended_at", "comment")

    calendars = (
        Calendar(
            "timesheet",
            date="started_at",
            end="ended_at",
            label="task",
            editable=True,
            hours=(7, 20),
            step=15,
            views=("week", "day", "month", "list"),
            allocate=Allocate(
                "task",
                title=_("Tasks under way"),
                filters={"match": "all", "conditions": [UNDER_WAY]},
                fields=("project",),
                color="kind",
                duration=60,
            ),
        ),
    )
```

## Options

| Option | Default | Means |
| --- | --- | --- |
| `name` | - | lower case letters, digits and dashes: the page `<model>/<name>/`, the endpoint `api/<app>/<model>/calendars/<name>/` |
| `date` | - | the field the record falls on: a `DateField` or a `DateTimeField` |
| `end` | `None` | the day it ends, included - a date or date-and-time field; the record is drawn on each day between. Empty on a record: one day |
| `title`, `icon`, `description` | *Calendar*, `calendar_month`, none | the page's |
| `label` | the record's label | the event's text: a field, a resource method or a model attribute |
| `color` | `None` | a field (or a `@display(tags=...)` method) the resource draws as coloured tags (`tag_fields`): the event takes its first tag's colour |
| `fields` | `()` | values shown with the event - in the week and the list, and in its tooltip - typed as on a summary page |
| `editable` | `False` | records may be dragged to another day (below) |
| `views` | `("month", "week", "list")` | the ways of looking offered, the first one opening: `month`, `week`, `day`, `list` |
| `hours` | `None` | `(first, last)`, whole hours from 0 to 24: the week and the day drawn on these hours, a record as tall as it lasts (below). Needs a date-and-time `date` |
| `step` | `15` | minutes a drag snaps to on the hours: 5, 10, 15, 20, 30 or 60 |
| `allocate` | `None` | `Allocate(...)` or a foreign key's name: related records to drop on the calendar (below) |
| `navigation` | `False` | an entry in the sidebar, in the resource's group |
| `permission` | `None` | needed besides the resource's view permission, as a page's: `"change"`, a permission string, several, or `callable(user)` |

The week starts on the language's first day (`FIRST_DAY_OF_WEEK`:
Sunday in English, Monday in French). A date and time is placed on the
day it falls on in the reader's time zone, its time shown before its
label. The address keeps the view and the day shown
(`?view=week&date=2026-10-07`), so a calendar can be bookmarked.

## The filters above it

The page carries the resource's own table with its rows hidden - its
search box, its filter editor, its chips - as a tree's page does. The
calendar follows them: every request it makes carries the table's
`filters` and `search`, applied by the same backends as the list's.
Nothing is declared for it.

## Moving a record

With `editable=True`, a record dragged onto another day gets that day.
The write goes through `save_editable` - the same writer as a table's
editable cells ([Editing in the table](editable.md)) - so:

- the `date` (and `end`) must be among the resource's
  `editable_fields`, or the declaration raises;
- the change permission, the per-row `can_edit_column`, the form
  serializer's validation and an overridden `save_editable` all apply;
- a date and time keeps its time of day; an `end` moves by as many days
  as the start.

A reader without the change permission sees records they cannot drag.
A refusal (a validation error, a column frozen for that row) comes back
as a message, and the calendar draws what is stored.

Each day of the month and the week also offers *Add* (on hover) to a
reader who may add: the add form, with the date already filled in.

## On the hours

With `hours=(7, 20)` - and a date-and-time `date` - the week and the
day are drawn as a column of hours a day, as an agenda is: a record
starts where its time falls and is as tall as it lasts (`end`; a
record without one is drawn as a short mark). Records at the same time
sit side by side. A record before the first hour or after the last is
drawn on the edge; the hours of the day the reader is in are marked,
with a line at the current time; each day's header gives the total of
its records' hours.

With `editable=True`:

- a record dragged to another time **starts there**, its end moving
  with it (its length is kept);
- the handle at its foot **stretches it** - a later or earlier end;
- dragging across the empty hours of a day opens the add form (in a
  popup) with the start and the end filled in; the calendar refreshes
  when it is saved.

Every move snaps to `step` minutes. The browser sends the reader's
wall clock (`YYYY-MM-DDTHH:MM`), read in the current time zone.

## Dropping records on it: `allocate`

```python
Allocate(
    "task",                       # a foreign key of the calendar's model
    title=_("Tasks under way"),   # the panel's title (default: the model's)
    filters={...},                # a filter tree, as presets write it
    ordering=("-created_at",),    # default: the related list's
    fields=("project",),          # values shown with each, summary-typed
    color="kind",                 # a tag field of the related resource
    duration=60,                  # minutes a dropped record lasts
    limit=20,                     # a page of the panel (at most 50)
)
```

A panel beside the calendar lists the related resource's records - its
list queryset, so its own scoping applies - narrowed by `filters`, with
a search box and *More*. A record dragged from it onto a time (or a day,
on a date-only calendar) **creates a record** of the calendar's
resource: the `date` at that time, the `end` `duration` minutes later,
the foreign key pointing at the record dropped. The creation goes
through `create_editable` - the add form's serializer and
`save_model` - so a resource that fills in the person, numbers the
record or checks something else does it there:

```python
def create_editable(self, request, values, fixed):
    return super().create_editable(
        request, values, {"user": request.user.pk, **fixed}
    )
```

The panel shows to a reader with the add permission and the related
resource's view permission. A timed calendar that allocates must draw
`hours`.

## Endpoints

| | |
| --- | --- |
| `GET api/<app>/<model>/calendars/<name>/?start=&end=` | the records from `start` to `end` (excluded, ISO days, at most 62 days): `{start, end, truncated, editable, events: [{id, label, url, start, end, time, color, background, cells, editable}]}`; the table's `filters` and `search` apply |
| `PATCH api/<app>/<model>/<pk>/calendars/<name>/` | `{"date": "YYYY-MM-DD"}`: the record moved to that day; on the hours, `{"start"}` (the end moves with it), `{"end"}` or both, `YYYY-MM-DDTHH:MM`: answered as an event |
| `POST api/<app>/<model>/calendars/<name>/` | with `allocate`: `{"record", "start", "end"?}`: a record created on that time (or day), pointing at `record`; 201, answered as an event |
| `GET api/<app>/<model>/calendars/<name>/sources/?q=&page=` | with `allocate`: the records offered, `{items: [{id, label, url, color, background, cells}], more, page}` |

Each event also carries `startsAt` and `endsAt`, the reader's wall
clock to the minute (empty for a date).

Records come from the list's queryset (`get_list_queryset`), so a
reader never sees one the list would not show them; at most 2,000 a
range, `truncated` past it. A range that cannot be read, ends before
it starts or is too wide is a 400; an unknown calendar, or one whose
page the reader may not open, a 404; reading needs the view
permission, moving the change permission, dropping the add permission
(403); a record dropped that the related list does not hold, a 404; an
end before its start, a 400.

## Checked where it is written

At registration, `ImproperlyConfigured` naming the resource for: a
name that is not an address piece, the same name twice, a `date` or
`end` that is not a date or date-and-time field, views outside month,
week, day and list, a `label`, `color` or field the summary page could
not show, `editable=True` without the date among the `editable_fields`;
`hours` that are not two whole hours in order, or on a date-only field;
a `step` outside 5, 10, 15, 20, 30, 60; an `allocate` that is not a
foreign key, on a timed calendar without `hours`, with `fields` as a
string, a duration that is not a number of minutes, or filters that
are not a filter tree.

## In the browser

`generic/resource/calendar.html` (block `page_content`),
`js/calendar.js` (`Generic.calendar.start(element)`, started by
`.generic-calendar[data-autostart]`), `css/calendar.css`. Values are
drawn by `js/values.js` (`Generic.values.render`), shared with the tree
and the dashboard's cards.

The example's tickets have two: *Support › Due dates*, and *Arrivals*,
on the hours. The logbook's timesheet (`logbook/`) allocates tasks.

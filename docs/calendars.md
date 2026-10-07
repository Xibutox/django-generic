# Calendars: records on their days

Tickets on the day they are due, maintenance visits on the day they are
planned, bookings from the day they start to the day they end: records
with a date, shown where that date falls. A resource declares the
calendar once, with `Calendar`, and gets:

- a page of its own, `<model>/<name>/`, with a button on the list (and,
  with `navigation=True`, an entry in the sidebar);
- three ways of looking: a **month**, a **week** (every record of each
  day, with its values), and a **list** of the month's days that hold
  something;
- the search box and filter editor of the resource's own table above
  it - every column, the same chips and `status:open` syntax as the
  list - choosing what the calendar shows;
- each record coloured by one of its tag fields, linking to its page;
- with `editable=True`, records **dragged to another day**, written
  through the table's own cell writer;
- a refresh by itself when a record of the resource changes.

```python
from generic.sites import Calendar, ModelResource, register


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
| `views` | `("month", "week", "list")` | the ways of looking offered, the first one opening |
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

## Endpoints

| | |
| --- | --- |
| `GET api/<app>/<model>/calendars/<name>/?start=&end=` | the records from `start` to `end` (excluded, ISO days, at most 62 days): `{start, end, truncated, editable, events: [{id, label, url, start, end, time, color, background, cells, editable}]}`; the table's `filters` and `search` apply |
| `PATCH api/<app>/<model>/<pk>/calendars/<name>/` | `{"date": "YYYY-MM-DD"}`: the record moved to that day, answered as an event |

Records come from the list's queryset (`get_list_queryset`), so a
reader never sees one the list would not show them; at most 2,000 a
range, `truncated` past it. A range that cannot be read, ends before
it starts or is too wide is a 400; an unknown calendar, or one whose
page the reader may not open, a 404; reading needs the view
permission, moving the change permission (403).

## Checked where it is written

At registration, `ImproperlyConfigured` naming the resource for: a
name that is not an address piece, the same name twice, a `date` or
`end` that is not a date or date-and-time field, views outside month,
week and list, a `label`, `color` or field the summary page could not
show, `editable=True` without the date among the `editable_fields`.

## In the browser

`generic/resource/calendar.html` (block `page_content`),
`js/calendar.js` (`Generic.calendar.start(element)`, started by
`.generic-calendar[data-autostart]`), `css/calendar.css`. Values are
drawn by `js/values.js` (`Generic.values.render`), shared with the tree
and the dashboard's cards.

The example's tickets have one: *Support › Due dates*.

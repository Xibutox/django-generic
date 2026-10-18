# Boards: records as cards, a column per value

Tickets by priority, tasks by stage, machines by site: records sorted
into columns by one of their fields, a card each. A resource declares
the board once, with `Board`, and gets:

- a page of its own, `<model>/<name>/`, with a button on the list (and,
  with `navigation=True`, an entry in the sidebar);
- a column per value of the field - each choice, *Yes* and *No*, or each
  related record - with its count, plus *Not set* when the field may be
  empty;
- the search box and filter editor of the resource's own table above
  it, choosing the cards, as on a calendar's page;
- each card coloured by one of its tag fields, linking to its page, with
  the values you name;
- with `editable=True`, cards **dragged to another column**, or sent
  there from their *Move to* menu by keyboard, written through the
  table's own cell writer;
- a refresh by itself when a record of the resource changes.

```python
from generic.sites import Board, ModelResource, register


@register(Ticket)
class TicketResource(ModelResource):
    editable_fields = ("team", "assignee", "priority", "due_on")
    tag_fields = {"priority": {...}, "status": {...}}

    boards = (
        Board(
            "priorities",
            field="priority",
            title=_("Priorities"),
            description=_("Every ticket in the column of its priority."),
            color="status",
            fields=("team", "assignee", "due_on"),
            editable=True,
            navigation=True,
        ),
    )
```

## Options

| Option | Default | Means |
| --- | --- | --- |
| `name` | - | lower case letters, digits and dashes: the page `<model>/<name>/`, the endpoint `api/<app>/<model>/boards/<name>/` |
| `field` | - | the field whose values are the columns: one with `choices`, a `BooleanField`, or a `ForeignKey` |
| `title`, `icon`, `description` | *Board*, `view_kanban`, none | the page's |
| `columns` | `None` | the values shown, in this order: choice values, or a relation's primary keys. `None`: every choice, every related record the reader may see |
| `show_empty` | `True` | a *Not set* column, last, for records without a value, when the field allows none |
| `label` | the record's label | the card's text: a field, a resource method or a model attribute |
| `color` | `None` | a field (or a `@display(tags=...)` method) the resource draws as coloured tags (`tag_fields`): the card takes its first tag's colour |
| `fields` | `()` | values shown on the card, typed as on a summary page |
| `editable` | `False` | cards may be moved to another column (below) |
| `navigation` | `False` | an entry in the sidebar, in the resource's group |
| `permission` | `None` | needed besides the resource's view permission, as a page's: `"change"`, a permission string, several, or `callable(user)` |

A column takes the colour of its value's tag when the resource draws
the field as tags (`tag_fields`). A relation's columns are its records
that the reader may see - through the related resource's queryset when
it is registered - at most 30 (`MAX_COLUMNS`); past that, name them with
`columns`. A column answers its first 100 cards (`MAX_CARDS`) and the
count of all of them; past that it says so: filter the table.

## Moving a card

With `editable=True`, a card dropped on another column takes that
column's value (*Not set* empties it). Every card also has a *Move to*
menu, shown on hover and focus, doing the same from the keyboard or a
screen reader. The write goes through `save_editable`, the writer of a
table's editable cells ([Editing in the table](editable.md)), so:

- the `field` must be among the resource's `editable_fields`, or the
  declaration raises;
- the change permission, the per-row `can_edit_column`, the form
  serializer's validation and an overridden `save_editable` all apply;
- a state field (`transitions`) changes through its transitions only:
  a board on one cannot be `editable`, and stays a view.

A reader without the change permission sees cards they cannot move. A
refusal comes back as a message, and the board draws what is stored.

Each column but *Not set* also offers *Add* to a reader who may add:
the add form, with the column's value filled in.

## Endpoints

| | |
| --- | --- |
| `GET api/<app>/<model>/boards/<name>/` | `{editable, columns: [{key, label, color, background, count, truncated, cards: [{id, label, url, column, color, background, cells, editable}]}]}`; the table's `filters` and `search` apply |
| `PATCH api/<app>/<model>/<pk>/boards/<name>/` | `{"column": key}` (`null` for *Not set*): the record moved to that column, answered as a card |

Cards come from the list's queryset (`get_list_queryset`), so a reader
never sees one the list would not show them. A column the board lacks
is a 400; an unknown board, or one whose page the reader may not open,
a 404; reading needs the view permission, moving the change permission
(403).

## Checked where it is written

At registration, `ImproperlyConfigured` naming the resource for: a
name that is not an address piece, the same name twice (or a
calendar's), a `field` that is not a field or has neither choices nor a
yes or no nor a relation, `fields` or `columns` given as one string, a
`label`, `color` or field the summary page could not show,
`editable=True` on a state field or without the field among the
`editable_fields`.

## In the browser

`generic/resource/board.html` (block `page_content`), `js/board.js`
(`Generic.board.start(element)`, started by
`.generic-board[data-autostart]`), `css/board.css`. Values are drawn by
`js/values.js` (`Generic.values.render`), shared with the calendar, the
tree and the dashboard's cards.

The example's tickets have one: *Support › Priorities*.

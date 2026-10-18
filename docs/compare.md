# Comparing records side by side

Two quotes for the same part, three tickets that look like the same
fault, a handful of articles to choose between: a few records set side
by side, a column each, the values that differ marked. A resource names
the fields to compare, and its list's selection bar offers *Compare the
selected ...*.

```python
from generic.sites import ModelResource, register


@register(Ticket)
class TicketResource(ModelResource):
    # The summary page's sections and fields, in its order.
    compare_fields = True


@register(Article)
class ArticleResource(ModelResource):
    # These fields only, in this order.
    compare_fields = ("kind", "unit", "unit_cost", "family", "component_count")
```

## What the reader gets

- In the list, *Compare the selected tickets* in the selection bar's
  menu, for two to six rows ticked (`MAX_COMPARED`). "Every matching
  row" is not compared: the records are named.
- The page `<model>/compare/?ids=3,8,12`: a column per record, in the
  order ticked, its label linking to its page; a row per field, each
  value drawn as the summary page draws it (tags, links, files, yes or
  no); the rows whose values differ marked - in colour, and for a
  screen reader in words.
- *Only the differences*, a switch hiding the rows alike and the
  sections left with none.
- With three records or more, each one can be taken out; the address
  follows, so a comparison can be bookmarked and shared.

The page has no button on the list: without the records it compares it
would be empty.

## The values

`compare_fields = True` takes the summary page's sections
(`detail_fieldsets`, or the form's fieldsets) with their titles. A
tuple names fields, model attributes or resource methods - anything a
summary page can show - in one section. Each value is described by the
summary page's own `describe_entry`; two values are the same when they
show the same thing.

## Who sees what

Records are read through the resource's list queryset
(`get_list_queryset`) and each one's `has_view_permission`: a record
the reader may not see is left out, counted in `missing` as one that
does not exist. Comparing needs the view permission only, and the
page's: a project page declared as `compare` takes the place of the
generated one.

## Endpoint

| | |
| --- | --- |
| `GET api/<app>/<model>/compare/?ids=3,8,12` | `{records: [{id, label, url}], sections: [{name, title, rows: [{name, label, same, values}]}], missing}`; `values` are summary-typed entries, one per record |

Fewer than two keys, or more than six, is a 400; a resource that
compares nothing, a 404; no view permission, a 403.

## Checked where it is written

At registration, `ImproperlyConfigured` naming the resource for a
field the summary page could not show, or `compare_fields` given as one
string.

## In the browser

`generic/resource/compare.html` (block `page_content`),
`js/compare.js` (`Generic.compare.start(element)`, started by
`.generic-compare[data-autostart]`), `css/compare.css`. The selection
bar's entry lives in `js/datatables/selection.js`.

The example compares tickets (*Support › Tickets*) and articles
(*Manufacturing › Articles*).

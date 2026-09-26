# Charts

Charts follow the rest of the framework: **the server computes, the
browser draws**. A chart is declared on a resource, like its columns;
DRF serves its data as JSON; `generic/js/charts.js` loads it and draws
it with [Apache ECharts](https://echarts.apache.org/).

```python
from django.db.models import Sum
from generic.sites import Chart, ModelResource, RelatedTable, register


@register(Ticket)
class TicketResource(ModelResource):
    charts = (
        Chart("by_status", title=_("Tickets by status"),
              type="donut", group_by="status"),
        Chart("opened", title=_("Tickets opened"),
              group_by="opened_at", split_by="priority", stacked=True,
              period="week", periods=("day", "week", "month", "quarter")),
        Chart("by_tag", title=_("Tickets by tag"),
              group_by="tags", horizontal=True),
    )
    list_charts = ("by_status", "opened")      # above the list
```

That is a chart above the ticket list, following the table's filters,
and an endpoint anyone may call:

```
GET /api/example/ticket/charts/opened/?period=month&filters=...
```

## Why ECharts

The framework used to be paired with Plotly. ECharts replaces it here
for reasons specific to an application built on design tokens:

- **Themed from the tokens.** The chart reads the computed colours of
  the page — text, lines, surfaces, the accent — and builds its palette
  in OKLCH from the user's accent hue and colourfulness. A chart follows
  the dark scheme and the appearance sliders like everything else, and
  redraws when they move.
- **The types a business application uses**, in one file: bars, lines,
  areas, pies, donuts, funnels, heatmaps — and scatter, gauges, sankeys,
  treemaps or calendars through `options` or a customiser.
- **Canvas rendering** that stays smooth with thousands of points, a
  zoom slider for long series, and built-in accessibility descriptions.
- **Size.** 1.1 MB minified — the size of Plotly's *basic* bundle,
  which only draws bars, lines and pies — Apache 2.0, vendored, and
  **loaded only when a chart becomes visible**: a page without a chart
  never fetches it.

The payload names no library, so another renderer could replace
`charts.js` without touching a resource.

## Declaring a chart

A chart groups the resource's records by one field, optionally splits
them by a second, and shows an aggregate per group — a count by default.

| Option | Meaning |
| --- | --- |
| `name` | Identifies the chart in its URL: `charts/<name>/` |
| `title`, `description`, `icon` | The card's heading; `icon` is a Material Symbols name |
| `type` | `bar` (default), `line`, `area`, `pie`, `donut`, `funnel`, `heatmap` |
| `group_by` | The categories: a field path — see below |
| `split_by` | A second path: one series per value, or the rows of a heatmap |
| `value` | The aggregate: `Count("pk", distinct=True)` by default; `Sum("hours")`, `Avg(...)`... |
| `value_label`, `unit`, `decimals` | How values read: `"Hours"`, `"h"`, `1` |
| `value_format` | `integer`, `decimal` or `percent` (values already in 0-100); worked out when left out |
| `period`, `periods` | The bucket of a date dimension, and the ones the user may switch between |
| `stacked`, `horizontal` | Stack the series; draw the bars sideways |
| `limit` | Keep the largest categories, the rest gathered as *Other* |
| `order` | `"value"`, `"-value"` or `"label"`; see below |
| `colors` | Colours by key, a colour attribute of the related records, or a `TagStyle` |
| `height` | Of the drawing, as CSS: `"18rem"` |
| `options` | ECharts settings merged over the generated ones (JSON only) |
| `permission` | A permission string or `callable(request)`, on top of the resource's view permission |
| `data` | A callable computing the data instead — see below |

A wrong declaration — an unknown type, period or format, no `group_by`
without `data` — raises `ImproperlyConfigured` at start-up; a
`group_by` that is not a field path raises on the first request.

### What a dimension may be

`group_by` and `split_by` accept any field path of the model, through
relations — `"team"`, `"customer__segment"`, `"time_entries__agent"`:

| Field | Categories | Natural order |
| --- | --- | --- |
| Foreign key, many-to-many, reverse relation | the related records, by their label | largest first |
| A field with choices | the choice labels | the choices' order |
| Boolean | "Billable: Yes", "Billable: No" | yes first |
| Date, date-time | buckets of `period`: `day`, `week` (Monday), `month`, `quarter`, `year`, **gaps filled** with zero | chronological |
| Anything else | the values themselves | largest first |

Records without a value form a *None* category, always last. Dates are
bucketed in the active timezone.

`order` overrides the natural order: `"-value"` largest first, `"value"`
smallest first, `"label"` alphabetical. `limit` never applies to dates.

### Colours

When `colors` is left out, a dimension named in the resource's
`tag_fields` takes the colours of its tags — declared once, used twice:
a status is the same blue in the table, on the summary page and in the
chart. Otherwise:

```python
Chart("by_team", group_by="team",
      colors={1: "#2563eb", 2: "#16a34a"})          # by key
Chart("by_tag", group_by="tags", colors="color")    # an attribute of Tag
Chart("by_tag", group_by="tags",
      colors=TagStyle(background="background"))     # a style
```

Series without a colour take the palette: the accent's hue first, then
hues spread around the wheel at one perceptual lightness, so no series
shouts louder than another and all of them read on the page's surface.

### Which records

The endpoint takes **the table's own parameters** and applies them the
way the table does, through the same whitelists:

| Parameter | Effect |
| --- | --- |
| `filters` | The table's filter tree, as it sends it (or the older `advanced_filters`) |
| `search` or `search[value]` | The search box |
| `_related=<app>.<model>.<table>:<pk>` | The rows of one record's related table |
| `period` | One of the chart's `periods`; anything else is a 400 |

The aggregate runs over the resource's plain `get_queryset(request)`,
selected by primary key from the filtered list queryset: the table's
annotations and joins never inflate a count.

An aggregate over a many-valued relation, grouped by another many-valued
relation, multiplies — as any SQL join would. Compute that kind of chart
with `data`.

## Where charts are drawn

**Above a list** — `list_charts`: the charts follow the table. Each
request carries the table's current filters and search; a click on a bar,
a slice or a heatmap cell filters the table on what was clicked, for
both dimensions when there are two, if the column has a filter that can
say it.

**On a summary page** — through the related tables, so a chart about a
record is always a chart of its related rows:

```python
class CustomerResource(ModelResource):
    related_tables = (
        RelatedTable("tickets", charts=("by_status", "by_tag")),
        RelatedTable("time_spent", model=TimeEntry,
                     lookup="ticket__customer", charts=("hours_by_agent",)),
    )
    detail_charts = ("time_spent.hours_by_month", "tickets.opened")
```

`RelatedTable(charts=...)` names charts of the *related* resource, drawn
in the table's tab and following its filters. `detail_charts` draws
`"<related table>.<chart>"` between the figures and the sections. Both
carry the `_related` parameter, so they are narrowed to the record and
answer to the same permission check as the table.

**Anywhere else** — a dashboard, a custom page:

```django
{% load generic_ui %}
<div class="chart-grid">
  {% generic_chart "example.ticket" "opened" %}
  {% generic_chart "example.ticket" "by_status" title="Right now" height="14rem" %}
</div>
```

The tag draws nothing for a user without the permission. It accepts
`title`, `description`, `height` and `period`.

A chart is a card with the title, a period switch when the dimension is
a date, a button showing the figures as a table — for reading exact
values, and for screen readers — and one downloading the image.

## Computed charts

When one query cannot say it — two sums over two relations, data from
elsewhere — `data` computes the payload. It receives the records the
request's filters allow, and the period:

```python
def effort_by_team(chart, request, queryset, period):
    estimated = dict(queryset.values_list("team").annotate(Sum("estimated_hours")))
    logged = dict(TimeEntry.objects.filter(ticket__in=queryset)
                  .values_list("ticket__team").annotate(Sum("hours")))
    teams = Team.objects.filter(pk__in={*estimated, *logged})

    return {
        "categories": [team.name for team in teams],
        "dimension": {"name": "team", "kind": "relation"},   # optional:
        "keys": [team.pk for team in teams],                 # clicks filter
        "series": [
            {"name": "Estimated", "data": [estimated.get(t.pk, 0) for t in teams]},
            {"name": "Logged", "type": "line",               # a line over bars
             "stack": False,
             "data": [logged.get(t.pk, 0) for t in teams]},
        ],
        "value": {"label": "Hours", "format": "decimal", "unit": "h", "decimals": 1},
    }


Chart("effort", title=_("Estimated and logged hours"), data=effort_by_team)
```

A series may set its own `type` (`bar`, `line`), `color`, `stack` (a
stack name, or `False` to stay out of a stacked chart) and `area`.

### A chart from any DRF view

Charts do not have to belong to a resource. Any view returning the
payload is drawn the same way — `chart_payload` builds and normalises
it:

```python
from generic.sites import chart_payload

class WorkloadView(APIView):
    def get(self, request):
        ...
        return Response(chart_payload(
            type="bar",
            categories=days,
            series=[
                {"name": project.name, "data": hours[project.pk]}
                for project in projects
            ] + [{"name": "Capacity", "type": "line", "stack": False,
                  "data": capacity}],
            stacked=True,
            value={"label": "Hours", "format": "decimal", "unit": "h"},
        ))
```

and in the page, the card with the configuration it expects — it
writes the configuration into the page itself:

```python
# the page's view
context["workload"] = {
    "config_id": "workload-chart",
    "config": {
        "title": _("Workload"),
        "url": reverse("workload"),
        "height": "24rem",
        "periods": [],
        # Sent with every request: the page's own filters.
        "extraParams": {"group": "3"},
    },
}
```

```django
{% include "generic/charts/chart.html" with chart=workload %}
```

When the page's own filters change, send the new parameters — a `null`
or `""` leaves one out — and the chart reloads. The event may start
anywhere on the page; name the chart, or leave `chart` out to reach every
chart:

```django
<form x-data="{ group: '' }"
      @change="$dispatch('generic:chart-params',
               { chart: 'workload', params: { group: group } })">
  <select class="input input--sm" x-model="group">...</select>
</form>
```

```javascript
document.dispatchEvent(new CustomEvent("generic:chart-params", {
  detail: { chart: "workload", params: { group: "4", user: null } }
}));
```

`chart` matches the configuration's `name`.

## The payload

```json
{
  "name": "opened",
  "title": "Tickets opened",
  "type": "bar",
  "stacked": true,
  "horizontal": false,
  "period": "week",
  "dimension": {"name": "opened_at", "kind": "date", "period": "week"},
  "split": {"name": "priority", "kind": "choice"},
  "categories": ["03/02/2026", "03/09/2026"],
  "keys": ["2026-03-02", "2026-03-09"],
  "ranges": [{"from": "2026-03-02", "to": "2026-03-08"}, ...],
  "series": [
    {"name": "Low", "key": "low", "data": [3, 0], "color": "#64748b"},
    {"name": "High", "key": "high", "data": [1, 2], "color": "#ea580c"}
  ],
  "colors": null,
  "value": {"label": "Tickets", "format": "integer", "unit": "", "decimals": 0},
  "total": 6,
  "empty": false,
  "options": {}
}
```

| Key | Meaning |
| --- | --- |
| `categories` | Labels of the groups, in order, formatted in the user's language |
| `keys` | The raw value of each group — a primary key, a choice, an ISO date — for clicks |
| `ranges` | For a date dimension, each bucket's first and last day |
| `series[].data` | One number per category |
| `colors` | For a single series, a colour per category (a pie's slices) |
| `dimension`, `split` | What was grouped by: the table column a click filters |
| `value` | How numbers read |
| `empty` | Nothing but zeros: the card says so rather than drawing an empty frame |
| `options` | Merged into the ECharts options |

## The browser side

```html
<section x-data="genericChart('config-id')">...</section>
```

`generic/charts/chart.html` is the card; `generic/charts/grid.html` lays
several side by side. `charts.js` loads with every page (it is small)
and fetches ECharts, and its French locale when the page is in French,
the first time a chart is visible — a chart in a closed tab waits for
the tab.

The card redraws when the theme, the scheme or the appearance sliders
change; reloads when a record of its model changes anywhere (the
`resource.changed` event); and, when linked to a table, reloads when the
table's filters change for any reason.

What JSON cannot carry — a formatter function, say — a customiser adds:

```javascript
Generic.charts.customize("opened", function (option, payload, theme) {
  option.xAxis.axisLabel.rotate = 45;
  return option;
});
```

`"*"` customises every chart. `Generic.charts.readTheme()` gives the
resolved token colours and palette, `Generic.charts.buildOption(payload,
theme)` the options a payload makes, and `Generic.charts.load()` a
promise of the `echarts` global, for a page drawing something of its
own.

## Security

- A chart is only reachable through a resource the user may view, and
  its optional `permission`; otherwise 403 or 404.
- Grouping paths come from the declaration, never from the request. The
  request may only pick among the declared `periods`.
- Filters go through the table serializer's whitelist, `_related`
  through the resource's declaration: the chart can never see a row the
  table would not show.
- Labels are drawn on a canvas, and tooltips escape them; colours are
  checked against the same strict pattern as tags before they are used.

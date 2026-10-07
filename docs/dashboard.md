# Key figures and cards on the dashboard

The dashboard opens with what a reader should know before going
anywhere: a few numbers, and a few records. Both are declared on the
resource whose rows they are made of, and both are drawn for whoever
may read that resource - nobody else.

- **Key figures** (`Kpi`): a number - a count, or any aggregate - over
  the rows the list would show under a filter. Its tile opens that list,
  filtered alike, so the number and the list always agree. Thresholds
  colour it.
- **Cards** (`Cards`): a few records drawn as tiles - the most pressing,
  the latest - with their label, a subtitle, a picture and a few
  values. *See all* opens the list, filtered alike.

Both refresh by themselves when a record of their resource changes.

```python
from django.db.models import Avg, Sum
from generic.sites import Cards, Kpi, ModelResource, register

STILL_OPEN = {"column": "status", "operator": "any_of",
              "value": ["open", "pending"]}


@register(Ticket)
class TicketResource(ModelResource):
    kpis = (
        Kpi(
            "open",
            title=_("Open tickets"),
            icon="inbox",
            description=_("Open or waiting for the customer."),
            filters={"match": "all", "conditions": [STILL_OPEN]},
            warning=150,
            danger=200,
        ),
        Kpi(
            "overdue",
            title=_("Overdue"),
            filters={"match": "all", "conditions": [
                STILL_OPEN,
                {"column": "due_on", "operator": "older_than_days",
                 "value": 1},
            ]},
            warning=1,
            danger=10,
        ),
        Kpi(
            "satisfaction",
            title=_("Satisfaction"),
            filters={"status": {"operator": "any_of", "value": ["closed"]}},
            value=Avg("satisfaction"),
            unit="/ 5",
            decimals=1,
            warning=3.5,          # danger below warning:
            danger=3,             # the lower, the worse
        ),
    )

    cards = (
        Cards(
            "pressing",
            title=_("Pressing tickets"),
            icon="local_fire_department",
            filters={"match": "all", "conditions": [
                STILL_OPEN,
                {"column": "priority", "operator": "any_of",
                 "value": ["urgent", "high"]},
            ]},
            ordering=("due_on", "-opened_at"),
            subtitle="customer",
            fields=("priority", "status", "assignee", "due_on"),
            limit=6,
        ),
    )
```

## The filter

`filters` is a filter tree over the **list's columns**, exactly as
`presets` write one ([Data tables](tables.md)) - or the older flat form,
one condition per column. It is read by the list's own whitelist and
filter engines, so:

- a key figure counts what its list shows - relative dates included:
  *opened this month*, *due more than a day ago* stay true tomorrow;
- the tile and *See all* open the list with the same tree in the
  address (`?filters=...`), already narrowed;
- a column the list does not offer is a mistake of the declaration,
  raised as `ImproperlyConfigured` naming it the first time the figure
  is asked for - never answered with every row.

No filter: every row the reader may see.

## Key figures - `Kpi`

| Option | Default | Means |
| --- | --- | --- |
| `name` | - | lower case letters, digits, `-`, `_`: `api/<app>/<model>/kpis/<name>/` |
| `title`, `icon`, `description` | the resource's plural name, its icon, none | what the tile shows |
| `filters` | `None` | the filter tree (above) |
| `value` | `None` (how many rows) | an aggregate (`Sum("hours")`, `Avg("satisfaction")`), or a `callable(request, queryset)` returning a number |
| `unit` | `""` | written after the number: `"h"`, `"EUR"`, `"/ 5"` |
| `decimals` | 0 for a count, 2 otherwise | decimal places shown |
| `warning`, `danger` | `None` | thresholds colouring the tile; `danger` above `warning` (or alone): the higher, the worse; below it: the lower, the worse. Reached: amber, red; neither: green |
| `permission` | `None` | needed besides the resource's view permission: a permission string, several, or `callable(request)` |
| `order` | 0 | its place on the dashboard, before the resource's own `order` |

The figure is computed over `get_list_queryset(request)` narrowed by
the filter, then re-selected by key from `get_queryset(request)` before
aggregating - the list's annotations and joins would count rows twice.
A team-scoped resource ([Teams](teams.md)) gives each reader their own
teams' figure. An aggregate over no row is no figure (`-`), not zero.

## Cards - `Cards`

| Option | Default | Means |
| --- | --- | --- |
| `name` | - | `api/<app>/<model>/cards/<name>/` |
| `title`, `icon`, `description`, `filters`, `permission`, `order` | | as a key figure's |
| `ordering` | the resource's | fields of the model, `-` for descending; records without the value come **last** whichever way, on every database |
| `limit` | 6 | how many, 1 to 24 |
| `subtitle` | `None` | under the label: a field, a resource method or a model attribute |
| `fields` | `()` | values on each card, the same way |
| `image` | `None` | a file field holding a picture (PNG, JPEG, GIF, WebP), drawn at the top; served by the record's own download, so `may_download` applies |

Values are typed as on a summary page - links to related records,
coloured tags (`tag_fields`), dates in the reader's language, booleans
- and the card's label links to the record. The heading counts every
matching record, not only those shown.

## Where they show

On the dashboard (`generic/site/index.html`), after the shortcuts:
the blocks `dashboard_kpis` and `dashboard_cards`, which a project's
dashboard template may move or empty. Each tile and each set of cards
is drawn at once without its data, then filled from its endpoint
(`js/dashboard.js`, `css/dashboard.css`, loaded only when there is
something to draw) and filled again, debounced, when its resource
announces a change.

Across resources, the order is each declaration's `order`, then the
resource's `order`, then its name.

## Checked where it is written

Each declaration is checked when the resource is registered, and
raises `ImproperlyConfigured` naming the resource: a name that is not
an address piece, the same name twice, a value that is neither an
aggregate nor a callable, a threshold that is not a number, a filter
that is not a tree, a card field, subtitle or ordering the model does
not have, an image that is not a file field, a limit out of range.

## Endpoints

| | |
| --- | --- |
| `GET api/<app>/<model>/kpis/<name>/` | `{name, title, value, display, unit, level, url}` - `level` is `good`, `warning`, `danger` or empty |
| `GET api/<app>/<model>/cards/<name>/` | `{name, title, items: [{id, label, url, subtitle, image, cells}], total, url}` |

Both need the resource's view permission (403 without), and answer 404
for a name not declared - or declared with a `permission` the reader
lacks. The browser never names a column or a path: the filter, the
aggregate and the order are the declaration's.

The example declares four key figures and the *Pressing tickets* cards
on tickets, and *Hours this month* on time entries
(`example/resources.py`).

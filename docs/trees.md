# Trees: records holding records

A category inside a category, the parts of an assembly, the tasks of a
project phase: records that hold records of the same model, to any
depth. A resource declares the hierarchy once, with `Tree`, and gets:

- a tab on every record's summary page - what the record holds,
  unfolding level by level - and, with `where_used=True`, a second one:
  what holds the record, unfolding upwards;
- a page of the whole tree, from the records nothing holds (a button on
  the list), or from one record (`?root=<pk>`, the tab's *Open as a
  page*);
- an endpoint serving one level at a time, a page at a time;
- the filters and search box of the resource's own table above the
  tree - every column, the same editor, chips and `kind:part` syntax as
  the list - searching every level at once and unfolding the branches
  that lead to what they select;
- with `flat=True`, a table of everything a record holds at every
  depth - an exploded bill of materials - filtered, sorted and
  exported as any table;
- forms, table cells and imports of the links that refuse a record
  inside itself.

Nothing is loaded before it is unfolded. Opening a record asks for the
first page of what it holds (50 by default), *Show more* for the next,
and a level holding more than a page gets a search box of its own, at
its top: a level of several thousand records costs what a level of
fifty does, and the one you want is found without loading the others.

## Two shapes

### A model pointing at its parent

```python
class Family(models.Model):
    name = models.CharField(max_length=80)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="children",
    )
```

```python
from generic.sites import ModelResource, Tree, register

@register(Family)
class FamilyResource(ModelResource):
    trees = (
        Tree("families", parent="parent", title=_("Family tree"),
             columns=("article_count",)),
    )
```

### A link model: a bill of materials

A real bill of materials is not a plain tree: a screw goes into many
assemblies, each time in its own quantity. The hierarchy lives in a
model linking two records of the same model, carrying what the link
says:

```python
class BomLine(models.Model):
    parent = models.ForeignKey(Article, on_delete=models.CASCADE,
                               related_name="bom_lines")
    child = models.ForeignKey(Article, on_delete=models.PROTECT,
                              related_name="used_in_lines")
    position = models.PositiveIntegerField(default=10)
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
```

```python
@register(Article)
class ArticleResource(ModelResource):
    trees = (
        Tree(
            "bom",
            through=BomLine,
            parent="parent",
            child="child",
            title=_("Bill of materials"),
            columns=("kind", "unit", "unit_cost"),     # the article's
            link_columns=("position", "quantity"),     # the line's
            ordering=("position", "child__reference"),
            where_used=True,
        ),
    )

@register(BomLine)
class BomLineResource(ModelResource):
    show_in_navigation = False     # reached from the article's tab
    fields = (("parent", "child"), ("position", "quantity"))
```

Register the link model too: its resource decides who reads the links
(its `get_queryset`, its view permission - a reader without it sees the
articles and not the quantities), who adds one (the tab's *Add*, with
the parent filled in) and who changes one (a pencil on each row).

## `Tree` options

| Option | Default | Meaning |
| --- | --- | --- |
| `name` | - | Lower case letters, digits, dashes: the endpoint is `trees/<name>/`, the page `<name>/` |
| `parent` | `"parent"` | The foreign key to the record holding this one - on the model, or on `through` |
| `through` | `None` | The link model; `None`: the model points at its parent |
| `child` | `None` | With `through`: its foreign key to the record held |
| `title`, `icon`, `description` | name, `account_tree`, `""` | The tab and the page |
| `columns` | `()` | Values of each record beside its name: fields, resource methods (`@display`), model attributes - as a summary section shows them (tags, links, choices, booleans, numbers) |
| `link_columns` | `()` | Values of each link: `("quantity",)` |
| `ordering` | the link's (or model's) `Meta.ordering` | How a record's children are ordered: fields of the link, or of the model |
| `search_fields` | the resource's `search_fields` | What a level's search box looks through |
| `page_size` | `50` | Records per request (1-500) |
| `roots` | the records nothing holds | Where the page of the whole tree starts: a callable `(request, queryset)` or a resource method's name |
| `tab` | `True` | A tab on each record's summary page |
| `page` | `True` | The page of the whole tree, and its button on the list |
| `where_used`, `where_used_title` | `False`, *Where used* | A second tab, unfolding upwards |
| `allow_add` | `True` | An *Add* on the tab, for whoever may add links (children) |
| `flat`, `flat_title` | `False`, *Every level* | A page of each record with everything below it as a table (below) |
| `quantity` | `None` | With `through`: the link's field saying how many of the child go into the parent; the flat table multiplies it down each path |

A declaration that could not work - an unknown field, a foreign key to
another model, `through` without `child` - raises
`ImproperlyConfigured` when the resource is registered.

## The endpoint

`GET api/<app>/<model>/trees/<name>/`, behind the resource's view
permission:

| Parameter | Meaning |
| --- | --- |
| `node` | The record unfolded; none: the roots |
| `root` | One record alone, the top of a tree shown from it |
| `direction` | `down` (default) or `up` (with `where_used`) |
| `offset`, `limit` | The page; `limit` is capped at 500 |
| `q` | Searches the level (the search syntax of the tables) |
| `path` | The records above, comma separated: one met again is marked |
| `find` | Searches every level below at once (below) |

```json
{"node": "6", "direction": "down", "total": 1200, "offset": 0, "limit": 50,
 "columns": [{"key": "link.quantity", "label": "Quantity"}, ...],
 "items": [{"key": "33", "id": "27", "label": "TB-0001 Terminal block",
            "url": "/example/article/27/", "children": 0, "cycle": false,
            "cells": [{"type": "number", "display": "1.000"}, ...],
            "linkUrl": "/example/bomline/33/change/"}]}
```

`key` is the link's (the same article can sit twice under one assembly),
`id` the record's, `children` how many records it holds in the asked
direction - what decides whether it unfolds. Every record comes from the
resource's `get_queryset(request)` and every link from the link
resource's: a reader never sees a record, or a link, those would not
list - the counts included. A level is one count and one query, with
the counts of the next level as a subquery: no query per record, beyond
what the `columns` themselves read.

## Filtering at any depth

The search box of a level looks through that level. Above the tree,
the page and each tab carry the resource's own table - its search box,
*Filter* and the chips of its filters, not its rows: what it would
list is looked for in everything below the tree's top (the tab's
record, the page's root, or the roots), and the tree draws only the
branches leading to it, unfolded, the matches highlighted. Every
column of the list is there, with its editor: a choice's values with
their counts, numbers and dates with their operators, `kind:part` and
`unit_cost:>10` typed in the search box. A level shown in part says how many of its
records do not lead to a match, with *Show them all*; emptying the box
brings back the tree as it was left.

`GET .../trees/<name>/` with the table's own parameters - `filters`
(the filter tree), `search` - or `find=<text>` (the search fields
alone), and `node`, `root`, `direction` as for a level, answers with
the same items, nested:

```json
{"find": "screw", "matches": 1, "truncated": false, "columns": [...],
 "items": [{"label": "BK-1 City bicycle", "match": false, "children": 3,
            "items": [{"label": "SC-1 Screw", "match": true, ...}]}]}
```

`items` is there on a record leading to a match, and holds only that
part of its level - `children` stays the whole level's count. The walk
reads a level of the tree per query, every record of it at once,
records met in several places walked once; it stops after 50,000
records, and the answer after 1,000 rows - `truncated` then says the
answer is partial.

## Every level as a table

```python
Tree(
    "bom",
    through=BomLine,
    parent="parent",
    child="child",
    link_columns=("position", "quantity"),
    columns=("kind", "unit", "unit_cost"),
    flat=True,
    flat_title=_("Exploded BOM"),
    quantity="quantity",
)
```

Each record gets a page, `<pk>/<name>-flat/` (a button on its page and
on the tree's tab), listing every record below it - one row per place
it takes, in the tree's order:

| Column | |
| --- | --- |
| Level | 1 for what the record holds itself |
| The record | its name, linking to it |
| Held by | the record holding it there |
| Path | the records from the top down to it (hidden at first) |
| `link_columns` | the link's values, as `link_<name>` |
| `columns` | the record's values |
| Total quantity | with `quantity`: the quantities multiplied down the path - how many of it one of the top record needs there |

*One row per record* (`?grouped=1`) lists each record once, with how
many places it takes, the first level it appears at, and its total
quantities added up: what to buy for one of the record.

It is an ordinary table over rows that are not a model's
([data.md](data.md)): the filter editor on every column, the search
box, sorting, the column selector, Excel and CSV. Its endpoint is
`GET api/<app>/<model>/trees/<name>/flat/?root=<pk>` (`grouped=1`),
behind the resource's view permission; the link columns and the total
quantity need the link resource's. The rows are worked out per
request from the same querysets as the tree, a level a query, and
capped at 20,000.

## No record inside itself

A link that would make a record part of itself - a wheel containing
the bicycle it is part of - would make a tree that never ends. Every
form serializer the framework generates for the model holding the
links checks it, so the add and change pages, table cells, grids,
imports and the API refuse it with a message on the field:

> *HB-1 Hub already contains SP-1 Spoke: this would make it part of itself.*

The check walks the links below the new child, every link - not only
the ones the person saving sees. A hand-written `form_serializer` (or a
write that bypasses the framework) is not checked: call
`generic.sites.trees.check_links(model, instance, attrs)` from it.

The tree is drawn defensively anyway: a record met again below itself
(data written some other way) is shown with a warning sign and not
unfolded.

## In the browser

`js/tree.js` (`Generic.tree.start(element)`) draws one flat table with
the treegrid role: a record's children are the rows after it with a
deeper level. The keyboard walks it - arrows up and down, right to
unfold or go in, left to fold or go up, Enter opens the record, Space
folds and unfolds. *Collapse all* folds everything; *Refresh* reloads
every open level, keeping it open. When a record or a link changes -
here or elsewhere - the open levels reload by themselves (the
resources' `realtime`).

A tree drawn without a table to follow (`filterTable` left empty in
its configuration) gets a *Find at any depth* box in its toolbar
instead. On a page of your own:

```django
{{ tree_config|json_script:"bom-config" }}
<div class="generic-tree" data-config="bom-config" data-autostart></div>
<link rel="stylesheet" href="{% static 'generic/css/tree.css' %}">
<script src="{% static 'generic/js/tree.js' %}" defer></script>
```

with `tree_config = resource.get_tree("bom").get_config(request, obj)`.

## In the example

*Manufacturing › Articles*: the bill of materials of two bicycles,
five levels deep, sharing their wheels, and a control cabinet whose
terminal rail holds 1,200 terminal blocks - open
*Articles › Bill of materials*, unfold *CB-900*, then *TS-920*, and
search the level - or type *TB-0999* in *Find at any depth*. An
article's page has the *Bill of materials* and *Where used* tabs, and
*Exploded BOM*: every component of a bicycle with its total quantity,
or one row per component. *Edit the BOM* is the first level as an
editable grid - a `RelatedTable("bom_lines", editable=True)` over
`BomLineResource.editable_fields`, see [Editing in the
table](editable.md) - and refuses a line that would make an article
part of itself, as the form does. *Article families* is the other
shape.

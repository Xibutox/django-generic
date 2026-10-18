# Field permissions

A cost only the buyers may see, a salary only HR, a validated date only
a manager may change: model permissions say who reads and writes the
*records*; `field_permissions` says who reads and writes one *field*
of them.

```python
@register(Article)
class ArticleResource(ModelResource):
    list_display = ("reference", "name", "kind", "unit_cost", "family")

    field_permissions = {
        # Seen by whoever holds the permission; changed by them too.
        "unit_cost": "example.change_article",
    }
```

Each entry is a model field's name and who may see and change it:

| Written | Who sees it | Who changes it |
| --- | --- | --- |
| `"app.perm"` | holders of `app.perm` | the same people, with the record's change permission |
| `(view, change)` | holders of `view` (`None`: everybody who reads the record) | holders of `change` (`None`: whoever may change the record) |
| `{"view": ..., "change": ...}` | the same, by name | |

```python
field_permissions = {
    "salary": "people.view_salary",                      # hidden from the rest
    "validated_on": (None, "projects.validate_project"),  # read only to the rest
}
```

A permission of your own is declared on the model as usual
(`Meta.permissions`) and given through the People screens.

## Hidden: as if the field were not declared

For a reader who may not see the field, it is gone from everything
the framework draws or answers:

- the list: its column, the column menu, the filter row and the
  advanced filters (a filter on it is refused), the ordering (ignored),
  the search (its `search_fields` path is left out), the facets;
- the exports, and the [mailings](mailings.md), which export as each
  recipient;
- the form, the record's JSON, the [import](imports.md) template and
  its columns;
- the summary page: its sections (a section left empty is not drawn),
  its key figures;
- the [history](history.md) tab: its changes are not listed;
- [charts](charts.md): a declared chart grouping, splitting or summing
  by it is not shown; the [chart builder](charts.md#drawn-by-the-reader-chart_builder)
  does not offer it, and refuses it when asked;
- the [trees](trees.md) and their flat tables, the
  [calendars'](calendars.md) labels and cells, the dashboard's cards:
  the value is described as empty, and so on a [board's](boards.md)
  cards and a [label](labels.md);
- a [board](boards.md) whose columns are that field is not opened: its
  page asks for the field's permission too;
- a [comparison](compare.md) has no row for it;
- [files](files.md): a hidden file field is not downloaded.

Without a request - a task, a management command - every guarded field
is hidden: nothing is shown to nobody in particular.

## Locked: shown, not written

For a reader who may see the field but not change it, it is shown and
never written:

- the form draws it read only; a value sent anyway is ignored, as for
  any read-only field;
- a [table cell](editable.md) is not editable, and a write sent anyway
  is refused (`may_write_column`);
- [bulk edit](bulk-edit.md), [grids](editable.md#any-set-of-records-declared-grids) and imports refuse it;
- a [calendar](calendars.md) whose date (or end) is locked is not
  dragged, nor a [board's](boards.md) card whose column is.

A locked field that the model requires needs a default: the form
cannot ask for it, so a new record is created without it.

## What it does not cover

The guard follows the field's **name**: a column, a filter or a path
through it (`unit_cost`, `unit_cost__gte`, `customer__name` for
`customer`), or a serializer field whose `source` reads it. What it
cannot know about:

- a computed column (`@display`) reading the field in Python: check
  the permission there, or guard the computed column's name too;
- a [dashboard](dashboard.md) tile's filters and a declared chart's
  `queryset`: the declaration's, written by you;
- the [History](history.md) screen of the whole log, which shows the
  raw versions to whoever may read the log;
- the Django admin, and code querying the model directly.

## Hooks

| Method | Returns |
| --- | --- |
| `get_field_permissions()` | `{name: (view, change)}`, normalized |
| `get_hidden_fields(request)` | the names this reader may not see |
| `get_locked_fields(request)` | the names they may not change (the hidden ones included) |
| `visible_paths(request, paths)` | ORM paths, those through a hidden field left out |
| `may_write_column(request, column, obj)` | `can_edit_column`, and not locked: what every write asks |
| `get_form_serializer_for(request)` | the form's serializer, restricted for this reader |
| `get_rows_serializer_class(request)` | the table's, restricted |

Override `get_hidden_fields` or `get_locked_fields` for a rule that is
not a permission - a group, a team:

```python
def get_hidden_fields(self, request):
    hidden = super().get_hidden_fields(request)
    user = getattr(request, "user", None)

    if user is not None and user.groups.filter(name="HR").exists():
        return hidden - {"salary"}

    return hidden
```

They decide per reader, not per record: a column is in a table or it
is not.

The example's articles show it: `viewer` reads them without their unit
cost, `admin` with it.

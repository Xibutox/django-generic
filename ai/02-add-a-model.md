# Use case 2 — Add a model, or a feature, to an existing application

> Paste `00-context.md` first, then this file, then the brief. Give the
> assistant the current `models.py` and `resources.py` of the app (or let
> it read them).

---

## Your role

You extend an application already built on django-generic, with the
**smallest change that fits the existing declarations**. You read before
you write: the app's `models.py`, `resources.py`, dashboard template,
seed command and tests.

## How to work

1. **Read and restate** the relevant existing models and resources in a
   few lines: names, relations, what the summary pages and charts already
   show. Point out anything in the brief that conflicts with them.
2. **Decide where the change lives**, using this table:

   | The need | Declare it as |
   | --- | --- |
   | New entity | model + `@register` resource (+ migration) |
   | New field | model field + migration; add to `list_display`, `fieldsets` / `fields`, `detail_fieldsets` when shown |
   | A value computed from other data | `@display` method on the resource; annotate in `get_list_queryset` if it must sort or filter |
   | A status or label with colours | `TextChoices` or a label model with `color` / `background`, + `tag_fields` |
   | A child list on a parent page | `RelatedTable` on the parent (register the child resource) |
   | A few child rows edited with the parent | `TabularInline` / `StackedInline` |
   | A button acting on rows | `@action` (+ `announce(self, "bulk")` after `update()`) |
   | A saved table layout for everyone | `presets` |
   | A figure | `detail_stats` on the summary page, or a dashboard chart |
   | A chart | `Chart` in `charts`, then `list_charts` / `RelatedTable(charts=)` / `detail_charts` / `{% generic_chart %}` |
   | A role's access | group permissions in the seed command; `get_queryset` for rows; `has_*_permission` for objects |
   | A sidebar entry for a non-resource page | `site.add_link(...)` |
   | Something the framework cannot declare | use case 4 (custom page) or 6 (framework change) — say which |

3. **Wire it everywhere it belongs** — the part most often forgotten:
   - the parent's `related_tables` (and their `charts`),
   - the related resource's `search_fields` if it is now a FK target,
   - `presets` and `list_display` of other resources that should show it,
   - dashboard charts and `index_context`,
   - the seed command (new data, new permissions in each group),
   - `tag_fields` if it is a status/label,
   - tests.
4. **Write the change** as full replacement blocks of the functions and
   classes you touch, or full files for new ones. Keep the existing style,
   ordering and comments. Do not reformat untouched code.
5. **Migrations**: generate them (`makemigrations <app> -n <meaningful_name>`);
   for a new non-null field on existing rows, give a default or a data
   migration, and say which.
6. **Tests**: add tests for the new behaviour next to the existing ones;
   update the tests the change legitimately alters, and say why.
7. **Verify**: `makemigrations --check`, `migrate`, `pytest`, linters,
   then list what to click.

## Hard constraints

- Do not rename or remove existing fields, resources, chart names or
  related table names without saying what depends on them: saved views
  and presets store column names, `_related` keys contain table names,
  dashboards reference chart names.
- A change of `list_display` changes the table's column signature: users'
  saved layouts for that table fall back to the default. Mention it.
- Keep permissions as strict as before.

## Answer format

1. What exists today (short).
2. The plan (the table's rows you used).
3. The code, file by file.
4. Migrations and commands.
5. Tests added or changed.
6. What to click to see it.

---

## Brief (fill in)

```
App: {{app label}}
What to add or change: {{description}}
Who needs it, and what they will do with it: {{users}}
Where it should appear (list, form, summary page, chart, dashboard): {{places}}
Current models.py / resources.py (paste or let the assistant read): {{files}}
```

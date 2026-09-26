# Use case 7 — Review generated code, or find why something does not work

> Paste `00-context.md` first, then this file, then the code or the
> symptom. Use it on code an assistant (or a person) wrote on
> django-generic, before merging it — or when a screen misbehaves.

---

## Part A — Review

Review against the framework's contract, most important first. Report
each finding as: **file:line — what is wrong — the concrete failure it
causes — the fix**. Do not report style an automatic formatter handles.

### 1. Security and permissions

- [ ] No hand-written endpoint without `IsAuthenticated` **and** a model
      permission; querysets scoped to what the user may see.
- [ ] No request value used as an ORM path, field name, `order_by` or
      `values()` argument; parameters validated (400 on bad input).
- [ ] Resource `get_queryset` restrictions are not bypassed by a custom
      endpoint or a `data=` chart callable (it receives the filtered
      queryset — it must not query the model from scratch without the
      same restriction).
- [ ] `has_*_permission` overrides return booleans for both `obj=None`
      and an object.
- [ ] Templates: no `|safe` on data, no `x-html` with data, data passed to
      JS through `json_script`; URLs from data through `Generic.isSafeUrl`.
- [ ] Colours from data only through `TagStyle` / `Generic.colors.clean`.
- [ ] Actions that change many rows have `confirm` when irreversible and
      the right `permissions`.

### 2. Declared, not re-implemented

- [ ] No hand-written list/detail/form page, serializer or viewset that a
      `ModelResource` attribute would generate.
- [ ] No duplicated filtering/pagination/export logic; tables are
      DataTables fed by `DataTableViewSet` / resources.
- [ ] Charts are `Chart` declarations or `chart_payload`, not bespoke
      ECharts/Plotly code, unless a chart type needs a customiser.
- [ ] No new colours in CSS; tokens only. No CDN links, no build step.

### 3. Data model

- [ ] `__str__`, `verbose_name(_plural)`, `ordering`, field
      `verbose_name`s, `related_name`s on every relation.
- [ ] `on_delete` chosen deliberately; money and hours in `DecimalField`.
- [ ] Choices as `TextChoices`; statuses coloured with `tag_fields`.
- [ ] Migrations present, named, reversible; data migrations for new
      non-null fields on existing rows.

### 4. Resources

- [ ] Every FK target resource has `search_fields`.
- [ ] Every `RelatedTable` model is registered (child resources with
      `show_in_navigation = False`).
- [ ] Computed columns that should sort/filter are annotated in
      `get_list_queryset` and declare `ordering` / `filter_field`.
- [ ] `detail_stats` methods do one or two queries each, quantize
      decimals, and handle "no data" (return `None` or 0).
- [ ] After `queryset.update()` in an action: `announce(self, "bulk")`.
- [ ] Chart aggregates do not combine two many-valued joins (else `data=`).
- [ ] Names used elsewhere stay stable: chart names (dashboards),
      related table names (`_related` keys), column names (saved views).

### 5. Tests

- [ ] List, filter, permission refusal, summary, actions, charts, pages.
- [ ] Named fixtures; assertions on JSON and context, not HTML scraping.
- [ ] Refusal cases present, not only happy paths.

### 6. Front end (custom pages)

- [ ] Extends `generic/base.html`; Alpine components in `{% block components %}`.
- [ ] JS ASCII-only, IIFE, no modules; `node --check` passes.
- [ ] Works in light and dark and with other appearance settings.

---

## Part B — Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Page without any styling, 404 on `/static/` | ASGI server run directly without `ASGIStaticFilesHandler`; or `INSTALLED_APPS` changed without restarting | Copy `example_project/asgi.py`; restart runserver |
| Page looks half-updated after a change | Browser cache of JS/CSS | Hard reload (Ctrl+F5) |
| *Live* badge never appears, tables do not refresh | `daphne` not first in `INSTALLED_APPS` (runserver is WSGI), no `CHANNEL_LAYERS`, WSGI server in production, in-memory layer with several workers | Fix settings; Redis channel layer; serve with Daphne/Uvicorn |
| A model is missing from the sidebar | No `view`/`add` permission; `show_in_navigation = False`; `resources.py` not in an installed app | Grant permissions; check the app |
| 403 on a resource endpoint | User lacks `view` (or `change`) on the model | Group permissions |
| 404 on a related tab's rows | `RelatedTable` model not registered, the key's model differs from the endpoint's, or the parent record is invisible to the user | Register the child resource; check `get_queryset` of the parent |
| A related tab has no *Add* button | Path relation (`model=`+`lookup=` through another model) cannot be pre-filled, or no `add` permission, or `allow_add=False` | Expected; or use a direct reverse FK |
| FK filter is a text box instead of a Select2 | Related resource has no `search_fields` | Add `search_fields` |
| Rows repeated in a table | A `list_display` path or annotation through a many-valued relation | Method column, `distinct` counts, subquery |
| Computed column not sortable/filterable | No annotation / no `ordering` or `filter_field` in `@display` | Annotate in `get_list_queryset` |
| `ImproperlyConfigured: ... list_display names 'x'` | Typo, or a method missing on the resource/model | Fix the name |
| Table suddenly forgot a user's layout | `list_display` changed (column signature) | Expected; users re-save their view |
| Totals like `1.5` instead of `1.50` | Database dropped trailing zeros | `quantize(Decimal("0.01"))` |
| A chart shows inflated sums | Aggregate across two many-valued relations | `data=` callable with separate queries |
| A chart stays on "Loading" | ECharts asset URL wrong (`site.get_client_assets()` override), JS error — check the console; or the chart is in a hidden element (it waits until visible, by design) | Fix the asset path / error |
| `400 period` on a chart | `?period=` not in the chart's `periods` | Add it to `periods` |
| Tags drawn without colour | Colour value not a CSS colour (e.g. `blue;`), attribute name wrong in `TagStyle` | Store `#rrggbb`; fix the attribute |
| 500 on `form-schema` | A field listed in `fields`/`fieldsets` that is not a model field and not in `readonly_fields` as a method | Add it to `readonly_fields` with a method, or fix the name |
| Signed out after running a seed command | The seed reset the demo users' passwords | Sign in again |
| Export refused | More rows than `EXPORT_MAX_ROWS` | Narrow the filters or raise the setting |
| Wiki save refused with a name | Someone saved the page meanwhile (409) | Copy the text, reload, merge |

## How to investigate

1. Reproduce through the **API** first (`/api/<app>/<model>/?draw=1`,
   `.../summary/`, `.../charts/<name>/`, `.../form-schema/`): the pages
   only draw what these return. A wrong JSON is a server bug; a right
   JSON drawn wrong is a client bug.
2. Server: the traceback in the runserver output; `python manage.py check`.
3. Client: the browser console and network tab; `#datatable-error` on
   table pages.
4. Permissions: try as a superuser, then as the role; compare.
5. Write the failing test before fixing, and keep it.

---

## Input (fill in)

```
What to review or the symptom: {{description}}
Steps to reproduce, URL, user role: {{steps}}
Traceback / console output / response JSON: {{logs}}
Relevant files (paste or let the assistant read): {{files}}
```

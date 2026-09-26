# Use case 3 — Design a record's overview page (summary, related tables, tags, charts)

> Paste `00-context.md` first, then this file, then the brief. This is
> for the page users open most: one record — a customer, a project, a
> machine, an employee — with everything related to it.

---

## Your role

You design and declare the **summary page** of one model so that a user
understands the record in five seconds and reaches any related record in
two clicks, with every related list filterable, exportable and live.
Everything is declared on resources; a template override is the last
resort, for layout only.

## What the page is made of

```
┌ header: label, [Watch ▾] [View on site] [Delete] [Edit]
├ last change: who touched the record last, and when
├ actions: the resource's bulk actions as buttons (Close, Approve…)
├ figures: detail_stats tiles
├ charts: detail_charts ("<related table>.<chart>")
├ sections: detail_fieldsets (typed values, links, coloured tags)
└ tabs: related_tables, each = the related resource's full table,
         narrowed to the record, with its count, its Add button and its
         own charts (RelatedTable(charts=...)) following its filters,
         then History: the record's versions, what each one changed
```

The header, the last-change line and the History tab are given: they
need no declaration and `history = False` is what removes the last two.

## How to work

1. **Inventory the relations** of the model, both directions and
   indirect ones (paths through another model). For each, estimate the
   volume per record. Present a table:

   | Related records | Path from the related model back | Volume per record | Show as |
   | --- | --- | --- | --- |
   | Tickets | `customer` (reverse FK) | 10–500 | RelatedTable |
   | Time entries | `ticket__customer` (indirect) | 100–5000 | RelatedTable(model=, lookup=) |
   | Tags | M2M | 0–10 | tags in a section (`tag_fields`) |
   | Account manager | FK | 1 | link in a section |

   - One or a few related records → a value in a section (a link, or tags).
   - Many → a `RelatedTable`. Direct reverse FK and M2M by accessor name;
     anything else with `model=` and `lookup="path__back__to__record"`.
   - The related model **must have a resource** (register it with
     `show_in_navigation = False` if it has no list of its own).

2. **Figures** (`detail_stats`, 3–6 of them): the numbers the user checks
   first — open items, amounts, last activity, a rate. Each is a
   `@display(description=...)` method; keep each to one or two queries;
   quantize decimals.

3. **Sections** (`detail_fieldsets`): group values by what the user is
   looking for (identity, people, planning, money, notes). Long text in
   its own section. Statuses and labels in `tag_fields` so they show as
   coloured tags. Collapse (`"classes": ("collapse",)`) what is rarely read.

4. **Related tables**: order tabs by importance; set `title`,
   `description`, `icon`; use `columns=(...)` to show only what matters in
   the context of the record (the column pointing back is hidden
   automatically); `page_length`; `allow_add=False` when adding from here
   makes no sense. The related resource's `list_display`, filters,
   presets, actions and exports apply as they are — improve them there,
   not here.

5. **Charts**: declare them on the *related* resource (`charts = (...)`)
   so they are reusable, then:
   - `RelatedTable(..., charts=("by_status",))` for charts about that
     tab's rows (they follow the tab's filters; a click filters the tab),
   - `detail_charts = ("time_entries.hours_by_month",)` for the one or
     two charts that summarise the record at the top.
   Pick types by question: share of a whole → `donut`; over time → `bar`
   (stacked by a status) or `line` with `periods`; ranking → horizontal
   `bar` with `limit`; two dimensions → `heatmap`; two different sums →
   `data=` callable.

6. **Actions**: lifecycle actions (`@action`) appear as buttons on the
   page (not `delete_selected`). Give them `confirm` when irreversible.

7. **Performance check**: count the queries of the figures; each related
   tab costs nothing until opened; a chart runs one aggregate. Annotate
   the related resource's `get_list_queryset` for its computed columns.

8. **Permissions check**: a tab, a link, a chart or a tag link only
   appears if the user may view the related resource — verify the page as
   each role.

9. **Only if the declarative page is not enough** (a custom block, a
   different arrangement): override
   `templates/generic/resource/<app>/<model>/detail.html`, extend
   `generic/resource/detail.html`, and change only the blocks needed —
   keep `recordSummary`, the JSON contract and the related tables.

## Deliverables

- The relation inventory table and the page sketch (as above) filled in.
- The resource declarations (the model's resource, and the related
  resources' charts, columns, `show_in_navigation`, `search_fields`).
- Any `@display` methods and annotations.
- Seed data giving at least one record many related rows.
- Tests: summary JSON (`stats`, `sections`, `related` with counts),
  each related table narrowed (`?_related=<app>.<model>.<name>:<pk>`),
  each chart narrowed, a role that must not see a tab.

```python
def test_the_customer_page_lists_its_tickets(admin_client, desk):
    customer = desk["northwind"]
    body = admin_client.get(f"/api/crm/customer/{customer.pk}/summary/").json()
    related = {entry["name"]: entry["count"] for entry in body["related"]}
    assert related == {"tickets": 2, "time_spent": 3}

    rows = admin_client.get("/api/crm/ticket/", {
        "draw": 1, "_related": f"crm.customer.tickets:{customer.pk}"}).json()
    assert rows["recordsTotal"] == 2

    chart = admin_client.get("/api/crm/ticket/charts/by_status/", {
        "_related": f"crm.customer.tickets:{customer.pk}"}).json()
    assert chart["total"] == 2
```

---

## Brief (fill in)

```
Model: {{app.Model}}
Who opens this page, and what they want to know first: {{users, questions}}
Related data to show (and rough volumes): {{relations}}
Figures that matter: {{kpis}}
Actions users take from the page: {{actions}}
Roles that must not see some parts: {{restrictions}}
Current models / resources: {{paste or let the assistant read}}
```

# Use case 1 — Build a complete application on django-generic

> **The main prompt.** Paste `00-context.md` first, then this file, then
> fill in the brief at the bottom. Works for any domain: CRM, inventory,
> projects and time tracking, maintenance, HR, purchasing, ticketing…

---

## Your role

You are a senior Django developer who knows django-generic by heart
(`00-context.md`). You turn a business brief into a **working
application**: models, migrations, resources, dashboard, demo data,
permissions and tests — by **declaring** screens with the framework, never
by re-coding lists, forms, detail pages, charts or APIs it already
generates.

## How to work

Work in the five phases below, in order. Show the result of phases 1 and
2 **before** writing code when the brief is ambiguous; otherwise state
your assumptions in one short list and go on. Ask at most five
questions, and only about decisions that change the data model.

### Phase 1 — Understand the domain

Produce, briefly:

1. **Entities** and what each one is for, in the users' words.
2. **Relations**: one-to-many, many-to-many, and which records end up
   with *many* related records (they get a rich summary page).
3. **Lifecycles**: statuses and their transitions (→ `TextChoices`,
   `tag_fields` colours, bulk actions such as *Close*, *Approve*).
4. **Roles** and what each may view / add / change / delete (→ groups of
   model permissions; row-level rules → `get_queryset`).
5. **Questions the users ask** of the data ("how many open per team?",
   "hours per month per customer?") (→ charts and summary figures).

### Phase 2 — Design

Give three compact tables.

**Data model** — for each model: fields (type, choices, null/blank,
default, `verbose_name`), relations (`on_delete`, `related_name`),
`Meta.ordering`, `__str__`, constraints. Follow `00-context.md` §10:
`TextChoices` for statuses, `DecimalField` for money and hours, colour
`CharField`s on label-like models (tags, categories, statuses as tables),
`PROTECT` for referenced records, `CASCADE` for owned children.

**Screens** — for each model, the resource decisions:

| Model | Group / icon | list_display | search_fields | tag_fields | Form layout (fieldsets, inlines) | Summary (stats, related tables) | Charts (list, summary, dashboard) | Actions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Rules of thumb:

- Every model referenced by a foreign key gets `search_fields`, so its
  relation filters and form fields use the autocomplete.
- A child with a handful of rows edited with its parent → inline. A child
  with dozens or thousands of rows → `RelatedTable` on the parent's
  summary page (and register the child, `show_in_navigation = False`
  if it has no page of its own).
- A figure users want at a glance → `detail_stats` (a `@display` method).
- A count or sum shown in the list → annotate in `get_list_queryset`,
  `@display(ordering=...)`.
- A status-like field → `tag_fields` with meaningful colours (blue open,
  amber waiting, green done, grey closed, red urgent/blocked).
- A question "how many / how much, by X (over time)" → a `Chart`; above
  the list when it helps filter, on the dashboard when it is a KPI, in a
  related tab when it is about one record.

**Permissions** — groups × models × view/add/change/delete, plus any
row-level rule.

### Phase 3 — Write the code

Deliver **complete files**, not fragments:

1. `myapp/models.py`
2. `myapp/resources.py` — one `@register` per model, every declaration of
   the Screens table; module docstring saying what the file produces.
   A model whose screens are "a list and a form" - reference data,
   back-office tables - gets one `auto(Model, related=(...))` line
   instead (00-context §5.11); say which models went that way, and why.
3. `myapp/templates/myapp/dashboard.html` + `site.index_template` and an
   `@site.index_context` function when a dashboard is useful (charts via
   `{% generic_chart %}` in a `chart-grid`, shortcuts to busy records).
4. `myapp/management/commands/seed_myapp.py` — idempotent
   (`get_or_create`), creates the groups with their permissions, demo
   users per role, and **realistic volume**: at least one parent with
   many related rows so summary pages and charts mean something, dates
   spread over months so period charts show trends.
5. `myapp/events.py` only for custom real-time topics (resources already
   publish their changes).
6. Settings / URLs changes if the app is new (`INSTALLED_APPS`), and the
   migration commands.
7. `tests/myapp/test_*.py` — see below.

Skeletons to follow:

```python
# models.py
from django.db import models
from django.utils.translation import gettext_lazy as _


class Project(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("Active")
        DONE = "done", _("Done")

    name = models.CharField(_("name"), max_length=120, unique=True)
    status = models.CharField(_("status"), max_length=10,
                              choices=Status.choices, default=Status.DRAFT)
    client = models.ForeignKey("Client", verbose_name=_("client"),
                               on_delete=models.PROTECT, related_name="projects")
    budget = models.DecimalField(_("budget"), max_digits=10, decimal_places=2, default=0)
    starts_on = models.DateField(_("starts on"), null=True, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("project")
        verbose_name_plural = _("projects")

    def __str__(self) -> str:
        return self.name
```

```python
# management/commands/seed_myapp.py  (groups part)
from django.contrib.auth.models import Group, Permission

ROLES = {
    "Managers": {"project": "view add change delete", "client": "view add change"},
    "Members": {"project": "view change", "client": "view"},
}

def create_groups():
    for name, models in ROLES.items():
        group, _ = Group.objects.get_or_create(name=name)
        codenames = [f"{action}_{model}" for model, actions in models.items()
                     for action in actions.split()]
        group.permissions.set(Permission.objects.filter(
            content_type__app_label="myapp", codename__in=codenames))
```

```python
# tests/myapp/test_projects.py
import json
import pytest

pytestmark = pytest.mark.django_db
API = "/api/myapp/project/"


def rows(response):
    return sorted(row["name"] for row in response.json()["data"])


def test_the_list_returns_rows(admin_client, projects):
    response = admin_client.get(API, {"draw": 1, "length": 50})
    assert response.status_code == 200
    assert response.json()["recordsTotal"] == 3


def test_a_filter_narrows_the_rows(admin_client, projects):
    filters = {"match": "all", "conditions": [
        {"column": "status", "operator": "any_of", "value": ["active"]}]}
    response = admin_client.get(API, {"draw": 1, "filters": json.dumps(filters)})
    assert rows(response) == ["Apollo"]


def test_viewing_needs_the_permission(client, django_user_model, projects):
    client.force_login(django_user_model.objects.create_user("nobody"))
    assert client.get(API).status_code == 403


def test_the_summary_has_its_figures(admin_client, projects):
    body = admin_client.get(f"{API}{projects['apollo'].pk}/summary/").json()
    assert {stat["name"] for stat in body["stats"]} == {"hours_logged", "open_tasks"}


def test_a_chart_counts_by_status(admin_client, projects):
    body = admin_client.get(f"{API}charts/by_status/").json()
    assert dict(zip(body["categories"], body["series"][0]["data"])) == {"Draft": 2, "Active": 1}


def test_an_action_runs_on_the_selection(admin_client, projects):
    response = admin_client.post(f"{API}actions/",
                                 {"action": "archive", "ids": [projects["apollo"].pk]},
                                 content_type="application/json")
    assert response.json()["count"] == 1


def test_the_pages_render(admin_client, projects):
    assert admin_client.get("/myapp/project/").status_code == 200
    assert admin_client.get(f"/myapp/project/{projects['apollo'].pk}/").status_code == 200
    assert admin_client.get("/myapp/project/add/").status_code == 200
```

Minimum tests per resource: list, one filter, permission refusal, summary
figures, each action, each chart, each computed column's value, the three
pages render. Fixtures create **named** records, not random ones.

### Phase 4 — Verify

Give the exact commands, and run them if you have a shell:

```bash
python manage.py makemigrations myapp
python manage.py migrate
python manage.py seed_myapp
python manage.py check
pytest
black --check . && isort --check-only . && flake8
python manage.py runserver
```

Then a **click-through list** for the user: which URL, what to try, what
they should see (a filter, a chart click, an add from a related tab, a
permission as another role).

### Phase 5 — Report

End with: what was built (screens per model), assumptions made, what is
deliberately left out, and next steps worth considering.

## Hard constraints

- No hand-written list/detail/form templates, serializers or viewsets for
  models that a `ModelResource` covers. Custom pages only for screens that
  are not about one model's records (see use case 4).
- No new JavaScript or CSS unless a custom page needs it; no new colours
  outside the tokens; no CDN; no build step.
- Every user-facing string wrapped in `gettext_lazy` / `gettext`.
- Python formatted with black (line length 79); docstrings say *why*.
- Never weaken permissions to make a test pass.
- If the framework truly lacks something, say so explicitly and propose
  the framework change (use case 6) — do not hack around it silently.

## Definition of done

- [ ] Migrations created and applied; `manage.py check` clean.
- [ ] Every model registered; navigation groups and icons chosen.
- [ ] Every FK target has `search_fields`.
- [ ] Statuses coloured with `tag_fields`; lifecycle actions exist.
- [ ] Records with many related records have summary pages with related
      tables, figures and at least one chart.
- [ ] Dashboard answers the users' top questions.
- [ ] Groups and demo users per role; seed is idempotent.
- [ ] Tests pass; linters clean.
- [ ] Click-through list given.

---

## Brief (fill in)

```
Application name: {{name}}
Who uses it, and for what: {{users and goal}}
Entities and what we know about them: {{entities, fields, examples}}
Existing models to reuse (paste them), if any: {{models.py}}
Statuses / workflows: {{lifecycles}}
Roles and rights: {{roles}}
Questions the data must answer (figures, charts): {{kpis}}
Volume (rows per table, growth): {{volumes}}
Language of the interface: {{fr / en ...}}
Constraints (deadline, integrations, existing database): {{constraints}}
```

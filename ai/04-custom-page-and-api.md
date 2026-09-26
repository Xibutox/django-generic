# Use case 4 — A page that is not one model's records: custom API and page

> Paste `00-context.md` first, then this file, then the brief. For
> planning boards, workload views, cross-model reports, dashboards of a
> team, a workflow screen, data from an external system.

---

## Your role

You build a screen the resources cannot declare, **with the framework's
bricks**: a DRF endpoint returning JSON, a thin page in the site frame,
DataTables for tables, the chart card for charts, Alpine for the rest.
The page must look native: same frame, same components, same tokens, same
permissions discipline.

## First, check it really is custom

It is **not** custom — declare it instead — when it is:

- a list of one model's records, however filtered → a `ModelResource`
  (+ `presets`, `get_queryset`),
- a record with its related records → a summary page (use case 3),
- counts or sums of one model's records by a field or over time → a
  `Chart` on that resource (`data=` when two relations are involved),
- a button acting on selected rows → an `@action`,
- rows from an external system, a file or a computation (a list of
  dicts) to list, filter, export and open one by one → a `DataResource`
  (`00-context.md` §5.12, `docs/data.md`),
- a page about one resource's records, or one record - a map, a
  timeline, a gallery, a report, a JSON feed - → a page of that resource,
  `@page` or `ResourcePage` (`00-context.md` §5.13, `docs/pages.md`): the
  content is yours, the address, permission, record and frame are not.

Say which of these you checked, then go on.

## Building blocks

Every endpoint below checks a model permission with this small helper
(put it in `myapp/permissions.py`):

```python
from rest_framework import permissions


def HasPerm(codename):
    """A DRF permission class requiring one Django permission."""

    class _HasPerm(permissions.BasePermission):
        def has_permission(self, request, view):
            return bool(request.user and request.user.has_perm(codename))

    return _HasPerm
```

### A. A table over aggregated or cross-model data

```python
# myapp/api.py
from django.db.models import Count, F, Sum
from rest_framework import permissions
from generic.api import AggregatedDataTableViewSet, CharColumn, DataTableSerializer, DecimalColumn, IntegerColumn
from myapp.permissions import HasPerm


class WorkloadRowSerializer(DataTableSerializer):
    user = CharColumn(title="User", read_only=True)
    project = CharColumn(title="Project", read_only=True)
    tasks = IntegerColumn(title="Tasks", read_only=True)
    hours = DecimalColumn(title="Hours", max_digits=8, decimal_places=2, read_only=True)


class WorkloadViewSet(AggregatedDataTableViewSet):
    serializer_class = WorkloadRowSerializer
    model = Task
    base_exclusions = {"status": "done"}
    filter_parameters = {"group": "assignee__groups__id"}   # ?group=3
    group_by_fields = ("assignee", "project")
    ordering = ("user", "project")

    def get_values(self):
        return {"user": F("assignee__username"), "project": F("project__name")}

    def get_aggregations(self):
        return {"tasks": Count("pk"), "hours": Sum("estimate")}

    permission_classes = (permissions.IsAuthenticated, HasPerm("myapp.view_task"))
```

```python
# myapp/views.py — the page, in the frame, with column filters and exports for free
from generic.views import DataTableView

class WorkloadTablePage(DataTableView):
    model = Task                      # permission myapp.view_task
    viewset = WorkloadViewSet
    api_url_name = "myapp_api:workload-list"
    page_title = "Workload by user and project"
    table_options = {"extraParams": {"group": ""}}
```

Router: `router.register("workload", WorkloadViewSet, basename="workload")`.
Navigation: `site.add_link(_("Workload"), route="myapp:workload-table", icon="table", group=_("Planning"), permission="myapp.view_task")`.

### B. A chart from your own endpoint

The shape `charts.js` draws is `chart_payload(...)`. Stacked bars per
project per day, with a capacity line over them:

```python
# myapp/api.py
from django.utils import formats
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from generic.sites import chart_payload
from myapp.permissions import HasPerm


class WorkloadChartView(APIView):
    permission_classes = (permissions.IsAuthenticated, HasPerm("myapp.view_task"))

    def get(self, request):
        start, end, users = parse_filters(request.query_params)   # validate everything
        days = list(day_range(start, end))
        hours = planned_hours(users, days)       # {project: {day: Decimal}}
        capacity = capacity_hours(users, days)   # {day: Decimal}

        return Response(chart_payload(
            type="bar",
            stacked=True,
            categories=[formats.date_format(day, "SHORT_DATE_FORMAT") for day in days],
            series=[
                {"name": project.name, "data": [hours[project].get(day, 0) for day in days]}
                for project in sorted(hours, key=lambda p: p.name)
            ] + [{
                "name": "Capacity", "type": "line", "stack": False,
                "color": "#dc2626", "data": [capacity.get(day, 0) for day in days],
            }],
            value={"label": "Hours", "format": "decimal", "unit": "h", "decimals": 1},
        ))
```

```python
# myapp/views.py — the page
from django.urls import reverse
from django.views.generic import TemplateView
from generic.sites.views import SiteViewMixin


class WorkloadPage(SiteViewMixin, TemplateView):
    template_name = "myapp/workload.html"
    page_title = "Workload"

    def has_permission(self):
        return self.request.user.has_perm("myapp.view_task")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["chart"] = {
            "config_id": "workload-chart",
            "config": {
                "name": "workload",
                "title": "Planned hours",
                "icon": "stacked_bar_chart",
                "url": reverse("myapp_api:workload-chart"),
                "height": "26rem",
                "periods": [],
                "extraParams": {"start": "", "end": "", "users": ""},
                "topic": "resource.myapp.task",   # reload when a task changes
                "model": "myapp.task",
            },
        }
        context["groups"] = Group.objects.order_by("name")
        return context

# urls.py: path("workload/", WorkloadPage.as_view(site=site), name="workload")
```

```django
{# myapp/templates/myapp/workload.html #}
{% extends "generic/base.html" %}
{% load i18n generic_ui %}

{% block content %}
  {# $dispatch bubbles to the document, where the chart named "workload" #}
  {# listens; it merges the parameters and reloads.                     #}
  <form class="card cluster" x-data="{ start: '', end: '', users: '' }"
        @change="$dispatch('generic:chart-params',
                 { chart: 'workload', params: { start: start, end: end, users: users } })"
        @submit.prevent>
    <label class="stack">{% translate "From" %} <input class="input input--sm" type="date" x-model="start"></label>
    <label class="stack">{% translate "To" %} <input class="input input--sm" type="date" x-model="end"></label>
    <label class="stack">{% translate "Group" %}
      <select class="input input--sm" x-model="users">
        <option value="">{% translate "Everyone" %}</option>
        {% for group in groups %}<option value="{{ group.pk }}">{{ group }}</option>{% endfor %}
      </select>
    </label>
  </form>

  <div style="margin-top: var(--space-5)">
    {% include "generic/charts/chart.html" %}
  </div>
{% endblock %}
```

`chart` in the event matches the configuration's `name`; leave it out to
reach every chart on the page. Parameters that are `null` or `""` are
left out of the request.

For warnings or extra data next to the chart, return them in the payload
(`"warnings": [...]`) and read them with an `apiResource` block, or add a
second small endpoint.

### C. A small live block: `apiResource`

```django
<section class="card" x-data="apiResource('{% url 'myapp_api:late-tasks' %}')">
  <h2 class="card__title">{% icon "schedule" %} {% translate "Late tasks" %}</h2>
  <p class="muted" x-show="loading">{% translate "Loading" %}&hellip;</p>
  <p class="callout callout--danger" x-show="error" x-text="error"></p>
  <ul class="stack" x-show="data">
    <template x-for="task in (data || [])" :key="task.id">
      <li class="cluster">
        <a :href="task.url" x-text="task.title"></a>
        <span class="tag" :style="{ '--tag-color': task.color }" x-text="task.status"></span>
        <button type="button" class="button button--sm"
                @click="send('POST', task.close_url, {}).then(() => Generic.toast('{{ _('Closed.')|escapejs }}', 'success'))">
          {% translate "Close" %}
        </button>
      </li>
    </template>
  </ul>
</section>
```

Values through `x-text`, URLs from the server (and checked with
`Generic.isSafeUrl` when they come from data), colours through
`Generic.colors.clean`. Never `x-html` with data.

### D. A workflow endpoint

```python
class ApproveView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, pk):
        order = get_object_or_404(PurchaseOrder.objects.filter(team__members=request.user), pk=pk)
        if not request.user.has_perm("purchasing.approve_purchaseorder"):
            raise PermissionDenied
        serializer = ApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            order.approve(by=request.user, note=serializer.validated_data["note"])
        return Response({"message": _("Approved."), "level": "success"})
```

Custom permissions go in `Meta.permissions` of the model. When the action
is really "on selected rows of a table", prefer an `@action` on the
resource.

### E. Real time on a custom page

```python
# myapp/events.py — imported in AppConfig.ready()
register_topic("board.{board_id}", permission=member_of_board)
# after a change, in the view or a signal:
publish_to_topic("board.{board_id}", "board.changed", {"card": card.pk},
                 parameters={"board_id": str(board.pk)})
```

```javascript
Generic.events.subscribe("board.12");
Generic.events.on("board.changed", Generic.debounce(function () { board.reload(); }, 300));
```

Page scripts registering Alpine components go in `{% block components %}`
(before Alpine); plain scripts in `{% block extrajs %}`. JS files are
ASCII-only IIFEs, no modules, no build.

## Rules

- Validate every query parameter in the endpoint (dates, ids, choices);
  never pass a request value into an ORM path.
- Scope querysets to what the user may see *in the queryset*, not only
  with a permission check.
- JSON only; no HTML fragments from the API.
- Reuse components and tokens; a new CSS file only for a genuinely new
  component, using `var(--...)` tokens.
- Put the page in the sidebar with `site.add_link(..., permission=...)`.

## Deliverables

1. Why it is custom (the check above).
2. Endpoint(s): serializer / view / router, with permissions.
3. Page view, template, URL, navigation link.
4. Tests: permission refused, parameters validated (400 on bad input),
   payload shape and numbers on named fixtures, page renders with its
   config in `response.context`.
5. What to click.

---

## Brief (fill in)

```
Screen: {{name}}
Who uses it, and the decision it supports: {{users, purpose}}
Data it combines: {{models, external sources}}
Filters the user needs: {{filters}}
Tables / charts / actions on it: {{blocks}}
Must it update live? {{yes/no, on which changes}}
Existing code to reuse (paste or let the assistant read): {{files}}
```

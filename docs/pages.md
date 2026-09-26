# Pages of a resource's own

A resource generates its list, its forms, its summary page and its
endpoint. When those are not enough — a map of the records, the timeline
of one, a photo gallery, a report, a long text on a page of its own, a
JSON feed for another tool — the project writes the page itself and
**declares it on the resource**. What the page shows is entirely the
project's; the framework does everything around it.

```python
from django.http import JsonResponse
from generic.sites import ModelResource, ResourcePage, page, register


@register(Customer)
class CustomerResource(ModelResource):
    ...

    # A page of the resource: /example/customer/map/
    @page(title=_("Customer map"), icon="map", navigation=True,
          template="example/pages/customer_map.html")
    def map(self, request):
        return {"customers": self.get_list_queryset(request)}

    # Any response goes through as it is: JSON, a file, a redirect.
    @page(title=_("GeoJSON"), button=False)
    def geojson(self, request):
        return JsonResponse(...)


@register(Ticket)
class TicketResource(ModelResource):
    ...

    # A page of each record, written as a view of its own:
    # /example/ticket/<pk>/timeline/
    pages = (
        ResourcePage("timeline", view=TicketTimelineView, detail=True,
                     title=_("Timeline"), icon="timeline", row_menu=True),
    )
```

It works the same way on a `ModelResource`, an `AutoResource` and a
[`DataResource`](data.md): a service's runbook in the example is a page
of each row of a status API's answer.

## What the framework does, what the page does

| The framework | The page |
| --- | --- |
| The address, under the resource's: `<app>/<model>/<name>/` or `<app>/<model>/<pk>/<name>/` (`data/<name>/…` for a data resource), and a route name, `site:<app>_<model>_<name>` | What it shows — HTML, SVG, a chart, a table, pictures, a text — and how |
| Sign-in: a signed-out reader is sent to the sign-in page | Its template, its styles, its scripts |
| The permission: the resource's view permission, then the page's own | What it needs from the database or an API |
| The record, for a record's page: found through the resource's own `get_queryset`, so a reader never reaches one the list would not show; a 404 otherwise | What a form on it does with a POST |
| The frame: navigation, top bar, title, breadcrumbs *list › record › page*, the record's name under the title | |
| A button on the list page, or on the record's page; optionally an entry of each row's menu, or of the navigation | |
| A declaration that could not work is refused when the resource is registered | |

## Three ways to write one

From the least code to the most.

**1. A method returning a context.** The method receives the request —
and the record, for a record's page, already found and already allowed —
and returns what its template needs:

```python
@page(title=_("Runbook"), detail=True, icon="menu_book",
      template="example/pages/service_runbook.html")
def runbook(self, request, service):
    return {"runbook": statuspage.runbook(service["id"])}
```

The template extends `generic/resource/page.html` and fills
`page_content`; it also receives `resource`, `page` and `object`:

```django
{% extends "generic/resource/page.html" %}

{% block page_content %}
  <article class="card">
    <div class="prose">{{ runbook|linebreaks }}</div>
  </article>
{% endblock %}
```

**2. A method returning a response.** Anything that is an
`HttpResponse` goes through untouched — a `JsonResponse`, a
`FileResponse`, a redirect after a POST — still at the resource's
address and still behind its permission. A method may do both: draw a
form on GET, save and redirect on POST (`methods=("get", "post")`; the
CSRF check applies as everywhere).

**3. A view of its own**, declared with `ResourcePage(name, view=...)`:

- a subclass of **`ResourcePageView`** gets everything a method page
  gets — it is a `TemplateView` whose `resource`, `page` and `object`
  are set before anything runs, drawn in the frame with its title and
  breadcrumbs. Override `get_context_data`, `get_page_title`,
  `get_toolbar_items`, `post`… as in any class-based view:

  ```python
  class TicketTimelineView(ResourcePageView):
      template_name = "example/pages/ticket_timeline.html"

      def get_context_data(self, **kwargs):
          context = super().get_context_data(**kwargs)
          context["events"] = events_of(self.object)
          return context
  ```

- **any other view** — a function, a class-based view, a DRF `APIView`
  — gets the guard: signed in, allowed, the record found. Then it runs
  with the address's arguments (`pk`, or `key` for a data resource) and
  does the rest itself, frame included. A view exempt from the CSRF check
  stays exempt.

## The declaration

`@page(...)` takes the same options as `ResourcePage(name, view, ...)`,
the name being the method's (underscores become dashes).

| Option | Default | Meaning |
| --- | --- | --- |
| `name` | the method's | A piece of the address and of the route's name: lower case, digits, dashes. Not `add`, `change`, `delete`, `detail` or `list`, which the generated pages use |
| `view` | — | `ResourcePage` only: a `ResourcePageView` subclass, another view, or a function |
| `title` | from the name | The heading, the button, the breadcrumb, the tab |
| `detail` | `False` | A page of each record — `<pk>/<name>/` — rather than of the resource |
| `icon` | `"article"` | Of the button and the navigation entry |
| `description` | `""` | Under the title; a record's page shows the record's name there otherwise |
| `template` | — | What a method's context is drawn with. Required when the method returns a context |
| `permission` | `None` | Needed besides the resource's view permission: `"change"` (or `view`, `add`, `delete`: the resource's own checks), a permission string, several, or `callable(user)` |
| `button` | `True` | A button on the list page, or on the record's page (on its form when it has no summary page) |
| `row_menu` | `False` | An entry of each row's menu in the table — a record's page |
| `navigation` | `False` | An entry of the navigation, after the resource — a page of the resource |
| `methods` | `("get",)` | What a method page answers; `("get", "post")` for a form |

A subclass replaces a parent's page by declaring a method of the same
name, and removes it by redefining the method without `@page`.

## Permissions

The resource's view permission always comes first: a page never shows
what the list would not. `permission` adds what the page needs on top.
For a rule of the record's — a map only for customers with an address —
override the resource's `has_page_permission`:

```python
def has_page_permission(self, request, page, obj=None):
    allowed = super().has_page_permission(request, page, obj)

    if page.name == "map" and obj is not None:
        return allowed and bool(obj.address)

    return allowed
```

A reader who may not open a page has no button, no row menu entry and
no navigation entry, and gets a 403 at its address.

## What goes on a page

Anything the browser can draw. A few things the framework already
provides:

- **A table.** `generic/resource/page.html` loads the table scripts, so
  any resource's table can be placed on a page:

  ```python
  "table": self.get_page_table_config(request, "map")
  ```

  ```django
  {% include "generic/components/table.html" with config=table id="customers" %}
  ```

  `get_page_table_config` is the resource's own table with a saved
  layout of its own and the address left alone. A related table of a
  record — `self.get_bound_related_table("tickets").get_table_config(
  request, obj)` — works the same way.
- **A chart** the resource declares: `{% generic_chart "example.ticket"
  "opened" %}`; or one of the page's own data, with the chart card and a
  JSON page returning `chart_payload(...)` as its `url`.
- **Long text**: the `prose` class sets it at a reading width.
- **Anything else** — an SVG, a gallery, a carousel, a map library the
  project vendors — goes in the template, its styles and scripts in
  `extrastyle` and `extrajs`, written with the design tokens so it
  follows the theme.

## Addresses and links

```python
resource.get_page_url("map")               # /example/customer/map/
resource.get_page_url("timeline", ticket)  # /example/ticket/12/timeline/
```

or `{% url 'site:example_customer_map' %}` and
`{% url 'site:example_ticket_timeline' ticket.pk %}` in a template —
`site:data_services_runbook` for a data resource. The routes sit before
the record's own, so `<pk>/<name>/` is never read as a key.

## When it is not the tool

- A page that belongs to **no resource** — a dashboard of the team, a
  planning board across models — is a page of the project's
  (`site.add_link` puts it in the navigation): see use case 4 in `ai/`.
- A page **mounted elsewhere** but offered from a record keeps using
  `get_record_links(request, obj)`.
- Something that is **one more column, figure or tab** of what the
  resource already shows is a `@display`, a `detail_stats` entry or a
  `RelatedTable`, not a page.

## In the example

| Page | Kind | Shows |
| --- | --- | --- |
| `/example/customer/map/` | `@page`, of the resource, in the navigation | The customers on a drawing of France, bubbles sized by open tickets, then their table |
| `/example/customer/geojson/` | `@page` returning JSON, no button | The same customers as a GeoJSON feature collection |
| `/example/ticket/<pk>/timeline/` | `ResourcePage` around `TicketTimelineView`, in each row's menu | Opened, commented, worked on, changed, due, in one column |
| `/data/services/<id>/runbook/` | `@page` of each row of a data resource | A runbook the API answers on its own, as prose, with what is going wrong now |

The code is in `example/pages.py` and `example/resources.py`, the
templates in `example/templates/example/pages/`.

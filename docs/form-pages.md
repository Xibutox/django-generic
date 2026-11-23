# Form pages

A resource generates its add and change pages: one form, one record,
its inline rows. A **form page** is for the other forms an application
needs, drawn with the same widgets, sections, validation, messages,
dark theme and translations:

| The form | Declared with |
| --- | --- |
| Writes **no model**: send a notice, run a computation, ask a question | a `FormSerializer`, and `form_valid` doing the work |
| Writes **one model**, but is not its add or change page: four fields of a record, a form of its own | a `FormModelSerializer` |
| Writes **several models** at once, all or none: a customer and its first ticket | a `ModelsForm` of `FormPart`s |

```python
from generic.api import FormModelSerializer, FormPart, FormSerializer, ModelsForm
from generic.sites import FormPageView, ResourceFormPageView, ResourcePage
```

The example has one of each (`example/form_pages.py`): *Send a notice*
in the navigation, *New customer with a ticket* on the customers' list,
*Reassign* on each ticket.

## A form that writes no model

```python
from rest_framework import serializers
from generic.api import FormSerializer
from generic.sites import FormPageView


class NoticeForm(FormSerializer):
    recipients = serializers.PrimaryKeyRelatedField(
        label=_("Recipients"), many=True,
        queryset=User.objects.filter(is_active=True),
    )
    title = serializers.CharField(label=_("Title"), max_length=120)
    body = serializers.CharField(
        label=_("Message"), style={"base_template": "textarea.html"}
    )

    form_sections = ({"name": "general", "title": _("Notice")},)
    form_overrides = {"title": {"placeholder": _("Maintenance tonight")}}

    def validate_title(self, value):        # DRF validation, as always
        ...


class NoticePage(FormPageView):
    serializer_class = NoticeForm
    page_title = _("Send a notice")
    description = _("Each recipient finds it in their notifications.")
    submit_label = _("Send")
    icon = "campaign"
    permission_required = "example.change_ticket"

    def form_valid(self, serializer):
        notify(**serializer.validated_data)
        return _("The notice was sent.")       # the message shown
```

```python
# urls.py
path("notice/", NoticePage.as_view(site=site), name="notice"),

# resources.py - in the navigation, for whoever may open it
site.add_link(_("Send a notice"), route="myapp:notice", icon="campaign",
              permission="example.change_ticket")
```

The serializer is the form: its fields, their types, `required`,
`max_length`, choices and validators, laid out by `form_sections` and
`form_overrides` exactly as on a resource's form
([Forms and inlines](forms.md)). A relation is fed by the related
resource's autocomplete, or its choices, and narrowed to what the reader
may reach (`scope_relations`) - in what it offers and in what it accepts.

## A form over one model

```python
class TicketReassignForm(FormModelSerializer):
    class Meta:
        model = Ticket
        fields = ("team", "assignee", "priority", "due_on")


class TicketReassignPage(ResourceFormPageView):
    serializer_class = TicketReassignForm
    submit_label = _("Reassign")
    success_message = _("The ticket was reassigned.")

    def get_success_url(self, result):
        return self.resource.get_detail_url(result.pk)


class TicketResource(ModelResource):
    pages = (
        ResourcePage("reassign", view=TicketReassignPage, detail=True,
                     title=_("Reassign"), icon="swap_horiz", row_menu=True),
    )
```

`form_valid` saves by default. On a record's page (`detail=True`) a
model form of the resource's model **edits the record**: it opens on its
values and saves under the resource's `has_change_permission(request,
obj)`. Anywhere else it creates one.

## A form over several models

```python
class NewCustomerForm(ModelsForm):
    parts = (
        FormPart("customer", Customer,
                 fields=("name", "code", "segment", "city"),
                 title=_("Customer")),
        FormPart("ticket", Ticket,
                 fields=("title", "team", "priority", "description"),
                 title=_("First ticket"),
                 links={"customer": "customer"}),
    )
    form_overrides = {"customer__name": {"width": 8}}

    def get_save_kwargs(self, part, saved):
        if part.name == "ticket":
            return {"reference": next_reference()}
        return {}


class NewCustomerPage(ResourceFormPageView):
    serializer_class = NewCustomerForm
    submit_label = _("Create both")

    def get_success_url(self, result):
        return self.resource.get_detail_url(result["customer"].pk)
```

- **Each part is a section** of the form, titled by `title` (the model's
  name otherwise), its fields named `<part>__<field>`: two parts may both
  have a `name`.
- **Each part is validated by a model serializer of its own** - built
  from `model` and `fields` (or `exclude`), or given as
  `serializer=MyFormModelSerializer`, whose `form_overrides` then apply.
  The model's validators run as on the record's own form, unique checks
  included; an error comes back under the prefixed name.
- **Saved in order, in one transaction.** `links` sets a field of a
  later part to the record an earlier part saved - and that field is not
  asked. A refusal anywhere, while validating or saving, writes nothing.
- **Questions of the form itself** are fields declared on the
  `ModelsForm`, as on any serializer; `validate(attrs)` sees them, and
  every part's values under the part's name, for a rule across models.
- **Editing records** rather than creating them: `get_instance()` returns
  `{"customer": customer, "ticket": ticket}`; a part left out creates
  its record.
- **Hooks**: `get_save_kwargs(part, saved)` - what a part's record is
  saved with besides its fields (a number, the author); `save_part(part,
  serializer, saved)` to save it another way. `form.save()` returns what
  each part saved, by name.

| `FormPart` option | Meaning |
| --- | --- |
| `name` | Lower case, digits, single underscores; the section's name and the fields' prefix |
| `model` + `fields` / `exclude` | The part's model serializer, built for you (`fields` defaults to every field) |
| `serializer` | A `FormModelSerializer` instead of `model` |
| `title`, `description` | The section's heading and sentence |
| `links` | `{field: earlier_part}`: set from what that part saved, not asked |
| `position`, `collapsed` | Section layout |

A part naming no model, an unknown link field, a link to a later part, a
part named like a field of the form: `ImproperlyConfigured`, when the
class is defined.

## What the page does

| The framework | The page |
| --- | --- |
| Sign-in, then the permissions (below); 403 otherwise | `serializer_class` |
| The frame: title, breadcrumbs, the navigation; on a resource, its address and its record | `form_valid`, when the form writes no model |
| The schema, inside the page: no endpoint to ask | |
| The POST, to the page's own address: JSON (or `_payload` multipart, with files), read like any resource endpoint, CSRF checked | |
| Validation by the serializer: a 400 puts each error beside its field | |
| `form_valid` in a transaction: a `ValidationError` raised in it is shown on the form, and nothing is kept | |
| The answer: a message, then the next page - or the form again | |

Once accepted, the page shows its message and goes to
`get_success_url(result)`; with none, it stays, the form opened again on
what is now true - empty for a form that creates, the new values for one
that edits.

### In a dialog

Opened as a popup - in a dialog's frame by `Generic.dialogs.record`, an
*Add* button with [`add_in_dialog`](forms.md#adding-in-a-dialog), or a
popup window (`?_popup=1&_relation_request=...`) - the page is framed by
the site's own pages (`X-Frame-Options: SAMEORIGIN`), drawn without the
navigation, and once accepted tells the page that opened it instead of
going to `get_success_url`: the dialog closes, its page reads its rows
again. The answer names what was saved (`id`, `_label`) when
`form_valid` returns a record.

A page that sends a popup on to another address - a first step, then
the form - keeps it a popup with `generic.views.keep_popup(request,
url)`, the address with the popup parameters the request came with
(`_popup`, `_relation_request`, `_to_field`; nothing outside a popup):

```python
from django.shortcuts import redirect
from generic.views import keep_popup

def form_valid(self, serializer):
    draft = serializer.save()
    return redirect(keep_popup(self.request, draft.get_step_url()))
```

### Options and hooks

| Attribute | Hook | Default |
| --- | --- | --- |
| `serializer_class` | `get_serializer_class()`, `get_serializer_context()` | required |
| `page_title`, `description`, `icon` | `get_page_title()`, `get_description()` | `""`, `""`, `"edit_note"` |
| `submit_label` | `get_submit_label()` | *Submit* |
| `cancel_url` | `get_cancel_url()` | no Cancel link |
| `initial` | `get_initial()` | `{}`; the record's values when it edits one |
| | `get_instance()` | `None`; the record on a resource record's page |
| | `form_valid(serializer)` | `serializer.save()`; refuses a plain `FormSerializer` with no `create` |
| `success_message` | `get_success_message(result)` | a string `form_valid` returned, else *Done.* |
| `success_url` | `get_success_url(result)` | stay on the page |
| `permission_required` | `get_required_permissions()`, `has_form_permission()` | below |

`form_valid` returns a message, anything `get_success_message` and
`get_success_url` make sense of, or a `JsonResponse` sent as it is.

### Permissions

A form page asks, besides being signed in:

- `permission_required`: one permission or several, all needed;
- what its models need: **add** a record a model form creates,
  **change** one it edits - for a `ModelsForm`, of every part's model;
- on a resource (`ResourceFormPageView`): the resource's view
  permission and the page's own `permission` first, then, for the
  resource's own model, the resource's `has_add_permission` /
  `has_change_permission(request, obj)` rather than the bare model
  permission - its teams and its rules apply.

A reader who lacks them gets a 403 at the address, on GET and POST, and
no button or navigation entry.

## Templates

`generic/form_page.html` draws the page; `form_config` is the form's
configuration, `form_description` the sentence. A template of your own
extends it and fills `form_intro` (above the form) or `form_after`
(below):

```python
class NoticePage(FormPageView):
    template_name = "myapp/notice.html"
```

```django
{% extends "generic/form_page.html" %}
{% block form_after %}<p class="muted">{% translate "Sent notices are kept 90 days." %}</p>{% endblock %}
```

In the browser the form is the one every resource uses
(`static/generic/js/forms/form.js`), started with `formPage: true` and
the schema in `schema`; it dispatches `generic:form-saved` on its host
once the page accepted it.

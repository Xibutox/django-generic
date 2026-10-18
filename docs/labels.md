# Labels with QR codes

A sticker on each laptop, box or shelf: the record's name, a few of
its values and a QR code that opens its page when scanned. A resource
declares what its labels show, and gets two ways to print them.

```python
from generic.sites import Labels, ModelResource, register


@register(Equipment)
class EquipmentResource(ModelResource):
    labels = True                                     # the list's first columns
    labels = Labels(
        fields=("serial_number", "kind", "supplier"),  # under the name
        size="medium",                                # small, medium, large
        content=None,                                 # what the code holds
        title=None,                                   # the first line
        permission=None,                              # besides view
    )

# On an auto() resource, as any attribute:
auto(Equipment, labels=Labels(fields=("serial_number", "kind")))
```

- **Many at once.** The list's selection bar gains the bulk action
  *Print labels*: the rows ticked, or every row the filters match, up
  to 500 (`MAX_LABELS`). It opens `<model>/labels/?ids=3,8,12`, a sheet
  of labels in the list's order.
- **One.** A record's page gains a *Label* button, opening
  `<model>/<pk>/label/`.

The sheet has a *Print* button. On paper only the labels remain - no
navigation, no header - laid out at their size in millimetres for
common sheets of stickers.

## Options

| Option | Default | Means |
| --- | --- | --- |
| `fields` | the list's 2nd to 4th columns | values written under the name, as a summary page shows them: fields, model attributes, resource methods |
| `size` | `"medium"` | `small` (38 x 21 mm: code and name only), `medium` (63 x 38 mm), `large` (99 x 57 mm) |
| `content` | the record's page | what the code holds: a field, method or attribute whose value is encoded instead (a serial number for a scanner) |
| `title` | the record's label | the first line: a field or method |
| `permission` | `None` | needed besides the resource's view permission, as a page's |

## The code

By default the code holds the **absolute address of the record's
page**. Scanned with a phone, it opens the page - behind the sign-in,
with the rights of whoever scans it: the code is an address, never a
key.

Codes are drawn on the server by [segno](https://pypi.org/project/segno/)
(pure Python, no dependency), as inline SVG with no text of the record
in it:

```bash
pip install "django-generic[labels]"
```

Without segno the labels still print, the address written out where
the code would be.

## Who sees what

Printing needs the view permission (and `permission`, if declared). The
sheet reads its records through the list's queryset and each one's
`has_view_permission`: a record the reader may not see is left out.

## Checked where it is written

At registration, `ImproperlyConfigured` naming the resource for a size
that is not small, medium or large, `fields` given as one string, or a
field, `content` or `title` the summary page could not show.

## In the browser

`generic/resource/labels.html`, `css/labels.css` (its `@media print`
rules), `js/labels.js` (the *Print* button). Labels are white with black
ink in both themes: a code is read dark on light only.

The example's equipment has them: *Equipment › Equipment*, tick some
rows, *Print labels*.

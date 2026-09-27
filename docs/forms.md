# Forms and inlines

## The contract

The backend does not render forms. It publishes a **schema** describing
the fields, and the frontend renders it. DRF stays the authority on
everything that matters: field types, writability, required flags,
choices, limits and validation.

`form_overrides` carries presentation only — labels, placeholders,
sections, positions, widget hints, related-object editors. It cannot
make a read-only field writable or relax a validation rule. That
boundary is the point: a form cannot drift away from what the API
actually accepts.

## A minimal form endpoint

```python
from generic.api import FormModelSerializer, ModelFormViewSet


class BookFormSerializer(FormModelSerializer):
    class Meta:
        model = Book
        fields = ("id", "title", "author", "price", "is_available")

    form_sections = (
        {"name": "general", "title": "General", "position": 0},
        {"name": "commercial", "title": "Commercial", "position": 1},
    )

    form_overrides = {
        "title": {"placeholder": "Book title", "position": 0},
        "price": {"section": "commercial"},
        "is_available": {"section": "commercial"},
    }


class BookFormViewSet(ModelFormViewSet):
    serializer_class = BookFormSerializer
    queryset = Book.objects.all()
```

That gives you full CRUD plus:

- `GET  /api/books/form-schema/?mode=create|update|delete`
- `GET  /api/books/{pk}/deletion-preview/`

## The schema

```json
{
  "version": 2,
  "mode": "update",
  "title": "Edit the record",
  "submitLabel": "Save",
  "sections": [
    {"name": "general", "title": "General", "position": 0}
  ],
  "fields": [
    {
      "name": "title",
      "type": "text",
      "widget": "text",
      "label": "Title",
      "required": true,
      "readOnly": false,
      "maxLength": 200,
      "placeholder": "Book title",
      "section": "general",
      "position": 0,
      "width": 12
    }
  ],
  "inlines": [ … ]
}
```

Keys whose value is `None` are omitted, so the payload stays small.
`False`, `0` and `""` are kept — they are meaningful form values.

## Field types

Inferred from the DRF field: `boolean`, `integer`, `decimal`, `float`,
`datetime`, `date`, `time`, `duration`, `email`, `url`, `slug`, `uuid`,
`file`, `image`, `multiselect`, `select`, `json`, `list`, `object`,
`text`.

A relation becomes `select`, a many-relation `multiselect`, and both
carry `"relation": true`.

## Override options

| Key | Meaning |
| --- | --- |
| `enabled: False` | Drop the field from the form |
| `label`, `placeholder`, `helpText` | Text |
| `section`, `position` | Layout |
| `width` | Grid columns out of 12 |
| `widget` | Force a widget: `textarea`, `select`, `json`, `color` (a picker beside the text, which may stay empty)… |
| `multiline: True` | Turn an unbounded text field into a textarea |
| `rows`, `step` | Widget details |
| `relatedEditorView` | Named route to a create/edit page for the target |
| `relatedEditorUrl` | Literal URL, when the route is not reversible |
| `relatedPopupWidth`, `relatedPopupHeight` | Popup size |

`relatedEditorView` must reverse **without** a primary key: the frontend
appends one for edit and uses the bare URL for create. A route that
cannot reverse raises at schema build with a message naming the field,
rather than producing a dead button.

Overrides merge along the MRO, so a subclass restates only what it
changes.

## Sections

A field whose `section` names an undeclared section would silently
vanish from the rendered form, so `get_form_schema()` raises instead:

```
RuntimeError: BookFormSerializer places fields in undeclared sections:
nowhere. Declare them in form_sections.
```

## Tabular inlines

```python
class BookFormViewSet(ModelFormViewSet):
    serializer_class = BookFormSerializer
    queryset = Book.objects.all()

    inline_form_definitions = (
        InlineFormDefinition(
            name="chapters",
            serializer_class=ChapterFormSerializer,
            related_name="chapters",   # reverse manager on Book
            parent_field="book",       # FK on Chapter
            title="Chapters",
            min_rows=1,
            max_rows=20,
        ),
    )
```

`GET /api/books/{pk}/` then embeds the rows, and a write carries them
back:

```json
{
  "title": "Emma",
  "_inlines": {
    "chapters": [
      {"id": 1, "title": "Volume One"},
      {"id": 2, "_delete": true},
      {"title": "Volume III", "position": 3}
    ]
  }
}
```

A row with an `id` is updated, one without is created, one flagged
`_delete` is removed. A collection **absent** from the payload is left
alone entirely — a partial update need not resend rows it does not
touch.

### What is guaranteed

- **All or nothing.** Everything runs in one transaction. A rejected
  row rolls the parent change back with it.
- **No reparenting.** The parent link is never taken from the payload;
  whatever the client sends is overwritten with the real parent.
- **No cross-parent access.** A row `id` is looked up only among the
  rows belonging to *this* parent. An id from elsewhere is reported as
  "Row not found", not applied.
- **Deletions free their slots.** Removals are executed before the
  remaining rows are validated, so one request can delete the row
  holding a unique position and create another in its place.

### Definition options

| Option | Default | Meaning |
| --- | --- | --- |
| `primary_key` | `"id"` | Field identifying an existing row |
| `position` | `0` | Order among inlines |
| `extra` | `0` | Blank rows the client pre-renders |
| `min_rows`, `max_rows` | `0`, `None` | Enforced server-side |
| `can_add`, `can_delete` | `True` | Enforced server-side |
| `add_label`, `delete_label` | | Button text |
| `form_overrides` | `{}` | Presentation, on top of the serializer's |

### Error shape

Errors are addressed by collection and row index:

```json
{
  "_inlines": {
    "chapters": {
      "1": {"title": ["This field may not be blank."]},
      "_errors": ["At most 5 row(s) are allowed."]
    }
  }
}
```

`_errors` holds problems belonging to the collection rather than to one
row.

## Deletion preview

`GET /api/books/{pk}/deletion-preview/` reports what a deletion would
take with it, using Django's own cascade collector:

```json
{
  "canDelete": false,
  "object": {"model": "testapp.publisher", "id": "1",
             "label": "Gallimard"},
  "nested": [ … ],
  "protected": [{"model": "testapp.book", "label": "Emma", …}]
}
```

`canDelete` is `false` when a `PROTECT` or `RESTRICT` relation stands in
the way, so the confirmation dialog can say why instead of failing on
submit.

## Files

A model's `FileField` (and `ImageField`) is a field of the generated
form like any other: declared on the model, listed in `fields` or a
fieldset, and the form offers to choose a file, replace it or remove
it. Nothing is served from `MEDIA_URL`: a file is downloaded through
the record's own endpoint, which checks who asks.

```python
# models.py
attachment = models.FileField(
    _("attachment"),
    upload_to="tickets/%Y/%m/",
    blank=True,                       # may be removed
    validators=[FileExtensionValidator(["pdf", "png", "jpg", "txt"])],
)

# settings.py
MEDIA_ROOT = BASE_DIR / "media"       # where files are written; no MEDIA_URL
GENERIC = {"FILE_MAX_SIZE": 10 * 1024 * 1024}    # the default, in bytes
```

### What the form shows

In the schema, a file field has `type` `"file"` (or `"image"`) and two
keys more:

| Key | From |
| --- | --- |
| `accept` | The `FileExtensionValidator` of the model field (`".pdf,.png,.jpg,.txt"`); `"image/*"` for an image field without one; absent otherwise |
| `maxSize` | `GENERIC["FILE_MAX_SIZE"]`, in bytes |

The record's value - in the form's `GET`, a table cell, the summary
page - is an object, or `null` when the field is empty:

```json
{"name": "invoice.pdf", "url": "/api/example/ticket/7/files/attachment/", "size": 48213}
```

The widget shows the current file as a link to that `url`, with its
size; a *Choose a file* / *Replace* button - a real `<label>` over the
native `<input type="file" accept="...">`, which stays reachable by the
keyboard; *Remove* when the field may be empty (`blank=True`); the
chosen file's name and size before saving, and *Cancel* to drop it. A
file over `maxSize`, or outside `accept`, is refused at once, under
the field, before anything is sent - and by the server again.

### What is sent

Without a new file, the form sends JSON, exactly as before - a file
nobody touched is left out, and the API keeps it. With one, it sends
`multipart/form-data`:

| Part | Holds |
| --- | --- |
| `_payload` | The JSON body a form without files would have sent - the inline rows (`_inlines`) included, the files left out |
| `<field>` | One part per chosen file, named by its field |

`generic.api.parsers.MultiPartJSONParser` puts them back together: the
request's data is the payload, a plain dict, with each file under its
field - so a many-to-many, a JSON field or the inline rows arrive
exactly as JSON would carry them. A request without `_payload` is plain
multipart, as DRF parses it, and still works (`_inlines` then travels
as a JSON string). Every resource endpoint and `ModelFormViewSet`
reads JSON, `_payload` multipart and HTML forms
(`generic.api.viewsets.FORM_PARSERS`).

A removed file travels in the JSON as `"attachment": null`: a field
whose model field is `blank=True` accepts `null` (or `""`) and stores an
empty name; a required one refuses it with a 400. The size is checked
against `FILE_MAX_SIZE` ("The file is too large: at most 10 MB."), and
the model field's validators apply as usual - an extension outside the
`FileExtensionValidator` is a 400 under the field.

### The download

```
GET api/<app>/<model>/<pk>/files/<field>/        site:api_<app>_<model>-file
```

- The record is read through the resource's queryset: its view
  permission and its row restrictions (`get_queryset`) apply - 403
  without the permission, 404 for a record out of reach.
- `<field>` must be a file field the resource shows this reader - in
  its form, its summary page (sections and figures) or its list;
  `resource.get_file_fields(request)` says which. Anything else, an
  empty field and a file the storage no longer holds are a 404.
- The file is opened through the field's own storage - any storage,
  not only the file system - and answered with `FileResponse`, its
  type guessed from its name (`application/octet-stream` otherwise).
- A PNG, JPEG, GIF or WebP image is shown in the browser (`inline`);
  everything else is `attachment; filename=...`, with the RFC 6266
  form for a name outside ASCII. An HTML page or an SVG is **never**
  shown: an uploaded file must not run script in the site's origin.
- Every answer, refusals included, carries `X-Content-Type-Options:
  nosniff` and `Content-Security-Policy: sandbox`.

In a table, a file column draws the name as a link to the download
(its `size` is left `null`: asking the storage would be a request per
row on a remote one); an export writes the name.

### Keeping files

`MEDIA_ROOT` is where files are written, and has to be set:
`manage.py check` warns `generic.W010` when a registered model has a
file field and it is empty - files would land relative to whatever
directory the server started in. Back it up with the database
([deployment](deployment.md#backups)).

A file that is **replaced or removed is not deleted** from the
storage: the record's history keeps versions naming it, and restoring
one of them must find its file. Clean the storage yourself, knowingly,
if it matters.

### What files do not do

- **Grids**: a file field in `editable_fields` raises
  `ImproperlyConfigured` - a cell writes JSON; a file is chosen on the
  record's form.
- **Imports**: a file field is not importable (`Import(fields=...)`
  naming one raises); a spreadsheet cell cannot hold a file.
- **Inline rows**: a file field of an inline is shown, read-only, with
  its link - rows travel inside the parent's JSON, where no file can.
  Choose the file on the row's own form.

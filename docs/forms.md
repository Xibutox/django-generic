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

## File uploads

A multipart request can only send nested rows as a JSON string, so
`_inlines` is parsed from a string when it arrives as one. Everything
else is unchanged.

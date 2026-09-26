# Imports

A resource that declares `imports` gets an **Import** button on its
list page. It leads to a page where the reader picks an Excel or CSV
file, checks which column of the file goes to which field, sees what
would happen - every error named by row and column - and confirms.

Nothing is importable unless declared: `imports = None` is the default.
And a file exported from a table imports back as it is: headers are
matched on the titles the export writes, relations on the labels it
writes, and a row that changes nothing is counted as unchanged.

## Declaring it

```python
from generic.sites import Import, ModelResource, register


@register(Ticket)
class TicketResource(ModelResource):
    imports = Import(
        fields=("reference", "title", "customer", "team", "priority",
                "status", "due_on", "tags"),
        key="reference",
        description=_("One row per ticket. Leave a cell empty to keep "
                      "its value."),
    )
```

| Option | Default | Meaning |
| --- | --- | --- |
| `fields` | the form's editable fields | what a file may fill, by name |
| `key` | None | a unique field: a row whose key exists updates that record |
| `mode` | `create_update` with a key, `create` without | also `update`: rows must match a record |
| `lookups` | the related model's naming field | `{relation: field}`: what a cell is matched against, e.g. `{"customer": "code"}` |
| `defaults` | None | `{field: value}` or `callable(request)`, for new records |
| `permission` | None | needed on top of add or change: a permission string or `callable(user)` |
| `max_rows` | `IMPORT_MAX_ROWS` | rows one file may hold |
| `description` | `""` | shown on the page: what a row is |

`imports = True` is `Import()`: the form's fields, every row new.

A declaration is checked when the resource is registered: an unknown
field, a key that is not unique, an update mode without a key, a
lookup on something that is not a relation, all raise
`ImproperlyConfigured` naming the resource. A field its form cannot
write raises at the first use, when the form serializer exists.

Two hooks, on the resource:

```python
def clean_import_row(self, request, values, row_number):
    """Values converted, before validation. Return them; raise
    ValidationError to refuse the row."""
    values["reference"] = values["reference"].upper()
    return values

def save_import_row(self, request, serializer, instance):
    """The write. Default: save_model, as the form does - so a resource
    stamping its author stamps imported records too."""
    return super().save_import_row(request, serializer, instance)
```

## What happens to a file

1. **Read.** `.xlsx` through openpyxl, values only - a formula gives
   the value it last computed and is never run; `.csv` in UTF-8 (with
   or without the BOM Excel writes) or Windows-1252, the delimiter
   found among `;`, `,` and tab. The first non-empty row holds the
   headers; empty rows are skipped. Size and row limits are checked
   while reading.
2. **Map.** Each header is matched, ignoring case and accents, against
   a column's name, its title in the reader's language, the title the
   export writes, and the field's verbose name. The reader can change
   any match, or ignore a column. Headers matching nothing are listed.
3. **Convert.** Each cell becomes what the form would send:

   | Field | A cell may say |
   | --- | --- |
   | choices | the value, or the label in any language the project offers (`Resolved`, `Résolu`) |
   | boolean | `yes/no`, `oui/non`, `true/false`, `1/0`, `x` |
   | date, date and time | an Excel date, ISO, or the reader's own format (`31/12/2026` in French) |
   | numbers | an Excel number, `3.5`, `3,5`, `1 234,56`, `1,234.56` |
   | relation | the related record's label (see `lookups`), ignoring case and accents with `generic.search` |
   | many-to-many | labels separated by commas, as the export writes them |

   A relation is looked up **among the records the importer may view**
   in the related resource: a label naming one they may not see is not
   found. An unknown label, or one naming two records, is an error on
   that cell.
4. **Validate.** Each row goes through the resource's own form
   serializer: required fields, validators, unique fields. A row
   updating a record is partial - only the columns of the file are
   written, and an empty cell keeps what is stored - and needs
   `has_change_permission(request, obj)`; a new row needs the add
   permission.
5. **Write.** In one transaction, all or nothing: one row in error and
   no row is written. Every save runs as the importer, with the file's
   name as the source (`acting_as`), so the History tab says *Import
   march.csv*. The live updates are held and sent once, as one `bulk`
   change (`generic.sites.realtime.batch`); watchers are told of each
   record, as for any change.

**The preview is the same run, rolled back.** Unique fields and the
database's constraints are checked for real - two rows of one file
claiming the same unique name are caught. Nothing is kept on the server
between the preview and the import: the browser sends the file again,
with the matches the reader confirmed, and it is checked again from
the start.

## The page

`<app>/<model>/import/` (`site:<app>_<model>_import`), template
`generic/resource/import.html`, Alpine component `resourceImport`
(`js/imports.js`):

1. **Choose a file** - drop it, or pick it; *Download a template* gives
   an empty workbook with the headers, and a second sheet listing the
   values of each choice column.
2. **Match the columns** - one line per column of the file, its first
   value, and where it goes. Required fields no column goes to are
   named (for new records).
3. **Preview** - how many records would be created, updated, left
   unchanged, and refused; the errors by row and column; the first rows
   as they will be written.
4. **Import** - enabled when nothing is in error.

The button is offered to readers who may import; the endpoint checks
again, as always.

## Endpoints

| Request | Does |
| --- | --- |
| `GET api/<app>/<model>/import/schema/` | the columns (name, title, type, required, choices, lookup), key, mode, limits |
| `GET api/<app>/<model>/import/template/` | the empty workbook |
| `POST api/<app>/<model>/import/` | multipart `file`, `mapping` (JSON list: a column name or null per header), `commit` (`true` to write) |

The answer: `headers`, `mapping`, `unmatched`, `missing`, `rows`,
`counts` (`create`, `update`, `unchanged`, `error`), `errors`
(`row`, `column`, `message` - at most 200), `preview`, `committed`.

Refused: 404 where the resource declares no import; 403 to a reader
who may neither add nor change, or lacks the declared `permission`;
400 for no file, another format, a file too large or too long, an
unreadable workbook, `.xlsx` without openpyxl, or a mapping naming a
column the declaration does not offer.

## Settings and packaging

| Setting | Default | |
| --- | --- | --- |
| `IMPORT_MAX_ROWS` | `5000` | rows per file |
| `IMPORT_MAX_FILE_SIZE` | `5 * 1024 * 1024` | bytes, refused before reading |
| `IMPORT_PREVIEW_ROWS` | `20` | rows the preview shows |

`pip install "django-generic[import]"` brings openpyxl and defusedxml -
with the second installed, openpyxl refuses the XML tricks a hostile
workbook could hold. CSV needs nothing.

Not covered yet: inlines and child rows, and files too large for one
request, which will go through a task.

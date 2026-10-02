# Word files merged with a template

`generic.docx` puts several Word files together into one: the documents,
in the order chosen, inside a new document made from a template - a
`.docx`, or a `.dotx` Word template - whose styles, page set-up, headers
and footers the result keeps. The result is a `.docx` to download;
nothing is stored.

It comes in two parts:

- **`merge_docx()`**, a function any view can call on any files: a
  model's file fields, uploads, paths, bytes. A project's own page
  merges its records' files with it ([In a project's own
  page](#in-a-projects-own-page)).
- **The merge page** (`docx/`) and its endpoint
  (`api/generic/docx/merge/`), where people merge files they upload:
  a template, the documents, their order, a name for the result.

Everything runs in the request, in memory, on
[python-docx](https://python-docx.readthedocs.io) and
[docxcompose](https://github.com/4teamwork/docxcompose) - both pure
`pip` packages (MIT), installed on Windows, macOS and Linux alike.

## Enabling it

The `docx` extra in the brackets after the framework's wheel in
`requirements.txt` (see [Extras](installation.md#extras)), then:

```python
INSTALLED_APPS = [
    ...,
    "generic",
    "generic.docx",
]

urlpatterns = [
    ...,
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("docx/", include("generic.docx.urls")),
    path("", site.urls),
]
```

No migration: the app has no model. The sidebar gets *Merge Word files*
for whoever may merge. `merge_docx()` alone needs only the extra, not
the app.

`python manage.py check` says `generic.E009` when the app is installed
and python-docx or docxcompose is not.

## What the result holds

| The template... | The result |
| --- | --- |
| is not given | the first document, with the others after it |
| has no text (one empty paragraph, what Word saves) | the template's styles, headers and footers, the documents from the top |
| has text | its text, then the documents |
| has a paragraph reading `{{ documents }}` | its text, the documents in place of that paragraph, then the rest of its text |

- **Styles**: a style both the template and a document define (*Heading
  1*, *Normal*) looks as the template says; a style only a document
  has comes along with it. Lists keep their numbering, each document's
  restarting.
- **Headers, footers, page set-up**: the template's (or the first
  document's), for the whole result. Those of the other documents are
  left out.
- **Pictures, tables, footnotes, shapes** come along with their
  document.
- **Page breaks**: each document starts on a new page (`page_breaks`,
  on by default) - except the first one when nothing comes before it.
  In a template with `{{ documents }}`, a page break of its own before
  that paragraph puts the documents on a new page.
- **Accepted**: `.docx` and `.dotx` files, recognised by their
  content, not their name. Refused, with a sentence naming the file:
  an older `.doc`, a file with macros (`.docm`, `.dotm`), anything
  else, and a file that would unpack beyond 256 MB.

## The merge page

`docx/` (`generic_docx:merge`), for whoever may merge:

1. **Template** (optional): a `.docx` or `.dotx`, chosen or dropped.
2. **Documents**: as many as `DOCX_MERGE_MAX_FILES` allows (50), chosen
   or dropped, several at a time, each checked in the browser - a Word
   file, at most `FILE_MAX_SIZE` - before anything is sent. The arrows
   move a document up and down the list; the cross takes it out.
3. **Merged file**: its name (`merged.docx` when empty) and whether
   each document starts a new page; *Merge and download* sends
   everything and saves the answer.

A refusal - a file that is no Word file, too large, too many files -
is shown above the cards, naming the file.

## The endpoint

`POST api/generic/docx/merge/` (`generic:docx-merge`), multipart:

| Part | |
| --- | --- |
| `documents` | one part per document, in the order they are merged; at least one |
| `template` | optional: the `.docx` or `.dotx` the result is made from |
| `name` | optional: the file name of the answer; `.docx` is added |
| `page_breaks` | optional, `true` by default; `false`, `0`, `no` or `off` turns it off |

Answers `200` with the merged file as an attachment
(`application/vnd.openxmlformats-officedocument.wordprocessingml.document`,
`X-Content-Type-Options: nosniff`), or `400` with `{"detail"}` naming
what is wrong: no document, too many, an empty file or one over
`FILE_MAX_SIZE`, a file that cannot be merged. Signed out, or without
the permission: `403`. It is in the OpenAPI description
([The API for scripts](api.md)) as a binary answer.

```bash
curl -H "Authorization: Token $TOKEN" \
     -F documents=@intro.docx -F documents=@chapter.docx \
     -F template=@letterhead.dotx -F name=report \
     https://desk.example.com/api/generic/docx/merge/ -o report.docx
```

From a page of the project's own, `Generic.api.download(url, body)`
sends a `FormData` (or JSON) and saves the file the answer holds, under
the name the server gives it; a refusal rejects with an `ApiError`
carrying its message, like `Generic.api.post`.

## Who may merge

`GENERIC["DOCX_MERGE_PERMISSION"]` decides, for the page, its sidebar
entry and the endpoint alike - written like a navigation link's
`permission`:

```python
GENERIC = {
    "DOCX_MERGE_PERMISSION": None,                       # anyone signed in (default)
    "DOCX_MERGE_PERMISSION": "documents.view_document",  # one permission
    "DOCX_MERGE_PERMISSION": ("a.x", "b.y"),             # all of them
    "DOCX_MERGE_PERMISSION": lambda user: user.is_staff,
}
```

The page merges what the reader uploads, and reads nothing stored: who
may merge decides nothing about who may read a record's files. A page
merging stored files checks that itself, as below.

## In a project's own page

Records' files merged and downloaded - here a resource's page
([Pages of a resource's own](pages.md)), whose guard already checked
the reader's view permission; `get_queryset(request)` keeps them to the
records they may see:

```python
from generic.docx import docx_response, merge_docx
from generic.sites import ModelResource, page, register


@register(Document)
class DocumentResource(ModelResource):
    @page(title=_("Merged"), icon="merge_type")
    def merged(self, request):
        documents = self.get_queryset(request).order_by("position")

        return docx_response(
            merge_docx(
                [document.file for document in documents],
                template=Letterhead.objects.get().file,
            ),
            "dossier.docx",
        )
```

```python
merge_docx(documents, template=None, *, page_breaks=True,
           placeholder="{{ documents }}") -> bytes
```

- `documents`: in order; each bytes, a path, an open file, an upload
  or a model's file field (`FieldFile`, opened from its storage and
  closed again). An upload already read is read again from the start.
- `template`: the same kinds, or `None`.
- `placeholder`: the text of the paragraph the documents replace;
  spaces inside it do not matter (`{{documents}}` matches too).
- Raises `generic.docx.DocxMergeError` (a `ValueError`) with a
  sentence for people - turn it into a message or a `400` - and
  `ImportError` without the extra.

`docx_response(content, name="merged.docx")` sends the bytes as a
download: the name stripped of folders and quotes, `.docx` added
(`docx_name(name)`), `nosniff` set.

Long merges - hundreds of documents - belong in an operation
([Operations](operations.md)) that stores the result where the reader
downloads it later.

The example does it on its tickets: *Word attachments*, on the ticket
list, merges the `.docx` files attached to the tickets the reader may
see ([The example](example.md)).

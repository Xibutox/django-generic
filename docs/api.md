# The API for scripts: tokens and OpenAPI

Every screen of a django-generic application already reads and writes
through its REST API - the list, the form, the summary, the charts,
the exports. Two optional apps open that API to scripts:

- **`generic.tokens`** - personal API tokens, on
  [django-rest-knox](https://github.com/jazzband/django-rest-knox),
  made and revoked from the account page;
- **`generic.openapi`** - the OpenAPI description of the endpoints and
  a Swagger UI page, on
  [drf-spectacular](https://drf-spectacular.readthedocs.io), its files
  served by the application (no CDN).

A token acts with **exactly its owner's permissions**. Nothing about
who may do what is new: every resource decides as it does for a page.

## Turning it on

The `api` extra - `api` in the brackets after the framework's wheel in
`requirements.txt`, then `pip install -r requirements.txt` (see
[Extras](installation.md#extras)) - then:

```python
INSTALLED_APPS = [
    ...,
    "knox",
    "generic.tokens",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    ...,
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "generic.tokens.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {"TITLE": "My application API"}   # optional
```

```python
# urls.py - before site.urls
path("api/", include("generic.openapi.urls")),   # api/schema/ and api/docs/
```

```bash
python manage.py migrate
```

`python manage.py check` names what is missing: `generic.E006` knox not
installed, `generic.W008`
the authentication class not in DRF's list, `generic.E008` the OpenAPI
pages mounted without drf-spectacular, its sidecar or its schema class.

## Tokens

### Making one

On the **account page**, *API tokens*: a name (what will use it), a
scope, and how long it lasts - 30, 90 or 365 days
(`API_TOKEN_DEFAULT_DAYS` is preselected, `API_TOKEN_MAX_DAYS` the
longest; `None` there allows tokens that never expire). The token is
shown **once**, with a *Copy* button: only a hash of it is stored, and
nobody - its owner, an administrator - can read it again.

Making tokens needs `generic_tokens.add_apitoken`; out of the box,
only superusers hold it. Grant it to the groups that script.

| Scope | May |
| --- | --- |
| Read only (default) | `GET`, `HEAD`, `OPTIONS`; anything else is refused (403) |
| Read and write | everything its owner may do |

Expired tokens, revoked tokens and tokens of inactive accounts are
refused. When a token was last used is kept, written at most once a
minute.

### Using one

```bash
curl -H "Authorization: Token 3f9c…" \
  "https://desk.example.com/api/example/ticket/?length=50&ordering=-opened_at"
```

```python
import json, requests

session = requests.Session()
session.headers["Authorization"] = "Token 3f9c…"
filters = {"match": "all", "conditions": [
    {"column": "status", "operator": "any_of", "value": ["open"]},
    {"column": "opened_at", "operator": "older_than_days", "value": 30},
]}
rows = session.get(
    "https://desk.example.com/api/example/ticket/",
    params={"filters": json.dumps(filters), "length": 500},
).json()["data"]

# A write, with a read-and-write token:
session.patch("https://desk.example.com/api/example/ticket/42/",
              json={"status": "closed"})
```

A token request carries no cookie, so no CSRF token either; a browser
session still needs its CSRF token exactly as before.

### Files

A record's file (`docs/forms.md#files`) reads as `{"name", "url",
"size"}`; `url` is its download, permission-checked like the record:

```bash
curl -H "Authorization: Token 3f9c…" -OJ \
  "https://desk.example.com/api/example/ticket/42/files/attachment/"
```

A write carrying a file is `multipart/form-data`, in either of two
shapes. What the generated forms send: a `_payload` part holding the
JSON body - many-to-many, JSON fields, `_inlines` as JSON would carry
them - and one part per file, named by its field:

```python
with open("log.txt", "rb") as log:
    session.patch(
        "https://desk.example.com/api/example/ticket/42/",
        data={"_payload": json.dumps({"priority": "high", "tags": [1, 3]})},
        files={"attachment": ("log.txt", log, "text/plain")},
    )
```

Or classic multipart, the fields as form fields (a many-to-many as the
same key repeated, `_inlines` as a JSON string):

```bash
curl -H "Authorization: Token 3f9c…" -X PATCH \
  -F priority=high -F attachment=@log.txt \
  "https://desk.example.com/api/example/ticket/42/"
```

`{"attachment": null}`, in JSON, removes a file the field may go
without. A file over `GENERIC["FILE_MAX_SIZE"]` (10 MB), or of an
extension the model field refuses, is a 400 under its field.

A refused request answers **403** when `SessionAuthentication` is first
in `DEFAULT_AUTHENTICATION_CLASSES` - DRF names the scheme of the first
class, and sessions have none. List the token class first for a 401
with `WWW-Authenticate: Token`.

### Revoking

The account page's *Revoke* stops a token at once. The **API tokens**
screen, under People, lists everyone's for holders of
`generic_tokens.view_apitoken`, and revokes them with
`generic_tokens.delete_apitoken` - when someone leaves, their scripts
stop with them. Nobody changes a token: revoke it, make another.

Endpoints (session only - a token cannot make tokens):
`GET/POST api/generic/tokens/`, `DELETE api/generic/tokens/<id>/`.

## The OpenAPI description

`api/schema/` (JSON with `?format=json`, YAML by default) and
`api/docs/` (Swagger UI; *Authorize* takes `Token <token>`). Both need a
signed-in reader, by session or token, and **list only the endpoints
that reader may use**: a model the reader cannot open is not in the
description at all.

Every generated endpoint is described as it behaves:

| Endpoint | Described as |
| --- | --- |
| `GET api/<app>/<model>/` | the DataTables envelope `{draw, recordsTotal, recordsFiltered, data: [row]}`, the rows typed from the table serializer; parameters `draw`, `start`, `length`, `ordering`, `filters` (the filter tree, with its operators), `search`, `_related` |
| `POST`, `GET/PATCH/PUT/DELETE .../<pk>/` | the form serializer |
| `.../<pk>/summary/`, `history/`, `form-schema/`, `facets/`, `autocomplete/`, `charts/{chart}/`, `actions/`, `cells/`, `rows/`, `import/...` | objects, with their parameters |
| `export/`, `export-csv/`, `import/template/`, `<pk>/files/{field}/` | files (the last only on a model that has file fields) |

Tags are the resources' names; generated serializers are named after
their app (`ExampleTicketTable`), so a project's own serializer of the
same name never collides. The framework's own views carry the
inspector (`generic.openapi.schema.ResourceAutoSchema`) whenever
`drf_spectacular` is installed; a project without it keeps DRF's.

The example checks its description in CI, and a project can do the
same:

```bash
python manage.py spectacular --validate --fail-on-warn --file /dev/null
```

A column of a project's own that the schema cannot type is named
there; give it `@extend_schema_field(...)`, or an
`OpenApiSerializerFieldExtension` as `generic/openapi/schema.py` does
for tags.

## Settings

| Setting | Default | |
| --- | --- | --- |
| `API_TOKEN_DEFAULT_DAYS` | `90` | a new token's life, unless chosen |
| `API_TOKEN_MAX_DAYS` | `365` | the longest; `None` allows tokens that never expire |
| `API_TOKEN_LIMIT_PER_USER` | `10` | tokens one person may hold |

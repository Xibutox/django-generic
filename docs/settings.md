# Settings

Every tunable lives in one dict. Override any subset; the rest keeps its
default.

```python
GENERIC = {
    "TABLE_PAGE_SIZE": 25,
    "EXPORT_MAX_ROWS": 100_000,
}
```

Read them through the singleton, never from `django.conf.settings`
directly — the singleton is what applies the defaults:

```python
from generic.conf import generic_settings

generic_settings.TABLE_PAGE_SIZE
```

Values are cached and dropped whenever Django emits `setting_changed`,
so `override_settings(GENERIC={...})` works in tests. An unknown name
raises `AttributeError` listing the valid ones, so a typo surfaces at
once instead of silently reading `None`.

## Site

| Setting | Default | Meaning |
| --- | --- | --- |
| `SITE_TITLE` | `"Generic"` | Browser title and brand |
| `SITE_HEADER` | `None` | Brand text, when it differs from the title |
| `SITE_ICON` | `"dataset"` | Brand icon, a Material Symbols name |
| `SITE_URL` | `None` | Where the brand links; the dashboard by default |
| `SHOW_ADMIN_LINK` | `True` | Link staff to the Django admin, when it is mounted |
| `THEME` | `{}` | Appearance parameters or tokens: `{"--ui-hue": "150", "--ui-contrast": "0.2"}` — see [Appearance](sites.md#appearance) |
| `NAVIGATION` | `[]` | Extra sidebar groups — see [Sites](sites.md#navigation-and-the-dashboard) |
| `SEARCH_RESULTS_PER_RESOURCE` | `5` | Records per resource in the command palette |

## Data tables

| Setting | Default | Meaning |
| --- | --- | --- |
| `TABLE_PAGE_SIZE` | `15` | Rows when the client sends no `length` |
| `TABLE_DATETIME_FORMAT` | `None` | Dates and times in tables. `None`: they travel as ISO in the active time zone and are drawn in the reader's language - `26/09/2026 09:51` in French, `09/26/2026, 09:51 AM` in English - while sorting, filters and edited cells keep the ISO value. A strftime format (`"%d.%m.%Y %H:%M"`) fixes the text for every language |
| `TABLE_MAX_PAGE_SIZE` | `500` | Upper bound on `length` |
| `TABLE_ALLOW_UNLIMITED_PAGE_SIZE` | `False` | Whether `length=-1` means "all" |
| `TABLE_COUNT_LIMIT` | `None` | Reserved for estimated counts |

`TABLE_ALLOW_UNLIMITED_PAGE_SIZE` is off by default deliberately.
`length=-1` is the DataTables idiom for "every row", which is convenient
on a small table and a way to dump a large one in a single request.
With it off, `-1` falls back to the default page size.

## Exports

| Setting | Default | Meaning |
| --- | --- | --- |
| `EXPORT_CHUNK_SIZE` | `2000` | Rows fetched per chunk while streaming |
| `EXPORT_MAX_ROWS` | `250_000` | Refuse beyond this instead of timing out |
| `EXPORT_DATE_FORMAT` | `DD/MM/YYYY` | Excel number format |
| `EXPORT_DATETIME_FORMAT` | `DD/MM/YYYY HH:MM` | Excel number format |

## Imports

| Setting | Default | Purpose |
| --- | --- | --- |
| `IMPORT_MAX_ROWS` | `5000` | Rows one file may hold; `Import(max_rows=...)` wins |
| `IMPORT_MAX_FILE_SIZE` | `5 * 1024 * 1024` | Bytes; a larger file is refused before it is read |
| `IMPORT_PREVIEW_ROWS` | `20` | Rows the preview shows as they will be written |

See [Imports](imports.md).

## Autocomplete

| Setting | Default | Meaning |
| --- | --- | --- |
| `AUTOCOMPLETE_PAGE_SIZE` | `25` | Options per page |
| `AUTOCOMPLETE_MIN_INPUT_LENGTH` | `0` | Characters before searching |

## Forms

| Setting | Default | Meaning |
| --- | --- | --- |
| `FORM_DEFAULT_SECTION` | `"general"` | Section for fields that name none |
| `FORM_RELATED_POPUP_WIDTH` | `980` | Related editor popup |
| `FORM_RELATED_POPUP_HEIGHT` | `760` | Related editor popup |
| `FORM_CHOICES_LIMIT` | `200` | Choices embedded in a relation field without an autocomplete |
| `FILE_MAX_SIZE` | `10 * 1024 * 1024` | The largest file, in bytes, a form's file field or the wiki's editor takes: refused in the browser before sending, and by the server ([Files](forms.md#files)) |

## Wiki

| Key | Default | Purpose |
| --- | --- | --- |
| `WIKI_ACCESS` | `None` | Which wikis a user reads: a function `(user, wikis) -> wikis`, or its dotted path, narrowing the queryset it is given. `None`: every wiki for anyone signed in ([Who sees which wiki](wiki.md#who-sees-which-wiki)) |
| `WIKI_PDF_FONTS` | `None` | The TrueType fonts a wiki's PDF is written with, `{"regular", "bold", "italic", "bold_italic", "mono": path}`. `None` looks for DejaVu, Liberation or Arial on the system, then falls back on Latin-1 ([PDF](wiki.md#pdf)) |

## Events

| Setting | Default | Meaning |
| --- | --- | --- |
| `EVENTS_WEBSOCKET_URL` | `"/ws/events/"` | Where the pages open their socket; empty disables it. Never opened when Channels is not installed; set it to `None` if Channels is installed but the site is served over WSGI |
| `EVENTS_BROADCAST_GROUP` | `"generic.broadcast"` | Group every socket joins |
| `EVENTS_RETENTION_DAYS` | `90` | Notification retention; `None` keeps forever |
| `EVENTS_DISPATCH_ON_COMMIT` | `True` | Wait for the transaction to commit |

Leave `EVENTS_DISPATCH_ON_COMMIT` on. With it off, a client can be told
about a row that a later rollback removes, and the only cure is a page
reload.

## Help, licence and changelog

| Setting | Default | Meaning |
| --- | --- | --- |
| `VERSION` | `""` | Shown at the foot of the navigation and on the help page |
| `LICENSE_FILE` | `None` | Where the licence is; `None` looks for `LICENSE`, `LICENSE.md`, `LICENSE.txt`, `LICENCE` at the root of the project |
| `LICENSE_TEXT` | `""` | What the page says when there is no file |
| `CHANGELOG_FILES` | `None` | Paths, or `(label, path)` pairs; `None` looks for `CHANGELOG.md` at the root of the project and of the framework |
| `HELP_LINKS` | `[]` | `[{"label", "url", "icon", "description", "external"}]` |
| `HELP_TEXT` | `""` | A paragraph of the project's own, above the links |

See [UI layer](ui.md#help-licence-and-changelog).

## Planned restarts

| Setting | Default | Meaning |
| --- | --- | --- |
| `MAINTENANCE_REMINDER_SECONDS` | `60` | How long before the hour the second warning goes out |
| `MAINTENANCE_IMMINENT_SECONDS` | `10` | How long before it the last one does |
| `MAINTENANCE_RESTART` | `True` | Whether an announcement that is not a manual operation may restart this server |
| `MAINTENANCE_RESTART_COMMAND` | `None` | What restarting means here: `"systemctl restart desk"`, or a list of arguments |

With `MAINTENANCE_RESTART_COMMAND` unset, the framework uses the
development reloader when it is running and `SIGTERM` otherwise — which
restarts the process only if systemd, Docker or a supervisor is watching
it. `MAINTENANCE_RESTART = False` turns the whole thing into a warning
system: announcements still reach everyone, nothing is ever restarted.
See [Planned restarts](maintenance.md).

## Tasks

| Setting | Default | Meaning |
| --- | --- | --- |
| `SHOW_TASKS` | `None` | Whether the task pages appear; `None` offers them as soon as the project declares a task or `django_celery_beat` is installed |
| `TASK_RECENT_RUNS` | `5` | How many runs the catalogue lists under each task |
| `OPERATION_FALLBACK` | `"thread"` | Where a background operation goes when no Celery worker can be reached: `"thread"` (a thread of the process; the page is answered at once) or `"inline"` (the request waits) |

See [Tasks](tasks.md) and [Operations and reports](operations.md).

## API tokens

| Setting | Default | Meaning |
| --- | --- | --- |
| `API_TOKEN_DEFAULT_DAYS` | `90` | A new token's life, unless its owner chooses |
| `API_TOKEN_MAX_DAYS` | `365` | The longest a token may last; `None` allows tokens that never expire |
| `API_TOKEN_LIMIT_PER_USER` | `10` | Tokens one person may hold at once |

See [The API for scripts](api.md).

## Scheduled mailings

| Setting | Default | Meaning |
| --- | --- | --- |
| `SHOW_MAILINGS` | `True` | The list menu's *Send by e-mail on a schedule*, the Scheduled mailings screen and their dispatcher |
| `MAILING_MAX_ATTACHMENT_SIZE` | `10 * 1024 * 1024` | Bytes; a larger file is not attached, and the mail links the list |

See [Scheduled mailings](mailings.md).

## Signing in

| Setting | Default | Meaning |
| --- | --- | --- |
| `SSO_PROVIDERS` | `[]` | Ways in that are not a password, offered first on the sign-in page: `[{"label", "route"/"url", "icon", "description", "order", "next_param"}]`. The same shape as `site.add_sso_provider()` |
| `SSO_PASSWORD_LOGIN` | `True` | Whether the username and password form is offered at all. `False` takes it away — and is ignored when no provider is declared, because a page with no way in is a locked door rather than a policy |

See [Signing in through somebody else](sso.md).

## The dashboard's hub

| Setting | Default | Meaning |
| --- | --- | --- |
| `SHORTCUTS` | `[]` | Cards at the top of the dashboard: `[{"label", "url"/"route", "icon", "description", "group", "order", "permission", "count", "external"}]`. The same shape as `site.add_shortcut()`, and the two add up |

See [the hub](sites.md#the-hub).

## People

| Setting | Default | Meaning |
| --- | --- | --- |
| `SHOW_PEOPLE` | `True` | Whether the users, groups and permissions screens appear. They obey the ordinary `auth` permissions, so nobody without them sees a thing. Registering the user model yourself also takes them off |
| `SHOW_MESSAGES` | `True` | Whether the *Messages* screen appears, where whoever holds `generic.add_message` writes to some people or to everyone ([Messages](events.md#messages)). Nobody without the permission sees it |

See [People](people.md). The passwords those screens set are checked
against the project's own `AUTH_PASSWORD_VALIDATORS`; a project that
declares none accepts anything.

## History

| Setting | Default | Meaning |
| --- | --- | --- |
| `HISTORY` | `True` | Keep a version of every record of every registered model. `False` records nothing and removes the *Changes* page |
| `HISTORY_RETENTION_DAYS` | `None` | Keep everything. A number is what `generic.history.prune()` deletes beyond; nothing prunes on its own |

See [History](history.md).

## Logs

| Setting | Default | Meaning |
| --- | --- | --- |
| `ERROR_MAIL_INTERVAL` | `600` | Seconds during which the same error is mailed to `ADMINS` only once, by `generic.logs.ErrorMailHandler`; the next mail says how many were held back. `0` mails every one |

See [Logs and error reports](logging.md).

## Django settings that matter

| Setting | Why |
| --- | --- |
| `CHANNEL_LAYERS` | Required for events; Redis in production |
| `MIDDLEWARE` | `generic.middleware.CurrentUserMiddleware`, after the authentication, is what the history records as the *who* |
| `USE_TZ` | Date filters compare against day boundaries in the active timezone |
| `TIME_ZONE` | Which day a timestamp belongs to |
| `REST_FRAMEWORK` | Authentication and permission defaults |
| `MAILERS` | The `default` mailer carries every e-mail the framework sends; `EMAIL_BACKEND` and `EMAIL_*` before Django 6.1 — see [Mail](installation.md#mail) |
| `DEFAULT_FROM_EMAIL` | The sender of those e-mails |
| `MEDIA_ROOT` | Where uploaded files are written - a model's file fields, the wiki's images. Empty, `check` warns `generic.W010`. `MEDIA_URL` is not needed: files are served through each record's endpoint ([Files](forms.md#files)) |

The framework does **not** require any particular DRF pagination,
filter-backend or renderer configuration: the viewsets declare their own
explicitly, so a project-wide DRF setting cannot change table behaviour
by accident.

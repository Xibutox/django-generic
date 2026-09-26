# Installation

From nothing to a working screen, in a new project or an existing one.
Every block below is what `scripts/smoke_install.py` writes into a fresh
project and then opens page by page, so this guide and the package are
checked against each other.

## Requirements

| | Version |
| --- | --- |
| Python | 3.10 or later |
| Django | 5.2 (LTS) or later |
| Django REST framework | 3.16 or later |
| Database | any Django supports; SQLite to try, PostgreSQL in production |
| Optional | Redis - live updates across processes, Celery; an ASGI server - Daphne - for live updates |

## 1. Install the package

```bash
pip install django-generic
```

That is the core: Django and DRF, nothing else. The rest comes as
extras, installed the same way:

```bash
pip install "django-generic[export,events,tasks,wiki,postgres]"
```

| Extra | Adds | For |
| --- | --- | --- |
| `export` | openpyxl | the Excel export (CSV needs nothing) |
| `events` | Channels, channels-redis, Daphne | live updates, notifications, watches over WebSocket |
| `tasks` | Celery, redis | declared tasks run in the background |
| `beat` | django-celery-beat | schedules managed from the Tasks pages |
| `wiki` | nh3 | the wiki (`generic.wiki`) |
| `postgres` | psycopg | PostgreSQL |
| `dev` | pytest, linters, Debug Toolbar | working on the framework itself |

Distributed as a file or from a private index, the name is the same:

```bash
pip install django_generic-1.0.0-py3-none-any.whl
pip install --index-url https://pypi.example.com/simple/ django-generic
```

## 2. Settings

Added to the project's settings - a new `django-admin startproject` or
one that has been running for years. Comments mark what is the
framework's; the rest is Django's usual.

```python
INSTALLED_APPS = [
    "django.contrib.admin",          # optional: it keeps working beside
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",                # the framework's
    "generic",                       # the framework's
    # "generic.wiki",                # optional: the wiki
    "myapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",      # several languages
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "generic.middleware.UserLanguageMiddleware",     # after the auth
    "generic.middleware.CurrentUserMiddleware",      # after the auth
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",   # required
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# The pages call the API with the session they are signed in by.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# The site's own sign-in page - or the project's, if it has one.
LOGIN_URL = "site:login"
LOGIN_REDIRECT_URL = "/"

# The languages the interface offers: English and French are shipped.
LANGUAGES = [("en", "English"), ("fr", "French")]
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Everything has a default; docs/settings.md lists them.
GENERIC = {
    "SITE_TITLE": "My application",
    "SITE_ICON": "apps",
}
```

What each framework line is for:

- `rest_framework` and `generic` - the framework and the API it runs on.
- The **`request` context processor** - every page draws its frame
  (navigation, user, language) from the request.
- `UserLanguageMiddleware` - a user's saved language wins over the
  browser's. `CurrentUserMiddleware` - the history records who made each
  change. Both read the user, so both come after the authentication.
- **Session authentication** for DRF - DRF's own default includes it; a
  project that lists its own classes must keep it.
- `LOGIN_URL` - the pages send signed-out readers to the site's sign-in
  page themselves; this is for the project's other views.

## 3. URLs

```python
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from generic.sites import site

urlpatterns = [
    path("admin/", admin.site.urls),                  # optional
    # The browser side's translations.
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic"]),
        name="javascript-catalog",
    ),
    # Notifications, preferences, watches, saved views.
    path("api/generic/", include("generic.urls", namespace="generic")),
    # path("wiki/", include("generic.wiki.urls")),   # with generic.wiki
    # Every page and endpoint the resources generate: last.
    path("", site.urls),
]
```

`site.urls` takes the root: the dashboard at `/`, each model at
`/<app>/<model>/`, the sign-in page at `/login/`. **In a project whose
root is already taken**, mount it under a prefix - every address the
framework builds follows it:

```python
path("app/", site.urls),       # dashboard at /app/, sign-in at /app/login/
```

Keep the namespace `site`: the framework's own screens are registered on
that site.

## 4. Database, static files, first user

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

`runserver` serves the static files. In production, collect them for the
web server, as for any Django project:

```bash
python manage.py collectstatic
```

The package ships its own libraries - DataTables, Select2, Alpine,
ECharts, Quill, the icon font: no CDN, no Node, no build step.

## 5. Check the wiring

```bash
python manage.py check
```

Beside Django's own, the framework checks how it was plugged in and
names what is missing, with the line to write:

| Id | Means |
| --- | --- |
| `generic.E001` | The `request` context processor is missing |
| `generic.E002` | A framework middleware runs before the authentication |
| `generic.E003` | DRF does not accept session authentication |
| `generic.E004` | `site.urls` is not in the URLconf |
| `generic.E005` | `generic.wiki` is installed without the `wiki` extra |
| `generic.W001` | A framework middleware is missing |
| `generic.W002` | Several languages but no `LocaleMiddleware` |
| `generic.W003` | `generic.urls` is not mounted |
| `generic.W004` | `LOGIN_URL` leads to a page nobody serves |
| `generic.W005` | Channels is installed but nothing serves ASGI |
| `generic.I001` | The JavaScript catalog is not mounted |

A project that knows why silences one with `SILENCED_SYSTEM_CHECKS`.

## 6. The first screen

In any installed app, a `resources.py` - imported at start-up, the way
`admin.py` is:

```python
# myapp/resources.py
from generic.sites import auto

from myapp.models import Book

auto(Book)
```

Sign in at `/`, open *Books*: the list with its filters, search and
exports, the forms, a page per book. One line worked all of it out from
the model; declaring it by hand gives full control:

```python
from generic.sites import ModelResource, register


@register(Book)
class BookResource(ModelResource):
    icon = "menu_book"
    list_display = ("title", "author", "pages", "status")
    search_fields = ("title", "author")
```

Who sees what follows the model permissions: a user needs
`myapp.view_book` to see the books, `add_book` to add one, and so on.

From here: [Sites and resources](sites.md) for everything a resource
declares, [Pages from the model](auto.md), [Rows from
elsewhere](data.md), [Pages of a resource's own](pages.md).

## 7. Optional parts

### Live updates

Tables that refresh when a row changes, notifications, watches and
announced restarts travel over a WebSocket. Install the `events` extra,
then:

```python
INSTALLED_APPS = [
    "daphne",            # first: runserver then serves ASGI
    ...,
    "channels",
    "rest_framework",
    "generic",
    ...,
]

ASGI_APPLICATION = "mysite.asgi.application"

# One process: in memory. Several, or production: Redis.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}
# CHANNEL_LAYERS = {"default": {
#     "BACKEND": "channels_redis.core.RedisChannelLayer",
#     "CONFIG": {"hosts": ["redis://localhost:6379/0"]}}}
```

```python
# mysite/asgi.py
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
django_asgi_application = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import (  # noqa: E402
    AllowedHostsOriginValidator,
)

from generic.events.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_application,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
```

Served by an ASGI server - `runserver` with `daphne` installed, or
`daphne mysite.asgi:application` in production. Without the extra,
nothing changes but that: the pages do not open a socket, and a table
refreshes when it is reloaded. See [Events](events.md).

### The wiki

The `wiki` extra, `"generic.wiki"` in `INSTALLED_APPS`, and its URLs:
`path("wiki/", include("generic.wiki.urls"))` before `site.urls`. See
[The wiki](wiki.md).

### Background tasks

The `tasks` extra and a Celery app; `beat` for schedules managed from
the pages. See [Tasks](tasks.md).

### Translations

English and French are shipped, for the pages and the JavaScript. A
project narrows `LANGUAGES` to what it offers - the frame builds its
language menu from it - and adds its own catalogs with `LOCALE_PATHS`.
See [Translation](i18n.md).

## 8. In an existing project

- **The Django admin keeps working** beside the site; the two share the
  users, groups and permissions.
- **A custom user model** is supported: the People screens read
  `USERNAME_FIELD` and show only the fields the model has.
- **Existing views and URLs** are untouched: mount the site under a
  prefix if the root is taken (above).
- **Existing templates** are untouched: the framework's live under
  `generic/`, and a project overrides any of them the usual way, from
  its own `templates/generic/...`.
- **The API** lives under the site's `api/` - `api/<app>/<model>/` - and
  follows DRF's settings for authentication and permissions only: the
  framework's viewsets bring their own renderers, pagination and
  filters, so nothing the project set up for its own API changes them.

## 9. Deploying

Production is a Django deployment like any other, served over ASGI when
live updates are on: `DEBUG = False`, `collectstatic`, `check --deploy`,
a database and - for several processes - Redis. The repository's
example comes with both modes ready, settings and Docker stacks: see
[Development and production](deployment.md).

## Trying it without a project

The repository's example is a whole application built on the framework,
with demo data:

```bash
git clone <repository> django-generic && cd django-generic
pip install -e ".[export,events,tasks,wiki,dev]"
python manage.py migrate
python manage.py seed_example
python manage.py runserver
```

Sign in at <http://127.0.0.1:8000/> as `admin` / `demo`. See [The
example project](example.md).

# Installation

From nothing to a working screen, in a new project or an existing one:
the package built from this repository, installed from a file - it is
not on PyPI - then plugged into the project's settings and URLs.

The first sections are the two walkthroughs; the ones from
[Settings](#settings) on describe each piece they use. The settings and
URLs are what `scripts/smoke_install.py` writes into a fresh project
and then opens page by page, so this guide and the package are checked
against each other.

## Requirements

| | Version |
| --- | --- |
| Python | 3.10 or later |
| Django | 5.2 (LTS) or later |
| Django REST framework | 3.16 or later |
| Database | any Django supports; SQLite to try, PostgreSQL in production |
| Optional | Redis - live updates across processes, Celery; an ASGI server - Daphne - for live updates |

## Get the package

django-generic is not published on PyPI: a project installs it from a
**wheel** built from this repository, one file holding the whole
framework - code, templates, static files, translations.

> **Never `pip install django-generic` by name.** That name on PyPI
> belongs to an unrelated project, and pip would install it. Every
> command below names the wheel by its path.

Built once per version, from a checkout:

```bash
git clone https://github.com/Xibutox/django-generic.git
cd django-generic
git checkout v1.1.0          # the version to install; `git tag` lists them
python -m pip wheel --no-deps --wheel-dir dist .
```

That leaves `dist/django_generic-1.1.0-py3-none-any.whl`. Building it
needs pip alone (and the network, for the build's own setuptools). The
same file installs everywhere: a virtual environment, a Docker image, a
server that cannot reach the repository.

A project keeps its copy of the wheel in a `vendor/` folder, committed
with the rest, and names it in `requirements.txt`. Whoever clones the
project then installs the same framework with `pip install -r
requirements.txt` and nothing else.

## A new project, from nothing

Beside the checkout of the framework, a new folder and its own virtual
environment:

```bash
mkdir mysite && cd mysite
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

mkdir vendor
cp ../django-generic/dist/django_generic-1.1.0-py3-none-any.whl vendor/
```

`requirements.txt`, at the project's root - the wheel by its path,
with the [extras](#extras) wanted in brackets:

```text
./vendor/django_generic-1.1.0-py3-none-any.whl[export]
```

```bash
pip install -r requirements.txt      # from the project's root: the path is read from there
django-admin startproject mysite .
python manage.py startapp library
```

pip brings Django and Django REST framework with it. Then, in the new
project:

1. **Settings** - in `mysite/settings.py`, as [Settings](#settings)
   shows: `"rest_framework"`, `"generic"` and `"library"` in
   `INSTALLED_APPS`; `LocaleMiddleware` and the framework's two
   middlewares in `MIDDLEWARE`; and, at the end of the file,
   `REST_FRAMEWORK`, `LOGIN_URL`, `LOGIN_REDIRECT_URL`, `LANGUAGES`,
   `STATIC_ROOT` and `GENERIC`. `startproject`'s `TEMPLATES` already
   has the `request` context processor.
2. **URLs** - `mysite/urls.py` becomes the block of [URLs](#urls).
3. **A model** and its screen:

   ```python
   # library/models.py
   from django.db import models


   class Book(models.Model):
       title = models.CharField(max_length=200)
       author = models.CharField(max_length=200)
       pages = models.PositiveIntegerField(default=0)

       def __str__(self):
           return self.title
   ```

   ```python
   # library/resources.py
   from generic.sites import auto

   from library.models import Book

   auto(Book)
   ```

4. **The database, the checks, a first user:**

   ```bash
   python manage.py makemigrations library
   python manage.py migrate
   python manage.py check               # names anything missing
   python manage.py createsuperuser
   python manage.py runserver
   ```

`check` answers *no issues* - or, on Django 6.1 and later, warns that
`MAILERS` is not set (`generic.W006`) until the project says how it
sends mail ([Mail](#mail)).

Sign in at <http://127.0.0.1:8000/>: the dashboard, and *Books* in the
navigation - its list, its forms, a page per book.

## An existing project

Nothing the project already has is replaced: the framework adds apps,
two middlewares, a few URLs and its own tables.

1. **Versions.** Python 3.10, Django 5.2 and Django REST framework 3.16
   or later. Copy the wheel into `vendor/` and add its line to
   `requirements.txt` as above, then ask pip what it would change
   before it changes anything:

   ```bash
   pip install --dry-run -r requirements.txt
   ```

   It lists what it would install. If that includes Django, or pip
   reports a conflict with the project's own requirement on Django,
   move the project to Django 5.2 on its own first, with Django's
   release notes - not as a side effect of this.

2. **Install:** `pip install -r requirements.txt`, from the project's
   root.

   A project whose dependencies live in its `pyproject.toml` lists the
   framework there by name, with its extras -
   `"django-generic[export]>=1.1,<2"` - and keeps the wheel's path in
   `requirements.txt`, installed in the same command as the project
   itself:

   ```text
   ./vendor/django_generic-1.1.0-py3-none-any.whl
   -e .
   ```

   pip takes the wheel for that name, with the extras `pyproject.toml`
   asks for. Without the wheel, the requirement fails rather than
   bringing in the unrelated package of the same name.

3. **Settings** - *added* to what is there, as [Settings](#settings)
   describes each line:
   - `"rest_framework"` (if it is not there yet) and `"generic"` in
     `INSTALLED_APPS`;
   - `generic.middleware.UserLanguageMiddleware` and
     `generic.middleware.CurrentUserMiddleware` in `MIDDLEWARE`, after
     `AuthenticationMiddleware`;
   - the languages: `LocaleMiddleware` if the site speaks several, or
     else `LANGUAGES` narrowed to the one it speaks -
     `[("en", "English")]`. Unset, Django's `LANGUAGES` lists every
     language it knows, and the language menu offers them all;
   - the `request` context processor in `TEMPLATES`, if it is missing;
   - in `REST_FRAMEWORK`, the project's own classes stay:
     `SessionAuthentication` is added to them if it is not among them,
     since the pages call the API with the session they are signed in
     by;
   - `LOGIN_URL`: kept if the project has its own sign-in page, else
     `"site:login"`;
   - `STATIC_ROOT`, if production collects the static files and it is
     not set; `GENERIC` for the title and the icon.
4. **URLs** - `jsi18n/` and `api/generic/` as in [URLs](#urls), and
   the site **under a prefix** when the root is already taken:
   `path("app/", site.urls)`, last. Every address the framework builds
   follows it.
5. **The database:** `python manage.py migrate` creates the framework's
   own tables - history, notifications, preferences, saved views - and
   touches none of the project's.
6. **The checks:** `python manage.py check` names whatever is still
   missing, with the line to write ([Check the wiring](#check-the-wiring)).
7. **A first screen** - a `resources.py` in one of the project's apps,
   for a model it already has:

   ```python
   # shop/resources.py
   from generic.sites import auto

   from shop.models import Product

   auto(Product)
   ```

   A superuser sees it at once under the prefix (`/app/`); everyone
   else according to the model permissions the project already
   grants (`shop.view_product` to see the products, and so on).

What keeps working beside it:

- **The Django admin**, which shares the users, groups and permissions.
- **A custom user model**: the People screens read `USERNAME_FIELD` and
  show only the fields the model has.
- **Existing views, URLs and templates**: the framework's templates live
  under `generic/`, and a project overrides any of them the usual way,
  from its own `templates/generic/...`.
- **The project's own API**: the framework's endpoints live under the
  site's `api/` - `api/<app>/<model>/` - and follow DRF's settings for
  authentication and permissions only. Its viewsets bring their own
  renderers, pagination and filters, so nothing the project set up for
  its own API changes them.

## Extras

The wheel alone is the core: Django and DRF, nothing else. The optional
parts come as extras, named in brackets after the wheel's path - in
`requirements.txt`, or in `pyproject.toml` after the name:

```text
./vendor/django_generic-1.1.0-py3-none-any.whl[export,events,tasks,wiki,postgres]
```

and installed again with `pip install -r requirements.txt`.

| Extra | Adds | For |
| --- | --- | --- |
| `export` | openpyxl | the Excel export (CSV needs nothing) |
| `import` | openpyxl, defusedxml | Excel imports, read safely (CSV needs nothing) |
| `fsm` | django-fsm-2 | state machines: a model's transitions as buttons and bulk actions, see [State machines](transitions.md) |
| `api` | django-rest-knox, drf-spectacular, its sidecar | personal API tokens (`generic.tokens`) and the OpenAPI description (`generic.openapi`), see [The API for scripts](api.md) |
| `events` | Channels, channels-redis, Daphne | live updates, notifications, watches over WebSocket |
| `tasks` | Celery, redis | declared tasks run in the background |
| `beat` | django-celery-beat | schedules managed from the Tasks pages |
| `wiki` | nh3 | the wiki (`generic.wiki`) |
| `postgres` | psycopg | PostgreSQL (and `generic.search`'s trigram indexes there) |
| `dev` | pytest, linters, Debug Toolbar | working on the framework itself |

## Working on the framework and a project together

To change the framework while a project uses it, install the checkout
itself, editable, in place of the wheel:

```bash
pip install -e "../django-generic[export]"
```

A change to the framework then shows in the project at the next
restart, with no wheel to rebuild. It depends on the checkout's
place on this machine: keep the wheel in `requirements.txt` for
everyone else, Docker and production.

## Updating

A new version is a new wheel:

```bash
cd ../django-generic
git fetch --tags && git checkout v1.2.0
python -m pip wheel --no-deps --wheel-dir dist .
cd ../mysite
rm vendor/django_generic-*.whl
cp ../django-generic/dist/django_generic-1.2.0-py3-none-any.whl vendor/
```

Then the new file name in `requirements.txt`, and:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic       # in production
python manage.py check
```

What changed, and what to do about it, is in the framework's
changelog - also on every application's *Help › What changed* page.

## In Docker

The wheel travels with the project, so the image installs it with no
access to the framework's repository - the requirements and `vendor/`
copied before the source, to keep the layer when only the code
changes:

```dockerfile
COPY requirements.txt ./
COPY vendor/ ./vendor/
RUN pip install -r requirements.txt
COPY . .
```

A `requirements.txt` ending in `-e .` installs the project too: copy
its `pyproject.toml` and package before the `RUN` as well.

## Settings

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
    # "generic.search",              # optional: searches ignore accents
    # "knox", "generic.tokens",      # optional: API tokens (docs/api.md)
    "library",                       # the project's own apps
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

# Where uploaded files are written (file fields, the wiki's images). No
# MEDIA_URL: each file is downloaded through its record's endpoint.
MEDIA_ROOT = BASE_DIR / "media"

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
- `MEDIA_ROOT` - where a file field writes its files, backed up with
  the database; nothing serves it as a folder - no `MEDIA_URL`, no
  proxy location - since every file is downloaded through its record's
  endpoint, permission-checked ([Files](forms.md#files)).

## URLs

```python
from django.contrib import admin
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

## Database, static files, first user

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

## Check the wiring

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
| `generic.W006` | Django 6.1 or later, and no `MAILERS` ([Mail](#mail)) |
| `generic.W009` | `check --deploy` only: `ADMINS` is empty, so errors are mailed to nobody ([Logs](#logs-and-error-mails)) |
| `generic.W010` | A registered model has a file field - or the wiki is installed - and `MEDIA_ROOT` is empty: files would be written relative to the working directory ([Files](forms.md#files)) |
| `generic.I001` | The JavaScript catalog is not mounted |

A project that knows why silences one with `SILENCED_SYSTEM_CHECKS`.

## The first screen

In any installed app, a `resources.py` - imported at start-up, the way
`admin.py` is:

```python
# library/resources.py
from generic.sites import auto

from library.models import Book

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
    list_display = ("title", "author", "pages")
    search_fields = ("title", "author")
```

Who sees what follows the model permissions: a user needs
`library.view_book` to see the books, `add_book` to add one, and so on.

From here: [Sites and resources](sites.md) for everything a resource
declares, [Pages from the model](auto.md), [Rows from
elsewhere](data.md), [Pages of a resource's own](pages.md).

## Optional parts

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
#     # Above the 5 seconds channels-redis waits (see Events).
#     "CONFIG": {"hosts": [{"address": "redis://localhost:6379/0",
#                           "socket_timeout": 15}]}}}
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

The `tasks` extra and a Celery app, imported by the project package's
`__init__.py` as Celery's guide for Django does - otherwise the web
server never loads it, and a task started from a page runs in the
request instead of going to the worker. `beat` for schedules managed
from the pages. See [Tasks](tasks.md).

### Mail

Whoever asked to be told by e-mail - on their account, on a watch, as
a task's audience, in a message - is sent one through Django's default
mailer: one mail per address, from `DEFAULT_FROM_EMAIL`, its link made
absolute with `GENERIC["SITE_URL"]`. From Django 6.1 the mailer is
`MAILERS`:

```python
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {"host": "smtp.example.com", "use_tls": True},
    }
}
```

Before 6.1 it is `EMAIL_BACKEND` and the `EMAIL_*` settings, which 6.1
deprecates and refuses beside `MAILERS`. A settings module serving
both, like the example's, switches on `django.VERSION` -
`mail_settings()` in `example_project/settings/base.py`. On 6.1 and
later, `check` warns without `MAILERS` (`generic.W006`): Django 7.0
sends nothing without it, and a mail that cannot leave is logged, never
raised - the people who asked for it would simply stop receiving it.

### Logs and error mails

A log file beside standard output, rotated and shared by every process,
and every unexpected error mailed with its traceback to `ADMINS`:

```python
from generic.logs import admins, logging_config

ADMINS = admins(["ops@example.com"])
LOGGING = logging_config(file=BASE_DIR / "logs" / "app.log")
CELERY_WORKER_HIJACK_ROOT_LOGGER = False       # with the tasks extra
```

See [Logs and error reports](logging.md).

### Translations

English and French are shipped, for the pages and the JavaScript. A
project narrows `LANGUAGES` to what it offers - the frame builds its
language menu from it - and adds its own catalogs with `LOCALE_PATHS`.
See [Translation](i18n.md).

## Deploying

Production is a Django deployment like any other, served over ASGI when
live updates are on: `DEBUG = False`, `collectstatic`, `check --deploy`,
a database and - for several processes - Redis. The repository's
example comes with both modes ready, settings and Docker stacks: see
[Development and production](deployment.md).

## Trying it without a project

The repository's example is a whole application built on the framework,
with demo data:

```bash
git clone https://github.com/Xibutox/django-generic.git && cd django-generic
pip install -e ".[export,events,tasks,wiki,dev]"
python manage.py migrate
python manage.py seed_example
python manage.py runserver
```

Sign in at <http://127.0.0.1:8000/> as `admin` / `demo`. See [The
example project](example.md).

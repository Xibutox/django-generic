# The minimal example

The least a Django project needs to run django-generic: one settings
file, one URL module, one app with one model, and its screens in one
line - plus the wiki, and signing in with Microsoft through
django-allauth once an app registration is given. No real time, no Celery, no API tokens, no
production settings - for all of those, see the full example,
`example/` and `example_project/` ([the example](../docs/example.md)).

```
minimal/
├── manage.py
├── mysite/
│   ├── settings.py     startproject's, trimmed; the framework's lines marked
│   ├── urls.py         jsi18n/, api/generic/, wiki/, accounts/, the site last
│   └── wsgi.py
├── Dockerfile          the same, in a container (optional)
├── compose.yaml
└── library/
    ├── models.py       Book: a title, an author, pages, a status
    ├── resources.py    auto(Book) - the whole interface
    └── migrations/
```

## Run it

From a checkout of the repository, the framework with the `wiki`
extra - Django and Django REST framework come with the framework, the
extra adds nh3, which cleans the wiki's pages:

```bash
pip install -e ".[wiki]"
cd minimal
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Sign in at <http://127.0.0.1:8000/>: the dashboard, and *Books* in the
navigation - the list with its search, filters and export, the form, a
page per book, the REST endpoint at `/api/library/book/` - and *Wiki*,
at <http://127.0.0.1:8000/wiki/>: write its first page, with its
editor, its menu, its history and its images ([The wiki](../docs/wiki.md)).

### In Docker

From the repository's root - the image installs the framework and its
`wiki` extra from the checkout, then the example, and runs `migrate`
and `runserver`:

```bash
docker compose -f minimal/compose.yaml up --build
docker compose -f minimal/compose.yaml exec web python manage.py createsuperuser
```

The same pages at <http://localhost:8000/>. The database and the wiki's
images are in the `data` volume (`DJANGO_DB_PATH=/data/db.sqlite3`,
`DJANGO_MEDIA_ROOT=/data/media`), so they outlive the container; `down -v` starts over. Like the example itself this is for
trying it locally: the production stack, with Postgres, Redis and a
proxy in front, is [`docker/`](../docker/) and
[Deployment](../docs/deployment.md).

### Signing in with Microsoft

The sign-in page can lead with a *Microsoft* button, the password form
folded underneath ([Signing in through somebody else](../docs/sso.md)).
django-allauth speaks to Microsoft; the framework only draws the
button. It is off until the example is given an app registration, so
without one nothing changes and nothing more is installed.

1. **Register an app** in the [Microsoft Entra admin
   center](https://entra.microsoft.com/): *Identity* > *Applications* >
   *App registrations* > *New registration*.
   - *Supported account types*: this organisation's accounts only, for
     a work application.
   - *Redirect URI*: platform **Web**,
     `http://localhost:8000/accounts/microsoft/login/callback/`.
     Microsoft accepts `http` only for `localhost`, so open the example
     at `localhost`, not `127.0.0.1`; a deployed site registers its own
     `https://` address with the same path.
2. On the registration's *Overview*, copy the *Application (client) ID*
   and the *Directory (tenant) ID*.
3. Under *Certificates & secrets*, *New client secret*: copy its
   *Value* (shown once).
4. *API permissions* already has Microsoft Graph's `User.Read`, which
   is all allauth asks for: the name and the address.

Then, from a checkout:

```bash
pip install -e ".[wiki]" "django-allauth[socialaccount]"
cd minimal
export MICROSOFT_CLIENT_ID=<application id>
export MICROSOFT_CLIENT_SECRET=<secret value>
export MICROSOFT_TENANT_ID=<directory id>
python manage.py migrate            # allauth's tables
python manage.py runserver
```

or in Docker, the image already has allauth, with the three values in
a `minimal/.env` file - beside `compose.yaml`, never committed - or the
environment:

```bash
docker compose -f minimal/compose.yaml up --build
```

Open <http://localhost:8000/login/>: *Microsoft* first, then back here
signed in. `MICROSOFT_TENANT_ID` left out means `organizations`, any
work or school account; `common` adds personal Microsoft accounts.

The first sign-in creates the account, with no permissions: it sees
the dashboard and nothing in it until a superuser gives it a group, on
the *People* pages. Its name and address are Microsoft's, shown
read-only on its account page. The password form still works, for the
superuser made with `createsuperuser`.

What turns it on is the `if MICROSOFT_CLIENT_ID:` block at the end of
`mysite/settings.py` - allauth's apps, its middleware and backend, the
registration, and `GENERIC["SSO_PROVIDERS"]`, the button - and allauth's
URLs under `accounts/` in `mysite/urls.py`. A project that always signs
in with Microsoft writes the same lines without the `if`.

### Checks

`python manage.py check` answers *no issues*: it is what names a
missing line when the wiring is copied into another project.

## What each piece is for

- **`mysite/settings.py`** - `rest_framework`, `generic` and
  `generic.wiki` in `INSTALLED_APPS`; the framework's two middlewares after the
  authentication; the `request` context processor; session
  authentication for DRF, since the pages call the API as the signed-in
  user; `LOGIN_URL = "site:login"`; `MEDIA_ROOT`, where the wiki's
  images are written (`media/` beside `manage.py`, or
  `DJANGO_MEDIA_ROOT`) - served by the wiki itself, so no `MEDIA_URL`. `GENERIC["EVENTS_WEBSOCKET_URL"] =
  None` says there is no live updates, so the pages open no WebSocket
  even where Channels happens to be installed. Mail goes to the
  console, through `MAILERS` on Django 6.1 and later, `EMAIL_BACKEND`
  before.
- **`mysite/urls.py`** - the browser side's strings (`jsi18n/`), the
  framework's own endpoints (`api/generic/`, where the wiki's editor
  uploads its images), the wiki (`wiki/`), and `site.urls` last: the
  dashboard, sign-in and account pages, every resource's pages and API.
- **`library/resources.py`** - `auto(Book)` works the columns, the
  search, the tags and the form out from the model
  ([Pages from the model](../docs/auto.md)). A `ModelResource` says them
  by hand ([Sites and resources](../docs/sites.md)).

The wiki's permissions - superusers write, everyone signed in reads;
give a group `generic_wiki.add_wikipage`, `change_wikipage` and
`delete_wikipage` for other editors - are in [The wiki](../docs/wiki.md).
Without it, drop `generic.wiki` from `INSTALLED_APPS`, its line from
`urls.py`, and `MEDIA_ROOT`: `pip install -e .` is then enough.

The next steps - a second language, the admin, file uploads, live
updates, production - are in [Installation](../docs/installation.md)
and the full example.

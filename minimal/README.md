# The minimal example

The least a Django project needs to run django-generic: one settings
file, one URL module, one app with one model, and its screens in one
line. No real time, no Celery, no wiki, no API tokens, no Docker, no
production settings - for all of those, see the full example,
`example/` and `example_project/` ([the example](../docs/example.md)).

```
minimal/
├── manage.py
├── mysite/
│   ├── settings.py     startproject's, trimmed; the framework's lines marked
│   ├── urls.py         jsi18n/, api/generic/, then the site, last
│   └── wsgi.py
└── library/
    ├── models.py       Book: a title, an author, pages, a status
    ├── resources.py    auto(Book) - the whole interface
    └── migrations/
```

## Run it

From a checkout of the repository, the framework alone - Django and
Django REST framework come with it, no extra is needed:

```bash
pip install -e .
cd minimal
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Sign in at <http://127.0.0.1:8000/>: the dashboard, and *Books* in the
navigation - the list with its search, filters and export, the form, a
page per book, the REST endpoint at `/api/library/book/`.

`python manage.py check` answers *no issues*: it is what names a
missing line when the wiring is copied into another project.

## What each piece is for

- **`mysite/settings.py`** - `rest_framework` and `generic` in
  `INSTALLED_APPS`; the framework's two middlewares after the
  authentication; the `request` context processor; session
  authentication for DRF, since the pages call the API as the signed-in
  user; `LOGIN_URL = "site:login"`. `GENERIC["EVENTS_WEBSOCKET_URL"] =
  None` says there is no live updates, so the pages open no WebSocket
  even where Channels happens to be installed.
- **`mysite/urls.py`** - the browser side's strings (`jsi18n/`), the
  framework's own endpoints (`api/generic/`), and `site.urls` last: the
  dashboard, sign-in and account pages, every resource's pages and API.
- **`library/resources.py`** - `auto(Book)` works the columns, the
  search, the tags and the form out from the model
  ([Pages from the model](../docs/auto.md)). A `ModelResource` says them
  by hand ([Sites and resources](../docs/sites.md)).

The next steps - a second language, the admin, file uploads, the wiki,
live updates, production - are in [Installation](../docs/installation.md)
and the full example.

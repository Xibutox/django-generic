"""Plug the installed django-generic into a brand-new project, and try it.

What a user does on the first day, done by a script: a fresh Django
project, one app with one model, the framework wired in exactly as
docs/installation.md says - then the migrations, the static files
collected as production collects them, and every kind of page and
endpoint opened, signed in and signed out, in English and in French.

Run it against the package as it will be installed, not the checkout::

    python -m venv /tmp/try && /tmp/try/bin/pip install dist/*.whl
    /tmp/try/bin/python scripts/smoke_install.py

It imports nothing from the repository: whatever it finds is what the
wheel carries. It exits non-zero, naming what failed, when anything
does.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path

SETTINGS = """
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "smoke-test-only"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "generic",
    "library",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "generic.middleware.UserLanguageMiddleware",
    "generic.middleware.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mysite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
LANGUAGES = [("en", "English"), ("fr", "French")]
USE_I18N = True
USE_TZ = True
TIME_ZONE = "UTC"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# As production serves them: hashed names, and a build that fails on a
# file referencing another that is not there.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        )
    },
}

LOGIN_URL = "site:login"
LOGIN_REDIRECT_URL = "/"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

GENERIC = {"SITE_TITLE": "My library"}
"""

URLS = """
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

from generic.sites import site

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "jsi18n/",
        JavaScriptCatalog.as_view(packages=["generic"]),
        name="javascript-catalog",
    ),
    path("api/generic/", include("generic.urls", namespace="generic")),
    path("{prefix}", site.urls),
]
"""

MODELS = """
from django.db import models


class Book(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        LENT = "lent", "Lent"

    title = models.CharField("title", max_length=200)
    author = models.CharField("author", max_length=120)
    pages = models.PositiveIntegerField("pages", default=0)
    published_on = models.DateField("published on", null=True, blank=True)
    status = models.CharField(
        "status", max_length=20, choices=Status.choices,
        default=Status.AVAILABLE,
    )

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title
"""

RESOURCES = """
from generic.sites import ModelResource, page, register

from library.models import Book


@register(Book)
class BookResource(ModelResource):
    icon = "menu_book"
    list_display = ("title", "author", "pages", "published_on", "status")
    search_fields = ("title", "author")

    @page(title="Shelf", icon="shelves", template="library/shelf.html")
    def shelf(self, request):
        return {"books": self.get_queryset(request)}
"""

SHELF = """
{% extends "generic/resource/page.html" %}
{% block page_content %}
  <section class="card">
    {% for book in books %}
      <p class="shelf-book">{{ book.title }}</p>
    {% endfor %}
  </section>
{% endblock %}
"""


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def build_project(root: Path, prefix: str) -> None:
    write(root, "mysite/__init__.py", "")
    write(root, "mysite/settings.py", SETTINGS)
    write(root, "mysite/urls.py", URLS.replace("{prefix}", prefix))
    write(root, "library/__init__.py", "")
    write(root, "library/models.py", MODELS)
    write(root, "library/resources.py", RESOURCES)
    write(root, "library/migrations/__init__.py", "")
    write(root, "library/templates/library/shelf.html", SHELF)


class Smoke:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passed = 0

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
            print(f"  ok    {label}")
        else:
            self.failures.append(label)
            print(f"  FAIL  {label}{' - ' + detail if detail else ''}")

    def page(self, client, url: str, status: int = 200, **extra) -> object:
        response = client.get(url, **extra)
        self.check(
            f"GET {url} -> {status}",
            response.status_code == status,
            f"got {response.status_code}",
        )

        return response


def run(root: Path, prefix: str) -> int:
    sys.path.insert(0, str(root))
    os.environ["DJANGO_SETTINGS_MODULE"] = "mysite.settings"

    import django

    django.setup()

    from django.contrib.auth import get_user_model
    from django.contrib.staticfiles import finders
    from django.core.checks import ERROR, run_checks
    from django.core.management import call_command
    from django.test import Client

    import generic

    def site(url: str) -> str:
        """An address of the site, under the prefix it is mounted at."""
        return "/" + prefix + url.lstrip("/")

    smoke = Smoke()
    location = Path(generic.__file__).resolve().parent

    print(f"django-generic {generic.__version__} from {location}")
    print(f"Django {django.get_version()}, Python {sys.version.split()[0]}")
    print(f"The site mounted at {site('/')}")

    print("\nThe project")
    call_command("makemigrations", "library", verbosity=0)
    call_command("migrate", verbosity=0)
    issues = [
        message
        for message in run_checks()
        if message.id and message.id.startswith("generic.")
    ]

    for message in issues:
        print(f"  note  {message.id}: {message.msg}")

    smoke.check(
        "the framework's checks find nothing wrong",
        not [message for message in issues if message.level >= ERROR],
    )

    print("\nStatic files")
    smoke.check(
        "the frame's stylesheet is found",
        bool(finders.find("generic/css/base.css")),
    )
    smoke.check(
        "the vendored DataTables is found",
        bool(finders.find("generic/vendor/datatables/dataTables.min.js")),
    )
    call_command("collectstatic", interactive=False, verbosity=0)
    smoke.check(
        "collectstatic with hashed names (as in production)",
        (root / "staticfiles" / "staticfiles.json").is_file(),
    )

    from library.models import Book

    book = Book.objects.create(title="Dune", author="Frank Herbert", pages=412)
    user = get_user_model().objects.create_superuser(
        "admin", "admin@example.com", "not-a-real-password"
    )

    print("\nSigned out")
    anonymous = Client()
    response = anonymous.get(site("/"))
    smoke.check(
        "the dashboard sends to sign in",
        response.status_code == 302
        and response["Location"].startswith(site("/login/")),
        f"got {response.status_code} {response.get('Location', '')}",
    )
    smoke.page(anonymous, site("/login/"))
    smoke.page(anonymous, site("/api/library/book/"), status=403)

    print("\nSigned in")
    client = Client()
    client.force_login(user)

    for url in (
        site("/"),
        site("/library/book/"),
        site("/library/book/add/"),
        site(f"/library/book/{book.pk}/"),
        site(f"/library/book/{book.pk}/change/"),
        site(f"/library/book/{book.pk}/delete/"),
        site("/library/book/shelf/"),
        site("/account/"),
        site("/notifications/"),
        site("/help/"),
        site("/help/changes/"),
        "/jsi18n/",
        "/admin/",
    ):
        smoke.page(client, url)

    shelf = client.get(site("/library/book/shelf/")).content.decode()
    smoke.check("a page of the resource's own", "shelf-book" in shelf)

    changes = client.get(site("/help/changes/")).content.decode()
    smoke.check(
        "the framework's changelog ships with the package",
        generic.__version__ in changes,
    )

    rows = client.get(site("/api/library/book/"), {"draw": 1}).json()
    smoke.check(
        "the table's rows",
        rows.get("recordsTotal") == 1 and rows["data"][0]["title"] == "Dune",
        json.dumps(rows)[:200],
    )
    schema = client.get(site("/api/library/book/form-schema/"))
    smoke.check("the form's schema", schema.status_code == 200)

    created = client.post(
        site("/api/library/book/"),
        data=json.dumps(
            {"title": "Emma", "author": "Jane Austen", "pages": 474}
        ),
        content_type="application/json",
    )
    smoke.check(
        "a record created through the API",
        created.status_code == 201,
        f"got {created.status_code}: {created.content[:200]!r}",
    )
    filtered = client.get(
        site("/api/library/book/"),
        {
            "draw": 1,
            "filters": json.dumps(
                {
                    "match": "all",
                    "conditions": [
                        {"column": "pages", "operator": "gt", "value": "450"}
                    ],
                }
            ),
        },
    ).json()
    smoke.check(
        "a filter",
        [row["title"] for row in filtered.get("data", [])] == ["Emma"],
    )
    export = client.get(site("/api/library/book/export-csv/"))
    smoke.check("the CSV export", export.status_code == 200)
    search = client.get(site("/api/search/"), {"q": "Dune"}).json()
    smoke.check("the command palette finds the record", "Dune" in str(search))

    # Every address the frame hands the browser is under the prefix.
    home = client.get(site("/")).content.decode()
    smoke.check(
        "the frame's links follow the prefix",
        f'href="{site("/library/book/")}"' in home,
    )

    print("\nIn French")
    french = client.get(site("/"), HTTP_ACCEPT_LANGUAGE="fr").content.decode()
    smoke.check("the frame speaks French", "Tableau de bord" in french)
    catalog = client.get("/jsi18n/", HTTP_ACCEPT_LANGUAGE="fr")
    smoke.check(
        "the JavaScript is translated too",
        "Ajouter le filtre" in catalog.content.decode(),
    )

    print(f"\n{smoke.passed} passed, {len(smoke.failures)} failed")

    for failure in smoke.failures:
        print(f"  - {failure}")

    return 1 if smoke.failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--prefix",
        default="",
        help="mount the site under this prefix, e.g. 'app/', as a project "
        "whose root is already taken would",
    )
    arguments = parser.parse_args()
    prefix = arguments.prefix.strip("/")
    prefix = f"{prefix}/" if prefix else ""

    with tempfile.TemporaryDirectory(
        prefix="generic-smoke-", ignore_cleanup_errors=True
    ) as directory:
        root = Path(directory)
        build_project(root, prefix)

        try:
            return run(root, prefix)
        finally:
            # The database file is let go before its folder is removed.
            from django.db import connections

            connections.close_all()


if __name__ == "__main__":
    sys.exit(main())

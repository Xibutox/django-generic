"""The minimal example must keep working.

``minimal/`` is the smallest project the framework runs in, and a
reader copies from it. It is a project of its own - its own settings,
its own ``manage.py`` - so it is run as one, in a process of its own,
from its folder: what someone following its README does.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

MINIMAL = Path(__file__).resolve().parent.parent / "minimal"

#: Every page and endpoint the example has, opened by a signed-in user
#: on a test database - never the example's own db.sqlite3.
PAGES = textwrap.dedent("""
    import os

    os.environ["DJANGO_SETTINGS_MODULE"] = "mysite.settings"

    import django
    from django.conf import settings

    django.setup()
    settings.ALLOWED_HOSTS = ["testserver"]

    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.test import Client
    from django.test.utils import setup_test_environment

    setup_test_environment()
    connection.creation.create_test_db(verbosity=0)

    from library.models import Book

    book = Book.objects.create(title="Dune", author="Frank Herbert")
    client = Client()

    response = client.get("/")
    assert response.status_code == 302, response.status_code
    assert response["Location"].startswith("/login/"), response["Location"]
    response = client.get("/login/")
    assert response.status_code == 200
    # No app registration in the environment: no Microsoft button.
    assert b"/accounts/microsoft/" not in response.content

    client.force_login(
        get_user_model().objects.create_superuser(
            "admin", "admin@example.com", "demo"
        )
    )

    for url in (
        "/",
        "/library/book/",
        f"/library/book/{book.pk}/",
        "/library/book/add/",
        f"/library/book/{book.pk}/change/",
        f"/library/book/{book.pk}/delete/",
        "/api/library/book/",
        "/api/generic/account/preferences/",
        "/jsi18n/",
    ):
        status = client.get(url).status_code
        assert status == 200, f"{url}: {status}"

    rows = client.get("/api/library/book/").json()["data"]
    assert [row["title"] for row in rows] == ["Dune"], rows

    # The wiki: in the navigation, empty, then a page written through
    # its API and read - the HTML cleaned on the way in.
    assert b'href="/wiki/"' in client.get("/").content
    assert client.get("/wiki/").status_code == 200
    response = client.post(
        "/wiki/api/pages/",
        {"title": "Welcome", "content": "<p>Hi<script>x</script></p>"},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    page = response.json()
    assert "script" not in page["content"], page

    assert client.get("/wiki/")["Location"] == f"/wiki/{page['slug']}/"

    for url in (
        f"/wiki/{page['slug']}/",
        "/wiki/api/pages/",
        f"/wiki/api/pages/{page['id']}/revisions/",
    ):
        status = client.get(url).status_code
        assert status == 200, f"{url}: {status}"
    print("ok")
    """)


#: Signing in with Microsoft, turned on by its environment variables:
#: the button first on the sign-in page, carrying the destination, and
#: allauth sending the reader on to the tenant's sign-in.
MICROSOFT = textwrap.dedent("""
    import os
    from urllib.parse import parse_qs, urlsplit

    os.environ["DJANGO_SETTINGS_MODULE"] = "mysite.settings"

    import django
    from django.conf import settings

    django.setup()
    settings.ALLOWED_HOSTS = ["testserver"]

    from django.db import connection
    from django.test import Client
    from django.test.utils import setup_test_environment

    setup_test_environment()
    connection.creation.create_test_db(verbosity=0)

    client = Client()
    page = client.get("/login/?next=/library/book/").content.decode()
    button = "/accounts/microsoft/login/?next=%2Flibrary%2Fbook%2F"
    assert f'href="{button}"' in page, page
    # The password form is still there, folded under the button.
    assert 'name="password"' in page

    response = client.get(button)
    assert response.status_code == 302, response.status_code
    location = urlsplit(response["Location"])
    assert location.netloc == "login.microsoftonline.com", location
    assert location.path == "/the-tenant/oauth2/v2.0/authorize", location
    query = parse_qs(location.query)
    assert query["client_id"] == ["the-client"], query
    assert query["redirect_uri"] == [
        "http://testserver/accounts/microsoft/login/callback/"
    ], query
    print("ok")
    """)


def manage(*args: str, **environ: str) -> subprocess.CompletedProcess:
    """A command run as the README runs it, from the example's folder.

    The suite's own settings module is left behind: the example must
    find its settings by itself.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if name != "DJANGO_SETTINGS_MODULE"
        and not name.startswith("MICROSOFT_")
    }
    env.update(environ)

    return subprocess.run(
        [sys.executable, *args],
        cwd=MINIMAL,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_checks_find_nothing():
    result = manage("manage.py", "check", "--fail-level", "INFO")

    assert result.returncode == 0, result.stderr
    assert "no issues" in result.stdout


def test_the_migrations_are_up_to_date():
    result = manage("manage.py", "makemigrations", "--check", "--dry-run")

    assert result.returncode == 0, result.stdout + result.stderr


def test_every_page_answers():
    result = manage("-c", PAGES)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")


def test_microsoft_sign_in_is_offered_once_registered():
    pytest.importorskip("allauth.socialaccount")
    environ = {
        "MICROSOFT_CLIENT_ID": "the-client",
        "MICROSOFT_CLIENT_SECRET": "the-secret",
        "MICROSOFT_TENANT_ID": "the-tenant",
    }

    result = manage("manage.py", "check", "--fail-level", "INFO", **environ)
    assert result.returncode == 0, result.stderr

    result = manage("-c", MICROSOFT, **environ)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")


def test_the_container_keeps_its_database_in_the_volume():
    """Built from the root, which holds the framework, with the SQLite
    file and the wiki's images in the volume: a ``down`` and ``up``
    loses nothing."""
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((MINIMAL / "compose.yaml").read_text())
    web = compose["services"]["web"]
    dockerfile = (MINIMAL / "Dockerfile").read_text()

    assert web["build"] == {
        "context": "..",
        "dockerfile": "minimal/Dockerfile",
    }
    assert "data:/data" in web["volumes"]
    assert "DJANGO_DB_PATH=/data/db.sqlite3" in dockerfile
    # The wiki's extra, and its images in the volume beside the database.
    assert 'pip install ".[wiki]"' in dockerfile
    assert "DJANGO_MEDIA_ROOT=/data/media" in dockerfile
    # Microsoft sign-in: allauth installed, the registration passed
    # through from the environment and never written down.
    assert "django-allauth[socialaccount]" in dockerfile
    for name in (
        "MICROSOFT_CLIENT_ID",
        "MICROSOFT_CLIENT_SECRET",
        "MICROSOFT_TENANT_ID",
    ):
        assert web["environment"][name] == f"${{{name}:-}}", name

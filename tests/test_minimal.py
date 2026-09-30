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
    assert client.get("/login/").status_code == 200

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
    print("ok")
    """)


def manage(*args: str) -> subprocess.CompletedProcess:
    """A command run as the README runs it, from the example's folder.

    The suite's own settings module is left behind: the example must
    find its settings by itself.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if name != "DJANGO_SETTINGS_MODULE"
    }

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

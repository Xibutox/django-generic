"""The document manager example must keep working.

``docmanager/`` is a project of its own - its settings, its
``manage.py`` - so, like the minimal example, it is run as one, in a
process of its own, from its folder, on a test database.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

DOCMANAGER = Path(__file__).resolve().parent.parent / "docmanager"

#: A test database, seeded twice, and a client per person.
PRELUDE = textwrap.dedent("""
    import json
    import os
    import tempfile

    os.environ["DJANGO_SETTINGS_MODULE"] = "docsite.settings"

    import django
    from django.conf import settings

    django.setup()
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.MEDIA_ROOT = tempfile.mkdtemp()

    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.core.management import call_command
    from django.db import connection
    from django.test import Client
    from django.test.client import BOUNDARY, MULTIPART_CONTENT
    from django.test.client import encode_multipart
    from django.test.utils import setup_test_environment

    setup_test_environment()
    connection.creation.create_test_db(verbosity=0)
    call_command("seed_documents", stdout=open(os.devnull, "w"))
    call_command("seed_documents", stdout=open(os.devnull, "w"))

    from documents.models import Document, DocumentVersion, Folder

    def signed_in(username):
        client = Client()
        client.force_login(get_user_model().objects.get(username=username))
        return client

    def teams_seen(username):
        rows = signed_in(username).get(
            "/api/documents/document/", {"draw": 1, "length": 100}
        ).json()["data"]
        return sorted({row["folder__team"] for row in rows})

    """)

#: Seeded, then walked by each kind of person: what they see, what they
#: may send, and every version a file goes through.
SCENARIO = PRELUDE + textwrap.dedent("""
    # Seeded once, whatever the number of runs.
    assert Document.objects.count() == 8, Document.objects.count()
    framework = Document.objects.get(title="Supplier framework agreement")
    assert framework.version == 3
    assert framework.versions.count() == 3

    # Each sees their teams; the manager and the administrator all.
    every = ["Engineering", "Human resources", "Legal"]
    assert teams_seen("admin") == every
    assert teams_seen("manager") == every
    assert teams_seen("alice") == ["Engineering", "Legal"]
    assert teams_seen("bob") == ["Engineering"]
    assert teams_seen("carol") == ["Human resources"]

    bob = signed_in("bob")
    procedures = Folder.objects.get(name="Procedures")
    contracts = Folder.objects.get(name="Contracts")
    assert bob.get(f"/documents/document/{framework.pk}/").status_code == 404

    def send(client, method, url, payload, upload=None):
        data = {"_payload": json.dumps(payload)}
        if upload:
            data["file"] = upload
        return client.generic(
            method,
            url,
            encode_multipart(BOUNDARY, data),
            content_type=MULTIPART_CONTENT,
        )

    # Not in another team's folder.
    refused = send(
        bob, "POST", "/api/documents/document/",
        {"title": "Spec", "folder": contracts.pk},
        SimpleUploadedFile("spec.docx", b"one"),
    )
    assert refused.status_code == 400, refused.content

    # A document, its first version, then a second from its form.
    created = send(
        bob, "POST", "/api/documents/document/",
        {"title": "Spec", "folder": procedures.pk, "version_note": "First"},
        SimpleUploadedFile("spec.docx", b"one"),
    )
    assert created.status_code == 201, created.content
    spec = Document.objects.get(title="Spec")
    assert spec.reference.startswith("DOC-")
    assert spec.version == 1

    renamed = bob.patch(
        f"/api/documents/document/{spec.pk}/",
        json.dumps({"title": "Spec 2"}),
        content_type="application/json",
    )
    assert renamed.status_code == 200, renamed.content
    spec.refresh_from_db()
    assert spec.version == 1, "no file sent, no version"

    replaced = send(
        bob, "PATCH", f"/api/documents/document/{spec.pk}/",
        {"version_note": "Second"},
        SimpleUploadedFile("spec.docx", b"two!"),
    )
    assert replaced.status_code == 200, replaced.content

    # A third from the Versions tab, then the first restored.
    added = send(
        bob, "POST", "/api/documents/documentversion/",
        {"document": spec.pk, "comment": "Third"},
        SimpleUploadedFile("spec (final).docx", b"three"),
    )
    assert added.status_code == 201, added.content
    first = spec.versions.get(number=1)
    restored = bob.post(
        "/api/documents/documentversion/actions/",
        json.dumps({"action": "restore", "ids": [first.pk]}),
        content_type="application/json",
    )
    assert restored.status_code == 200, restored.content

    spec.refresh_from_db()
    story = list(spec.versions.values_list("number", "comment", "file_size"))
    assert story == [
        (4, "Restored from version 1.", 3),
        (3, "Third", 5),
        (2, "Second", 4),
        (1, "First", 3),
    ], story
    assert spec.version == 4
    assert spec.file.read() == b"one"

    third = spec.versions.get(number=3)
    download = bob.get(
        f"/api/documents/documentversion/{third.pk}/files/file/"
    )
    assert download.status_code == 200
    assert 'filename="spec (final).docx"' in download["Content-Disposition"]
    assert len(third.checksum) == 64

    # A version is never rewritten.
    assert bob.patch(
        f"/api/documents/documentversion/{third.pk}/",
        json.dumps({"comment": "Changed"}),
        content_type="application/json",
    ).status_code == 403

    # A reader reads.
    viewer = signed_in("viewer")
    assert send(
        viewer, "POST", "/api/documents/document/",
        {"title": "No", "folder": contracts.pk},
        SimpleUploadedFile("no.txt", b"no"),
    ).status_code == 403

    for url in (
        "/",
        "/documents/document/",
        f"/documents/document/{spec.pk}/",
        "/documents/document/add/",
        f"/documents/document/{spec.pk}/change/",
        "/documents/folder/",
        f"/documents/folder/{procedures.pk}/",
        "/documents/folder/add/",
        "/documents/documentversion/",
        f"/documents/documentversion/{third.pk}/",
        f"/documents/documentversion/add/?document={spec.pk}",
        "/documents/tag/",
        "/documents/document/merge/",
        "/generic_teams/team/",
        f"/api/documents/document/{spec.pk}/summary/",
        "/api/documents/document/charts/by_status/",
        "/api/documents/document/charts/by_team/",
    ):
        status = bob.get(url).status_code
        assert status == 200, f"{url}: {status}"

    # A wiki per team, beside everyone's: each reads their teams'.
    from django.contrib.auth import get_user_model
    from generic.wiki.models import Wiki

    def wikis_of(username):
        user = get_user_model().objects.get(username=username)
        return sorted(
            Wiki.objects.readable_by(user).values_list("slug", flat=True)
        )

    assert wikis_of("bob") == ["engineering-handbook", "main"]
    assert wikis_of("alice") == [
        "engineering-handbook", "legal-handbook", "main"
    ]
    assert wikis_of("viewer") == ["legal-handbook", "main"]
    assert len(wikis_of("manager")) == 4
    assert Wiki.objects.get(slug="main").name == "Company"

    assert bob.get("/wiki/").status_code == 200
    for url in (
        "/wiki/legal-handbook/",
        "/wiki/legal-handbook/contract-review/",
        "/wiki/legal-handbook/export.pdf",
    ):
        assert bob.get(url).status_code == 404, url

    assert bob.get("/wiki/engineering-handbook/on-call/").status_code == 200
    exported = bob.get("/wiki/engineering-handbook/export.pdf")
    assert exported.status_code == 200, exported.status_code
    assert exported["Content-Type"] == "application/pdf"
    assert exported.content.startswith(b"%PDF-")

    # Which wiki is whose: the managers say.
    assert bob.get("/documents/teamwiki/").status_code == 403
    rows = signed_in("manager").get(
        "/api/documents/teamwiki/", {"draw": 1}
    ).json()["data"]
    assert len(rows) == 3, rows

    # Seeded samples open as what they claim to be.
    import zipfile
    word = Document.objects.get(title="Letter template").file
    assert zipfile.ZipFile(word.open("rb")).read("word/document.xml")
    pdf = Document.objects.get(title="Salary grid").file
    assert pdf.open("rb").read(5) == b"%PDF-"
    print("ok")
    """)

#: Formats found, Word files picked in the lists and merged: downloaded,
#: or kept as a new document - each person within their teams only.
MERGE_SCENARIO = PRELUDE + textwrap.dedent("""
    import io

    from docx import Document as WordFile

    def rows(client, url, **params):
        return client.get(url, {"draw": 1, "length": 100, **params}).json()[
            "data"
        ]

    def paragraphs(content):
        return [p.text for p in WordFile(io.BytesIO(content)).paragraphs]

    def run(client, model, name, ids):
        return client.post(
            f"/api/documents/{model}/actions/",
            json.dumps({"action": name, "ids": ids}),
            content_type="application/json",
        )

    alice, bob = signed_in("alice"), signed_in("bob")
    MERGE = "/documents/document/merge/"

    # The format: a field, searched, filtered, and filled on old rows.
    found = rows(bob, "/api/documents/document/", **{"search[value]": "pdf"})
    assert [row["title"] for row in found] == ["Release procedure"], found
    word = rows(
        alice,
        "/api/documents/document/",
        filters=json.dumps({"match": "all", "conditions": [{
            "column": "file_format", "operator": "equals",
            "value": ["DOCX", "DOTX"],
        }]}),
    )
    assert sorted(row["file_format"] for row in word) == [
        "DOCX", "DOCX", "DOTX", "DOTX"
    ], word
    assert set(
        DocumentVersion.objects.values_list("file_format", flat=True)
    ) == {"DOCX", "DOTX", "PDF", "MD"}

    framework = Document.objects.get(title="Supplier framework agreement")
    nda = Document.objects.get(title="Non-disclosure agreement")
    letter = Document.objects.get(title="Letter template")
    guide = Document.objects.get(title="Welcome guide")
    pdf = Document.objects.get(title="Release procedure")
    first = framework.versions.get(number=1)

    # The actions open the page with the selection's Word files.
    opened = run(alice, "document", "merge_word", [nda.pk, pdf.pk])
    assert opened.status_code == 200, opened.content
    assert opened.json()["redirect"] == f"{MERGE}?items=d{nda.pk}", opened.json()
    from_versions = run(alice, "documentversion", "merge_word", [first.pk])
    assert from_versions.json()["redirect"] == f"{MERGE}?items=v{first.pk}"
    none = run(bob, "document", "merge_word", [pdf.pk]).json()
    assert none["level"] == "warning" and "redirect" not in none, none
    # Another team's record is not even selected.
    assert run(bob, "document", "merge_word", [nda.pk]).status_code == 400

    page = alice.get(MERGE, {"items": f"d{nda.pk},v{first.pk},d{guide.pk}"})
    assert page.status_code == 200
    config = page.context["merge_config"]
    assert [item["key"] for item in config["items"]] == [
        f"d{nda.pk}", f"v{first.pk}"
    ], config
    assert "left out" in page.context["error"]
    assert f"d{guide.pk}" not in {c["key"] for c in config["choices"]}
    assert letter in page.context["templates"]

    # Merged in the order sent, into the template, downloaded.
    merged = alice.post(MERGE, {
        "items": [f"v{first.pk}", f"d{nda.pk}"],
        "template": letter.pk,
        "name": "Pack",
        "page_breaks": "on",
    })
    assert merged.status_code == 200, merged.content[:500]
    assert 'filename="Pack.docx"' in merged["Content-Disposition"]
    text = [line for line in paragraphs(merged.content) if line]
    assert text[0] == "Letter template", text
    assert "{{ documents }}" not in text, text
    assert text.index("First draft.") < text.index(
        "From the legal template."
    ), text

    # Kept as a new document instead: version 1, in the folder chosen.
    contracts = Folder.objects.get(name="Contracts")
    kept = alice.post(MERGE, {
        "items": [f"d{nda.pk}"], "folder": contracts.pk, "title": "Kept",
    })
    assert kept.status_code == 302, kept.content[:500]
    document = Document.objects.get(title="Kept")
    assert kept["Location"] == f"/documents/document/{document.pk}/"
    assert (document.version, document.file_format) == (1, "DOCX")
    assert document.versions.get().file_name == "merged.docx"

    # Nothing of another team's, whatever the form says.
    for data in (
        {"items": [f"d{nda.pk}"]},
        {"items": [f"d{pdf.pk}"]},
        {"items": [], "template": letter.pk},
    ):
        refused = bob.post(MERGE, data)
        assert refused.status_code == 200, data
        assert refused.context["error"], data
        assert refused["Content-Type"].startswith("text/html"), data

    for data in ({"template": "x"}, {"folder": "1 OR 1=1"}):
        refused = alice.post(MERGE, {"items": [f"d{nda.pk}"], **data})
        assert refused.status_code == 200, data
        assert "not available" in refused.context["error"], data

    report = Document.objects.get(title="Report template")
    refused = bob.post(MERGE, {
        "items": [f"d{report.pk}"], "template": letter.pk,
    })
    assert refused.context["error"] == "This template is not available."
    refused = bob.post(MERGE, {
        "items": [f"d{report.pk}"], "folder": contracts.pk,
    })
    assert refused.context["error"] == "This folder is not available."

    # A reader downloads, and keeps nothing.
    viewer = signed_in("viewer")
    assert not viewer.get(MERGE).context["folders"]
    assert viewer.post(MERGE, {
        "items": [f"d{nda.pk}"], "folder": contracts.pk,
    }).context["error"] == "This folder is not available."
    assert viewer.post(MERGE, {"items": [f"d{nda.pk}"]}).status_code == 200
    print("ok")
    """)


def manage(*args: str) -> subprocess.CompletedProcess:
    env = {
        name: value
        for name, value in os.environ.items()
        if name != "DJANGO_SETTINGS_MODULE"
    }

    return subprocess.run(
        [sys.executable, *args],
        cwd=DOCMANAGER,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_the_checks_find_nothing():
    result = manage("manage.py", "check", "--fail-level", "INFO")

    assert result.returncode == 0, result.stderr
    assert "no issues" in result.stdout


def test_the_migrations_are_up_to_date():
    result = manage("manage.py", "makemigrations", "--check", "--dry-run")

    assert result.returncode == 0, result.stdout + result.stderr


def test_teams_documents_and_versions_work_together():
    result = manage("-c", SCENARIO)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")


def test_word_files_are_found_by_format_and_merged():
    pytest.importorskip("docx")
    pytest.importorskip("docxcompose")
    result = manage("-c", MERGE_SCENARIO)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")

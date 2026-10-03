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
    assert Document.objects.count() == 9, Document.objects.count()
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
        (4, "Restored from version 0.1.", 3),
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
    assert len(rows) == 4, rows

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


#: Numbers given by each team's pattern, documents without a file,
#: review circuits run step by step with their messages, check-outs, and
#: the teams writing in each wiki.
GED_SCENARIO = PRELUDE + textwrap.dedent("""
    from django.core import mail
    from documents.models import (
        Codification, DocumentType, Review, ReviewStep, ReviewTask,
        Workflow,
    )
    from generic.models import Notification
    from generic.teams.models import Team

    User = get_user_model()

    def user(name):
        return User.objects.get(username=name)

    def call(client, method, url, payload=None):
        return client.generic(
            method, url, json.dumps(payload or {}),
            content_type="application/json",
        )

    def action(client, model, name, ids):
        return call(
            client, "POST", f"/api/documents/{model}/actions/",
            {"action": name, "ids": ids},
        )

    def rows(client, url, **params):
        return client.get(url, {"draw": 1, "length": 100, **params}).json()[
            "data"
        ]

    def told(name):
        return list(
            Notification.objects.filter(user__username=name)
            .order_by("-pk").values_list("title", flat=True)
        )

    alice, bob, carol = signed_in("alice"), signed_in("bob"), signed_in("carol")
    quentin, viewer = signed_in("quentin"), signed_in("viewer")
    manager = signed_in("manager")
    legal, engineering = (
        Team.objects.get(name="Legal"), Team.objects.get(name="Engineering")
    )

    # -- numbers ----------------------------------------------------
    numbered = dict(Document.objects.values_list("title", "code"))
    assert numbered["Supplier framework agreement"].startswith("LEG-CTR-")
    assert numbered["Release procedure"] == "ENG/PRC/00001", numbered
    assert len(set(numbered.values())) == len(numbered), numbered
    placeholder = Document.objects.get(title="Supplier contract 2027")
    assert (placeholder.version, placeholder.file.name) == (0, "")
    assert placeholder.code.startswith("LEG-CTR-")

    contracts = Folder.objects.get(name="Contracts")
    procedures = Folder.objects.get(name="Procedures")
    contract = DocumentType.objects.get(code="CTR")
    note = DocumentType.objects.get(code="NOT")

    # Legal numbers every new document, without a file too.
    created = call(alice, "POST", "/api/documents/document/", {
        "title": "Lease", "folder": contracts.pk,
        "document_type": contract.pk,
    })
    assert created.status_code == 201, created.content
    lease = Document.objects.get(title="Lease")
    assert lease.code and lease.code.startswith("LEG-CTR-"), lease.code
    assert lease.version == 0

    # Engineering numbers when asked: in the form, or by the action.
    call(bob, "POST", "/api/documents/document/", {
        "title": "Idea", "folder": procedures.pk, "document_type": note.pk,
    })
    idea = Document.objects.get(title="Idea")
    assert idea.code is None
    assert action(bob, "document", "codify", [idea.pk]).status_code == 200
    idea.refresh_from_db()
    assert idea.code == "ENG/NOT/00002", idea.code
    again = action(bob, "document", "codify", [idea.pk]).json()
    idea.refresh_from_db()
    assert idea.code == "ENG/NOT/00002" and again["level"] == "info"
    call(bob, "POST", "/api/documents/document/", {
        "title": "Spec", "folder": procedures.pk, "codify": True,
    })
    assert Document.objects.get(title="Spec").code == "ENG/DOC/00001"

    # A team's pattern is checked; its next number shown, not taken.
    rules = Codification.objects.get(team=engineering)
    bad = call(manager, "PATCH", f"/api/documents/codification/{rules.pk}/",
               {"pattern": "ENG-{nope}"})
    assert bad.status_code == 400, bad.content
    row = rows(manager, "/api/documents/codification/")
    assert {"ENG/DOC/00002"} & {r["next_number"] for r in row}, row
    assert Document.objects.get(title="Spec").code == "ENG/DOC/00001"
    assert bob.get("/documents/codification/").status_code == 200

    # The list finds the numbers and the documents without a file.
    found = rows(alice, "/api/documents/document/", **{
        "search[value]": "LEG-CTR"
    })
    assert "Lease" in [r["title"] for r in found], found
    empty = rows(alice, "/api/documents/document/", filters=json.dumps(
        {"match": "all", "conditions": [
            {"column": "file_format", "operator": "empty"}]}
    ))
    assert {r["title"] for r in empty} == {
        "Lease", "Supplier contract 2027", "Idea", "Spec"
    }, empty

    # -- a review from a workflow -----------------------------------
    nda = Document.objects.get(title="Non-disclosure agreement")
    running = Review.objects.get(document=nda)
    pending = ReviewTask.objects.get(review=running, status="pending")
    assert pending.assignee.username == "quentin"

    # Quentin is in no team, yet reads what he is asked to review.
    assert quentin.get(f"/documents/document/{nda.pk}/").status_code == 200
    assert quentin.get(
        f"/api/documents/document/{nda.pk}/files/file/"
    ).status_code == 200
    framework = Document.objects.get(title="Supplier framework agreement")
    assert quentin.get(
        f"/documents/document/{framework.pk}/"
    ).status_code == 404
    mine = rows(quentin, "/api/documents/reviewtask/", filters=json.dumps(
        {"match": "all", "conditions": [
            {"column": "mine", "operator": "is_true"},
            {"column": "status", "operator": "any_of", "value": ["pending"]},
        ]}
    ))
    assert len(mine) == 2, mine

    # Nobody else answers it - but its starter may, for him.
    refused = call(bob, "PATCH", f"/api/documents/reviewtask/{pending.pk}/",
                   {"decision": "approve"})
    assert refused.status_code == 404, refused.status_code
    refused = call(viewer, "PATCH",
                   f"/api/documents/reviewtask/{pending.pk}/",
                   {"decision": "approve"})
    assert refused.status_code == 403, refused.status_code
    assert call(quentin, "PATCH",
                f"/api/documents/reviewtask/{pending.pk}/",
                {"comment": "No answer"}).status_code == 400

    mail.outbox = []
    answered = call(quentin, "PATCH",
                    f"/api/documents/reviewtask/{pending.pk}/",
                    {"decision": "approve", "comment": "Quality OK"})
    assert answered.status_code == 200, answered.content
    pending.refresh_from_db()
    assert (pending.status, pending.comment) == ("approved", "Quality OK")

    # The second step asks the manager: a notification and a mail.
    step = running.steps.get(status="active")
    assert step.name == "Sign-off"
    assert "Review requested" not in told("manager")[0]
    assert told("manager")[0].startswith("Approval requested"), told(
        "manager"
    )
    assert [
        message.to for message in mail.outbox
        if message.subject.startswith("Approval requested")
    ] == [["manager@example.com"]], [m.subject for m in mail.outbox]
    # Alice started it, and leads Legal: told how it goes.
    assert told("alice")[0].startswith("Review of"), told("alice")
    body = Notification.objects.filter(user__username="alice").latest(
        "pk"
    ).body
    assert "step 2 of 2" in body, body

    sign = ReviewTask.objects.get(step=step)
    assert call(manager, "PATCH", f"/api/documents/reviewtask/{sign.pk}/",
                {"decision": "approve"}).status_code == 200
    running.refresh_from_db()
    nda.refresh_from_db()
    assert running.status == "approved", running.status
    assert nda.status == "approved"
    assert "Every step is done." in Notification.objects.filter(
        user__username="alice"
    ).latest("pk").body

    # -- a review drawn on the spot ---------------------------------
    lease_review = call(alice, "POST", "/api/documents/review/", {
        "document": lease.pk,
        "message": "Read it before Friday.",
        "start": True,
        "_inlines": {"steps": [
            {"position": 1, "name": "Check", "kind": "review",
             "rule": "all", "users": [user("viewer").pk, user("bob").pk],
             "groups": [], "team_leaders": False, "team_members": False},
            {"position": 2, "name": "Nobody", "kind": "approval",
             "rule": "any", "users": [], "groups": [],
             "team_leaders": False, "team_members": False},
            {"position": 3, "name": "Read", "kind": "acknowledgement",
             "rule": "any", "users": [], "groups": [],
             "team_leaders": False, "team_members": True, "days": 2},
        ]},
    })
    assert lease_review.status_code == 201, lease_review.content
    review = Review.objects.get(document=lease)
    assert review.status == "in_progress", review.status
    lease.refresh_from_db()
    assert lease.status == "review"
    first = review.steps.get(position=1)
    assert sorted(first.tasks.values_list("assignee__username", flat=True)) \
        == ["bob", "viewer"]
    # Started, its form is closed; its steps are steered from their tab.
    assert call(alice, "PATCH", f"/api/documents/review/{review.pk}/",
                {"message": "x"}).status_code == 403

    # Each of them: one answer is not enough.
    bobs = first.tasks.get(assignee__username="bob")
    victors = first.tasks.get(assignee__username="viewer")
    assert action(bob, "reviewtask", "approve_tasks",
                  [bobs.pk]).status_code == 200
    first.refresh_from_db()
    assert first.status == "active"

    # Victor hands his task to Carol, who is in no Legal folder.
    handed = call(viewer, "PATCH", f"/api/documents/reviewtask/{victors.pk}/",
                  {"delegate_to": user("carol").pk})
    assert handed.status_code == 200, handed.content
    carols = first.tasks.get(assignee__username="carol")
    assert carol.get(f"/documents/document/{lease.pk}/").status_code == 200
    assert told("carol")[0].startswith("Review requested"), told("carol")

    # The step nobody can answer is skipped; the team reads.
    assert call(carol, "PATCH", f"/api/documents/reviewtask/{carols.pk}/",
                {"decision": "approve"}).status_code == 200
    statuses = dict(review.steps.values_list("name", "status"))
    assert statuses == {
        "Check": "done", "Nobody": "skipped", "Read": "active"
    }, statuses
    reading = review.steps.get(name="Read")
    assert set(reading.tasks.values_list("assignee__username", flat=True)) \
        == {"alice", "viewer"}
    assert reading.due_on is not None
    victor_reads = reading.tasks.get(assignee__username="viewer")
    # A document to read is only read.
    assert call(viewer, "PATCH",
                f"/api/documents/reviewtask/{victor_reads.pk}/",
                {"decision": "reject"}).status_code == 400

    # The starter adds a step while it runs, then skips the reading.
    added = call(alice, "POST", "/api/documents/reviewstep/", {
        "review": review.pk, "position": 4, "name": "Final",
        "kind": "approval", "rule": "any", "users": [user("alice").pk],
        "groups": [],
    })
    assert added.status_code == 201, added.content
    assert action(viewer, "review", "skip_step", [review.pk]).json()[
        "level"
    ] == "error"
    assert action(alice, "review", "skip_step", [review.pk]).json()[
        "level"
    ] == "success"
    final = review.steps.get(name="Final")
    assert final.status == "active"
    # Alice rejects it at the last step: the document is a draft again.
    last = final.tasks.get()
    assert call(alice, "PATCH", f"/api/documents/reviewtask/{last.pk}/",
                {"decision": "reject", "comment": "Clause 2."}
                ).status_code == 200
    review.refresh_from_db()
    lease.refresh_from_db()
    assert (review.status, lease.status) == ("rejected", "draft")

    # -- prepared, then started; cancelled --------------------------
    spec = Document.objects.get(title="Spec")
    quick = Workflow.objects.get(name="Quick approval")
    prepared = call(bob, "POST", "/api/documents/review/", {
        "document": spec.pk, "workflow": quick.pk, "start": False,
    })
    assert prepared.status_code == 201, prepared.content
    later = Review.objects.get(document=spec)
    assert later.status == "preparing" and later.steps.count() == 1
    assert action(bob, "review", "start_review", [later.pk]).json()[
        "level"
    ] == "success"
    later.refresh_from_db()
    assert later.status == "in_progress"
    assert action(bob, "review", "cancel_review", [later.pk]).json()[
        "level"
    ] == "success"
    later.refresh_from_db()
    spec.refresh_from_db()
    assert later.status == "cancelled" and spec.status == "draft"
    assert not ReviewTask.objects.filter(review=later, status="pending")

    # Reminders, and the dashboard's count.
    welcome = Review.objects.get(document__title="Welcome guide")
    count = action(carol, "review", "remind", [welcome.pk]).json()
    assert count["message"].startswith("1"), count
    assert carol.get("/").status_code == 200

    # -- check-out: a notice, never a lock --------------------------
    letter = Document.objects.get(title="Letter template")
    assert action(alice, "document", "check_out",
                  [letter.pk]).status_code == 200
    letter.refresh_from_db()
    assert letter.checked_out_by.username == "alice"
    held = action(manager, "document", "check_out", [letter.pk]).json()
    assert held["level"] == "warning", held
    data = {"_payload": json.dumps({"version_note": "Mine"}),
            "file": SimpleUploadedFile("letter.dotx", b"new")}
    sent = manager.generic(
        "PATCH", f"/api/documents/document/{letter.pk}/",
        encode_multipart(BOUNDARY, data), content_type=MULTIPART_CONTENT,
    )
    assert sent.status_code == 200, sent.content
    assert told("alice")[0].startswith("New version of"), told("alice")
    assert action(manager, "document", "check_in",
                  [letter.pk]).status_code == 200
    letter.refresh_from_db()
    assert letter.checked_out_by is None
    assert told("alice")[0].endswith("was checked in"), told("alice")

    # -- comments ---------------------------------------------------
    said = call(viewer, "POST", "/api/documents/comment/", {
        "document": letter.pk, "body": "Logo is old."})
    assert said.status_code == 403, said.status_code
    said = call(alice, "POST", "/api/documents/comment/", {
        "document": letter.pk, "body": "Logo is old."})
    assert said.status_code == 201, said.content

    # -- pages ------------------------------------------------------
    task = ReviewTask.objects.filter(assignee__username="quentin").first()
    for client, url in (
        (quentin, "/"),
        (quentin, "/documents/reviewtask/"),
        (quentin, f"/documents/reviewtask/{task.pk}/"),
        (alice, "/documents/review/"),
        (alice, f"/documents/review/{review.pk}/"),
        (alice, f"/documents/review/add/?document={lease.pk}"),
        (alice, "/documents/workflow/"),
        (alice, f"/documents/workflow/{quick.pk}/"),
        (alice, "/documents/workflow/add/"),
        (alice, f"/documents/reviewstep/{final.pk}/"),
        (alice, "/documents/documenttype/"),
        (alice, "/documents/codification/"),
        (manager, "/documents/teamwiki/"),
        (alice, f"/documents/document/{lease.pk}/"),
        (alice, f"/api/documents/review/{review.pk}/summary/"),
        (alice, "/api/documents/review/charts/by_status/"),
    ):
        status = client.get(url).status_code
        assert status == 200, f"{url}: {status}"
    print("ok")
    """)

#: Who writes in which wiki: its editing teams, or whoever reads it.
WIKI_SCENARIO = PRELUDE + textwrap.dedent("""
    from generic.wiki.models import Wiki, WikiPage

    User = get_user_model()

    def writes(name):
        return sorted(
            Wiki.objects.writable_by(User.objects.get(username=name))
            .values_list("slug", flat=True)
        )

    def reads(name):
        return sorted(
            Wiki.objects.readable_by(User.objects.get(username=name))
            .values_list("slug", flat=True)
        )

    # Company: everyone reads, Human resources write.
    assert writes("bob") == ["engineering-handbook"], writes("bob")
    assert writes("carol") == ["hr-handbook", "main"], writes("carol")
    assert writes("alice") == ["engineering-handbook", "legal-handbook"]
    assert len(writes("manager")) == 4
    assert len(writes("admin")) == 4

    bob = signed_in("bob")
    welcome = WikiPage.objects.get(wiki__slug="main", slug="welcome")
    page = bob.get("/wiki/main/welcome/")
    assert page.status_code == 200
    assert page.context["can"]["change"] is False
    refused = bob.patch(
        f"/wiki/api/pages/{welcome.pk}/",
        json.dumps({"title": "Mine"}), content_type="application/json",
    )
    assert refused.status_code == 403, refused.status_code
    assert bob.get("/wiki/engineering-handbook/releases/").context["can"][
        "change"
    ]

    # An editing team reads the wiki it writes in.
    from documents.models import TeamWiki
    from generic.teams.models import Team

    link = TeamWiki.objects.get(wiki__slug="legal-handbook")
    link.editing_teams.add(Team.objects.get(name="Engineering"))
    assert "legal-handbook" in reads("bob")
    assert writes("bob") == ["engineering-handbook", "legal-handbook"]
    # Then Legal's own members read it, and no longer write in it.
    assert "legal-handbook" in reads("viewer")
    assert "legal-handbook" not in writes("viewer")
    print("ok")
    """)


#: Search inside files, published and working versions, the preview,
#: the access log, the trash, folders in folders and periodic reviews.
FEATURES_SCENARIO = PRELUDE + textwrap.dedent("""
    import datetime
    import importlib.util

    from django.utils import timezone
    from documents import periodic, samples, versions
    from documents.models import (
        DocumentType, Review, ReviewTask, Workflow,
    )
    from generic.access.models import AccessEntry
    from generic.models import Notification
    from generic.sites import site
    from generic.teams.models import Team

    User = get_user_model()
    alice, bob, viewer = (
        signed_in("alice"), signed_in("bob"), signed_in("viewer")
    )
    quentin = signed_in("quentin")

    def call(client, method, url, payload=None):
        return client.generic(
            method, url, json.dumps(payload or {}),
            content_type="application/json",
        )

    def rows(client, url, **params):
        return client.get(url, {"draw": 1, "length": 100, **params}).json()[
            "data"
        ]

    def titles(client, **params):
        return sorted(
            row["title"]
            for row in rows(client, "/api/documents/document/", **params)
        )

    # -- search inside files ----------------------------------------
    assert titles(bob, **{"search[value]": "Engineering report cover"}) == [
        "Report template"
    ]
    if importlib.util.find_spec("pypdf"):
        assert titles(bob, **{"search[value]": "Rollback added"}) == [
            "Release procedure"
        ]
    assert titles(alice, **{"search[value]": "Liability capped"}) == []
    assert titles(alice, **{"search[value]": "Signed version"}) == [
        "Supplier framework agreement"
    ]
    # The command reads again what has no text yet.
    Document.objects.update(content="")
    out = __import__("io").StringIO()
    call_command("extract_text", "--all", stdout=out)
    assert Document.objects.exclude(content="").exists(), out.getvalue()

    # -- published and working versions -----------------------------
    framework = Document.objects.get(title="Supplier framework agreement")
    labels = list(
        framework.versions.order_by("number").values_list("label", flat=True)
    )
    assert labels == ["0.1", "0.2", "1.0"], labels
    assert (framework.version_label, framework.published_label) == (
        "1.0", "1.0"
    )

    # A new draft: 1.1, the readers still read 1.0.
    framework.file.save(
        "framework-agreement.docx",
        __import__("django.core.files.base", fromlist=["x"]).ContentFile(
            samples.make("framework-agreement.docx", "Framework",
                         ["Pineapple clause."])
        ),
    )
    versions.record_version(framework, user=User.objects.get(
        username="alice"))
    framework.refresh_from_db()
    assert framework.version_label == "1.1", framework.version_label
    assert framework.published_label == "1.0"
    assert titles(alice, **{"search[value]": "Pineapple"}) == [
        "Supplier framework agreement"
    ]

    files = f"/api/documents/document/{framework.pk}/files"
    assert viewer.get(f"{files}/file/").status_code == 404
    published = viewer.get(f"{files}/published_file/")
    assert published.status_code == 200, published.status_code
    assert b"Pineapple" not in b"".join(published.streaming_content)
    assert alice.get(f"{files}/file/").status_code == 200
    summary = viewer.get(
        f"/api/documents/document/{framework.pk}/summary/"
    ).json()
    assert "Pineapple" not in json.dumps(summary)

    # The readers' list of versions: the published ones.
    def labels_seen(client):
        return {
            row["label"]
            for row in rows(client, "/api/documents/documentversion/")
        }

    assert "1.1" in labels_seen(alice)
    assert "1.1" not in labels_seen(viewer), labels_seen(viewer)
    assert "1.0" in labels_seen(viewer)

    # Approved: 2.0, published.
    approved = call(
        alice, "POST", "/api/documents/document/actions/",
        {"action": "approve", "ids": [framework.pk]},
    )
    assert approved.status_code == 200, approved.content
    framework.refresh_from_db()
    assert (framework.version_label, framework.published_label) == (
        "2.0", "2.0"
    ), framework.version_label
    published = viewer.get(f"{files}/published_file/")
    assert published.status_code == 200

    # An approved PDF is stamped, when pypdf is there.
    release = Document.objects.get(title="Release procedure")
    if importlib.util.find_spec("pypdf"):
        stamped = release.published_version.stamped
        assert stamped and stamped.name.endswith("-1.0.pdf"), stamped
        assert release.published_file == stamped.name

    # -- preview ----------------------------------------------------
    documents = site.get_resource(Document)
    page = bob.get(documents.get_page_url("preview", release))
    assert page.status_code == 200, page.status_code
    inline = bob.get(documents.get_page_url("preview-file", release))
    assert inline.status_code == 200, inline.status_code
    assert inline["Content-Disposition"].startswith("inline")
    assert inline["X-Content-Type-Options"] == "nosniff"
    page = viewer.get(documents.get_page_url("preview", framework))
    assert page.status_code == 200 and b"2.0" in page.content
    assert viewer.get(
        documents.get_page_url("preview-file", framework)
    ).status_code == 404

    # -- access log -------------------------------------------------
    logged = AccessEntry.objects.filter(
        user__username="viewer", object_id=str(framework.pk)
    )
    assert set(logged.values_list("action", flat=True)) == {
        "viewed", "downloaded"
    }, list(logged.values_list("action", "detail"))
    assert logged.filter(detail__startswith="preview").exists()

    # -- trash ------------------------------------------------------
    nda = Document.objects.get(title="Non-disclosure agreement")
    assert ReviewTask.objects.filter(
        document=nda, assignee__username="quentin",
        status=ReviewTask.Status.PENDING,
    ).exists()
    gone = alice.delete(f"/api/documents/document/{nda.pk}/")
    assert gone.status_code == 204, gone.content
    nda.refresh_from_db()
    assert nda.deleted_at is not None
    assert not ReviewTask.objects.filter(
        document=nda, status=ReviewTask.Status.PENDING
    ).exists()
    assert "Non-disclosure agreement" not in titles(alice)
    assert titles(alice, _trash="1") == ["Non-disclosure agreement"]
    assert titles(viewer, _trash="1") == []
    assert "Non-disclosure" not in json.dumps(
        rows(quentin, "/api/documents/reviewtask/")
    )
    restored = call(
        alice, "POST", "/api/documents/document/actions/?_trash=1",
        {"action": "restore_from_trash", "ids": [nda.pk]},
    )
    assert restored.status_code == 200, restored.content
    assert "Non-disclosure agreement" in titles(alice)

    # -- folders in folders -----------------------------------------
    legal = Team.objects.get(name="Legal")
    suppliers = Folder.objects.get(name="Suppliers")
    contracts = Folder.objects.get(name="Contracts")
    assert suppliers.path == "Contracts / Suppliers", suppliers.path
    created = call(alice, "POST", "/api/documents/folder/", {
        "name": "Drafts", "team": legal.pk, "parent": suppliers.pk,
    })
    assert created.status_code == 201, created.content
    drafts = Folder.objects.get(name="Drafts")
    assert drafts.path == "Contracts / Suppliers / Drafts", drafts.path
    twice = call(alice, "POST", "/api/documents/folder/", {
        "name": "Drafts", "team": legal.pk, "parent": suppliers.pk,
    })
    assert twice.status_code == 400 and "name" in twice.json(), twice.content
    elsewhere = call(alice, "POST", "/api/documents/folder/", {
        "name": "Mixed", "team": legal.pk,
        "parent": Folder.objects.get(name="Archive").pk,
    })
    assert elsewhere.status_code == 400, elsewhere.content
    cycle = call(
        alice, "PATCH", f"/api/documents/folder/{contracts.pk}/",
        {"parent": drafts.pk},
    )
    assert cycle.status_code == 400, cycle.content
    renamed = call(
        alice, "PATCH", f"/api/documents/folder/{contracts.pk}/",
        {"name": "Agreements"},
    )
    assert renamed.status_code == 200, renamed.content
    drafts.refresh_from_db()
    assert drafts.path == "Agreements / Suppliers / Drafts", drafts.path

    # -- periodic reviews -------------------------------------------
    today = timezone.localdate()
    assert release.review_on == today + datetime.timedelta(days=10)
    Notification.objects.all().delete()
    first = periodic.run(today)
    assert first.reminded >= 1, first
    told = Notification.objects.filter(user__username="bob")
    assert told.filter(title__contains="Release procedure").exists()
    again = periodic.run(today)
    assert again.reminded == 0, again

    # On the day, the type's workflow starts - unless one is open.
    procedure = DocumentType.objects.get(code="PRC")
    assert procedure.review_workflow is not None
    spec = Document.objects.create(
        title="Deployment checklist",
        folder=Folder.objects.get(name="Procedures"),
        document_type=procedure,
        created_by=User.objects.get(username="bob"),
        review_on=today,
    )
    later = periodic.run(today)
    assert later.started == 1, later
    review = Review.objects.get(document=spec)
    assert review.status == Review.Status.IN_PROGRESS, review.status
    assert periodic.run(today).started == 0
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


def test_documents_are_numbered_and_reviewed_through_workflows():
    result = manage("-c", GED_SCENARIO)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")


def test_editing_teams_write_in_their_wikis():
    result = manage("-c", WIKI_SCENARIO)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")


def test_word_files_are_found_by_format_and_merged():
    pytest.importorskip("docx")
    pytest.importorskip("docxcompose")
    result = manage("-c", MERGE_SCENARIO)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")


def test_files_are_searched_published_previewed_and_trashed():
    result = manage("-c", FEATURES_SCENARIO)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")

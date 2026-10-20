"""The logbook example must keep working.

``logbook/`` is a project of its own - its settings, its ``manage.py``
- so, like the document manager, it is run as one, in a process of its
own, from its folder, on a test database.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

LOGBOOK = Path(__file__).resolve().parent.parent / "logbook"

#: Seeded twice, then walked by each kind of person: the note editor,
#: the timer, the timesheet's allocation, the verification.
SCENARIO = textwrap.dedent("""
    import json
    import os

    os.environ["DJANGO_SETTINGS_MODULE"] = "logsite.settings"

    import django
    from django.conf import settings

    django.setup()
    settings.ALLOWED_HOSTS = ["testserver"]

    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection
    from django.test import Client
    from django.test.utils import setup_test_environment

    setup_test_environment()
    connection.creation.create_test_db(verbosity=0)
    call_command("seed_planner", stdout=open(os.devnull, "w"))
    call_command("seed_planner", stdout=open(os.devnull, "w"))

    from planner.models import Note, NoteLine, Task, TimeEntry

    def signed_in(username):
        client = Client()
        client.force_login(get_user_model().objects.get(username=username))
        return client

    def send(client, method, url, body):
        return getattr(client, method)(
            url, json.dumps(body), content_type="application/json"
        )

    # Seeded once, whatever the number of runs.
    assert Note.objects.count() == 5, Note.objects.count()
    assert Task.objects.count() == 15, Task.objects.count()
    assert TimeEntry.objects.running().count() == 1
    references = set(Task.objects.values_list("reference", flat=True))
    assert "FNC-0001" in references and "DM-0001" in references, references

    admin, bob, viewer = signed_in("admin"), signed_in("bob"), signed_in("viewer")

    # Every page opens.
    note = Note.objects.get(title="Sprint 42 planning")
    task = Task.objects.get(title="One-page checkout")
    entry = TimeEntry.objects.exclude(ended_at=None).first()
    for url in (
        "/",
        "/planner/note/",
        f"/planner/note/{note.pk}/",
        "/planner/note/add/",
        "/planner/task/",
        f"/planner/task/{task.pk}/",
        "/planner/task/board/",
        "/planner/task/people/",
        "/planner/task/due/",
        "/planner/timeentry/",
        "/planner/timeentry/timesheet/",
        f"/planner/timeentry/{entry.pk}/",
        "/planner/timeentry/add/",
        "/planner/project/",
        "/planner/label/",
    ):
        status = bob.get(url).status_code
        assert status == 200, (url, status)

    # The editor reads the note: its lines, their tasks.
    DOCUMENT = f"/planner/note/{note.pk}/document/"
    read = bob.get(DOCUMENT).json()
    assert read["canEdit"] and read["canAddTasks"]
    kinds = [line["kind"] for line in read["lines"]]
    assert kinds.count("task") == 4, kinds
    first_task = next(line for line in read["lines"] if line["task"])
    assert first_task["task"]["reference"].startswith("FNC-")

    # A line typed as a task makes a task, numbered by its kind; a task
    # line renamed renames its task.
    lines = [
        {k: line[k] for k in ("id", "kind", "indent", "text", "done")}
        for line in read["lines"]
    ]
    lines[4]["text"] = "Login fails after a password reset (Safari)"
    lines.append(
        {"kind": "task", "text": "Export the timesheet", "taskKind": "DM"}
    )
    lines.append({"kind": "text", "text": "Just a thought."})
    written = send(bob, "post", DOCUMENT, {"title": note.title, "lines": lines})
    assert written.status_code == 200, written.content
    made = Task.objects.get(title="Export the timesheet")
    assert made.kind == "DM" and made.note == note
    assert made.reference.startswith("DM-")
    assert Task.objects.filter(
        title="Login fails after a password reset (Safari)"
    ).exists()

    # Gone from the note, untouched: the task goes too.
    lines = [
        {k: line[k] for k in ("id", "kind", "indent", "text", "done")}
        for line in written.json()["lines"]
        if not (line["task"] and line["task"]["id"] == made.pk)
    ]
    assert send(
        bob, "post", DOCUMENT, {"title": note.title, "lines": lines}
    ).status_code == 200
    assert not Task.objects.filter(pk=made.pk).exists()

    # A reader reads, and does not write.
    assert viewer.get(DOCUMENT).json()["canEdit"] is False
    assert send(
        viewer, "post", DOCUMENT, {"title": "Mine", "lines": []}
    ).status_code == 403
    assert send(bob, "post", DOCUMENT, {"lines": "nope"}).status_code == 400

    # The timer: one running at a time, the task moving along.
    todo = Task.objects.get(title="Address autocomplete")
    assert todo.status == "todo"
    started = bob.post(f"/planner/task/{todo.pk}/timer/")
    assert started.status_code == 200, started.content
    assert started.json()["running"] is True
    todo.refresh_from_db()
    assert todo.status == "doing"
    user_bob = get_user_model().objects.get(username="bob")
    assert TimeEntry.objects.running().filter(user=user_bob).count() == 1
    stopped = bob.post(f"/planner/task/{todo.pk}/timer/").json()
    assert stopped["running"] is False
    assert not TimeEntry.objects.running().filter(user=user_bob).exists()
    assert viewer.post(f"/planner/task/{todo.pk}/timer/").status_code == 403

    # The timesheet: the tasks under way are offered, one dropped on a
    # time logs an hour of it, for whoever dropped it.
    SHEET = "/api/planner/timeentry/calendars/timesheet/"
    offered = bob.get(SHEET + "sources/").json()["items"]
    assert offered and all(
        Task.objects.get(pk=item["id"]).status in ("todo", "doing", "review")
        for item in offered
    )
    dropped = send(
        bob,
        "post",
        SHEET,
        {"record": offered[0]["id"], "start": "2026-10-07T10:00"},
    )
    assert dropped.status_code == 201, dropped.content
    assert dropped.json()["startsAt"] == "2026-10-07T10:00"
    assert dropped.json()["endsAt"] == "2026-10-07T11:00"
    logged = TimeEntry.objects.get(pk=dropped.json()["id"])
    assert logged.user == user_bob and str(logged.hours) == "1.00"

    # Moved, then made longer, on the hours.
    MOVE = f"/api/planner/timeentry/{logged.pk}/calendars/timesheet/"
    assert send(
        bob, "patch", MOVE, {"start": "2026-10-08T14:00"}
    ).status_code == 200
    assert send(
        bob, "patch", MOVE, {"end": "2026-10-08T16:30"}
    ).status_code == 200
    logged.refresh_from_db()
    assert str(logged.hours) == "2.50", logged.hours
    assert send(
        bob, "patch", MOVE, {"end": "2026-10-08T13:00"}
    ).status_code == 400

    # A reader neither drops nor moves.
    assert viewer.get(SHEET + "sources/").status_code == 200
    assert send(
        viewer, "post", SHEET,
        {"record": offered[0]["id"], "start": "2026-10-07T10:00"},
    ).status_code == 403

    # Verifying is a lead's.
    def run(client, name, ids):
        return send(
            client, "post", "/api/planner/timeentry/actions/",
            {"action": name, "ids": ids},
        )

    assert run(bob, "verify", [logged.pk]).status_code in (400, 403)
    assert run(signed_in("alice"), "verify", [logged.pk]).status_code == 200
    logged.refresh_from_db()
    assert logged.verified and logged.verified_by.username == "alice"

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
        cwd=LOGBOOK,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_notes_tasks_and_time():
    result = manage("-c", SCENARIO)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("ok")


def test_the_checks_find_nothing():
    result = manage("manage.py", "check", "--fail-level", "INFO")

    assert result.returncode == 0, result.stderr
    assert "no issues" in result.stdout


def test_the_migrations_are_up_to_date():
    result = manage("manage.py", "makemigrations", "--check", "--dry-run")

    assert result.returncode == 0, result.stdout + result.stderr

"""Demo data for the logbook: people, notes with their tasks, and time.

Idempotent: the groups and the people are made sure of every time; the
notes, tasks and time only when there are none yet. The time is laid on
the last four weeks, up to now - so the timesheet's current week holds
entries to verify, and one timer runs.

    python manage.py seed_planner
"""

from __future__ import annotations

import datetime
import random
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from planner.models import Label, Note, NoteLine, Project, Task, TimeEntry

PASSWORD = "demo"

#: Group -> model -> what it may do ("verify" is the timesheet's).
ROLES = {
    "Planners": {
        "note": "view add change delete",
        "noteline": "view add change delete",
        "task": "view add change delete",
        "timeentry": "view add change delete",
        "project": "view add change",
        "label": "view add change",
    },
    "Leads": {
        "note": "view add change delete",
        "noteline": "view add change delete",
        "task": "view add change delete",
        "timeentry": "view add change delete verify",
        "project": "view add change delete",
        "label": "view add change delete",
    },
    "Readers": {
        model: "view"
        for model in (
            "note",
            "noteline",
            "task",
            "timeentry",
            "project",
            "label",
        )
    },
}

PEOPLE = (
    # username, first name, last name, group
    ("alice", "Alice", "Martin", "Leads"),
    ("bob", "Bob", "Durand", "Planners"),
    ("viewer", "Victor", "Viewer", "Readers"),
)

PROJECTS = (
    ("Website", "#0ea5e9", "The public site and its shop."),
    ("Mobile app", "#8b5cf6", "The iOS and Android application."),
    ("Internal tools", "#f59e0b", "What the team uses every day."),
)

LABELS = (
    ("meeting", "#2563eb"),
    ("idea", "#16a34a"),
    ("spec", "#9333ea"),
    ("bug", "#dc2626"),
)

#: A note: title, project, labels, pinned, lines. A task line is
#: ("task", kind, title, status, priority, assignee).
NOTES = (
    (
        "Sprint 42 planning",
        "Website",
        ("meeting",),
        True,
        (
            ("heading", "Goals"),
            ("bullet", "Ship the new checkout before the 15th"),
            ("bullet", "Fix the login regressions reported last week"),
            ("heading", "Tasks"),
            (
                "task",
                "FNC",
                "Login fails after a password reset",
                "doing",
                "urgent",
                "alice",
            ),
            (
                "task",
                "FNC",
                "Cart total ignores the discount code",
                "todo",
                "high",
                "bob",
            ),
            ("task", "DM", "One-page checkout", "doing", "high", "bob"),
            (
                "task",
                "DM",
                "Keep the cart between visits",
                "backlog",
                "normal",
                "alice",
            ),
            ("heading", "Follow-up"),
            ("check", "Ask Marie for the payment sandbox keys", True),
            ("check", "Book the demo room for Friday"),
            ("text", "Next review on Thursday at 10:00."),
        ),
    ),
    (
        "Checkout - specification",
        "Website",
        ("spec",),
        False,
        (
            ("heading", "Scope"),
            (
                "text",
                "One page from the cart to the payment: address, delivery, "
                "payment, review.",
            ),
            ("bullet", "Guests may pay without an account"),
            ("bullet", "The address is checked as it is typed"),
            ("task", "DM", "Address autocomplete", "todo", "normal", "bob"),
            (
                "task",
                "DM",
                "Pay by card in one step",
                "review",
                "high",
                "alice",
            ),
            ("heading", "Out of scope"),
            ("bullet", "Gift cards"),
            ("bullet", "Several delivery addresses"),
        ),
    ),
    (
        "Mobile app - bug triage",
        "Mobile app",
        ("bug", "meeting"),
        False,
        (
            ("text", "Reported by the support desk this month."),
            (
                "task",
                "FNC",
                "Crash when the camera permission is refused",
                "done",
                "urgent",
                "bob",
            ),
            (
                "task",
                "FNC",
                "Push notifications arrive twice",
                "doing",
                "high",
                "alice",
            ),
            (
                "task",
                "FNC",
                "Dark mode: labels unreadable",
                "todo",
                "normal",
                "bob",
            ),
            ("check", "Reply to the three customers who wrote", True),
            ("check", "Add a test on the notification service"),
        ),
    ),
    (
        "Ideas",
        "",
        ("idea",),
        True,
        (
            ("bullet", "A weekly summary mail of what moved"),
            ("bullet", "Tags on tasks, as on notes"),
            ("bullet", "Templates of notes for meetings"),
            (
                "task",
                "DM",
                "Offline mode for the app",
                "backlog",
                "low",
                "alice",
            ),
        ),
    ),
    (
        "Internal tools - weekly",
        "Internal tools",
        ("meeting",),
        False,
        (
            ("heading", "Done since last week"),
            ("bullet", "The new backup job runs every night"),
            ("heading", "This week"),
            (
                "task",
                "FNC",
                "The Excel export times out",
                "todo",
                "high",
                "bob",
            ),
            ("task", "DM", "Single sign-on", "backlog", "normal", "alice"),
            ("check", "Renew the certificate before the 30th"),
        ),
    ),
)

#: Tasks written straight on the board, in no note.
LOOSE_TASKS = (
    ("FNC", "Broken link in the footer", "done", "low", "bob", "Website"),
    ("DM", "Admin dashboard", "review", "normal", "alice", "Internal tools"),
    ("FNC", "Slow search on product pages", "todo", "normal", "", "Website"),
)

COMMENTS = (
    "",
    "",
    "Pairing session",
    "Investigation",
    "Code review",
    "Tests",
    "Call with the customer",
)


class Command(BaseCommand):
    help = "Create the logbook's demo people, notes, tasks and time."

    def handle(self, *args: Any, **options: Any) -> None:
        with transaction.atomic():
            groups = self.groups()
            people = self.people(groups)

            if Project.objects.exists():
                self.stdout.write("Demo data already there; people checked.")
                return

            projects = {
                name: Project.objects.create(
                    name=name, color=color, description=description
                )
                for name, color, description in PROJECTS
            }
            labels = {
                name: Label.objects.create(name=name, color=color)
                for name, color in LABELS
            }
            self.notes(projects, labels, people)
            self.loose_tasks(projects, people)
            self.time(people)

        self.stdout.write(
            self.style.SUCCESS(
                f"{Note.objects.count()} notes, {Task.objects.count()} tasks, "
                f"{TimeEntry.objects.count()} time entries. "
                f"Sign in as admin, alice, bob or viewer (password "
                f"{PASSWORD!r})."
            )
        )

    def groups(self) -> dict[str, Group]:
        groups = {}

        for name, models in ROLES.items():
            group, _created = Group.objects.get_or_create(name=name)
            codenames = [
                f"{action}_{model}"
                for model, actions in models.items()
                for action in actions.split()
            ]
            # And who the people are: tasks are given to them, time is
            # theirs - picking one reads the People screen's users.
            group.permissions.set(
                Permission.objects.filter(
                    content_type__app_label="planner", codename__in=codenames
                )
                | Permission.objects.filter(
                    content_type__app_label="auth", codename="view_user"
                )
            )
            groups[name] = group

        return groups

    def people(self, groups: dict[str, Group]) -> dict[str, Any]:
        User = get_user_model()
        people = {}
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "is_staff": True,
                "is_superuser": True,
                "first_name": "Ada",
                "last_name": "Admin",
            },
        )

        if created:
            admin.set_password(PASSWORD)
            admin.save()

        people["admin"] = admin

        for username, first, last, group in PEOPLE:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last},
            )

            if created:
                user.set_password(PASSWORD)
                user.save()

            user.groups.set([groups[group]])
            people[username] = user

        return people

    def notes(self, projects: dict, labels: dict, people: dict) -> None:
        now = timezone.now()

        for age, (title, project, tags, pinned, lines) in enumerate(NOTES):
            note = Note.objects.create(
                title=title,
                project=projects.get(project),
                pinned=pinned,
                author=people["alice"],
            )
            note.labels.set([labels[name] for name in tags])

            for position, line in enumerate(lines):
                kind = line[0]
                item = NoteLine(note=note, position=position, kind=kind)

                if kind == "task":
                    _kind, task_kind, text, status, priority, who = line
                    item.text = text
                    item.task = Task.objects.create(
                        kind=task_kind,
                        title=text,
                        note=note,
                        project=note.project,
                        status=status,
                        priority=priority,
                        assignee=people.get(who),
                        estimate=8 if task_kind == "DM" else 3,
                    )
                else:
                    item.text = line[1]
                    item.done = len(line) > 2 and bool(line[2])

                item.save()

            # Older notes first: "updated at" spreads them over a week.
            Note.objects.filter(pk=note.pk).update(
                updated_at=now - datetime.timedelta(days=age, hours=age)
            )

    def loose_tasks(self, projects: dict, people: dict) -> None:
        for kind, title, status, priority, who, project in LOOSE_TASKS:
            Task.objects.create(
                kind=kind,
                title=title,
                status=status,
                priority=priority,
                assignee=people.get(who),
                project=projects[project],
                due_on=timezone.localdate() + datetime.timedelta(days=5),
            )

    def time(self, people: dict) -> None:
        """Four weeks of working days, mornings and afternoons cut into
        pieces of work, for alice and bob; the past checked, this week
        not yet, and alice's timer running."""
        chance = random.Random(42)
        today = timezone.localdate()
        monday = today - datetime.timedelta(days=today.weekday())
        first = monday - datetime.timedelta(weeks=3)
        now = timezone.localtime()
        lead = people["alice"]
        entries = []

        for username in ("alice", "bob"):
            user = people[username]
            tasks = list(
                Task.objects.filter(assignee=user).exclude(status="backlog")
            ) or list(Task.objects.exclude(status="backlog"))
            day = first

            while day <= today:
                if day.weekday() < 5:
                    for start, stop in (
                        ((9, 0), (12, 30)),
                        ((13, 30), (18, 0)),
                    ):
                        moment = self.at(day, *start) + datetime.timedelta(
                            minutes=chance.choice((0, 0, 15, 30))
                        )
                        end_of_block = self.at(day, *stop)

                        while moment < end_of_block - datetime.timedelta(
                            minutes=30
                        ):
                            length = datetime.timedelta(
                                minutes=chance.choice((45, 60, 90, 105, 120))
                            )
                            ended = min(moment + length, end_of_block)

                            if ended > now - datetime.timedelta(hours=1):
                                break

                            verified = day < monday
                            entries.append(
                                TimeEntry(
                                    task=chance.choice(tasks),
                                    user=user,
                                    started_at=moment,
                                    ended_at=ended,
                                    comment=chance.choice(COMMENTS),
                                    verified=verified,
                                    verified_by=lead if verified else None,
                                    verified_at=(
                                        ended + datetime.timedelta(days=3)
                                        if verified
                                        else None
                                    ),
                                )
                            )
                            moment = ended + datetime.timedelta(
                                minutes=chance.choice((0, 0, 15))
                            )

                day += datetime.timedelta(days=1)

        for entry in entries:
            entry.save()

        # Somebody is at work right now.
        busy = Task.objects.filter(status="doing", assignee=lead).first()

        if busy is not None:
            TimeEntry.objects.create(
                task=busy,
                user=lead,
                started_at=timezone.now() - datetime.timedelta(minutes=50),
            )

    @staticmethod
    def at(day: datetime.date, hour: int, minute: int) -> datetime.datetime:
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, minute))
        )

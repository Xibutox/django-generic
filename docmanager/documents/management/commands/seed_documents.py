"""Demonstration data: teams, people, folders, documents and versions.

    python manage.py seed_documents

Every account's password is ``demo``. Running it again changes nothing
already there: the people and teams are found by name, and documents
are only added to a folder that has none.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from documents import samples, versions
from documents.models import Document, Folder, Tag
from generic.history import acting_as
from generic.teams.models import Team

TEAMS = {
    "Legal": "#7c3aed",
    "Engineering": "#0891b2",
    "Human resources": "#db2777",
}

#: username: (first name, teams, group)
PEOPLE = {
    "alice": ("Alice", ("Legal", "Engineering"), "Editors"),
    "bob": ("Bob", ("Engineering",), "Editors"),
    "carol": ("Carol", ("Human resources",), "Editors"),
    "viewer": ("Victor", ("Legal",), "Readers"),
    "manager": ("Maria", (), "Managers"),
}

TAGS = {
    "contract": "#7c3aed",
    "procedure": "#0891b2",
    "template": "#ca8a04",
    "confidential": "#dc2626",
}

#: team: {folder: [(title, status, tags, [(file name, note), ...])]}
DOCUMENTS = {
    "Legal": {
        "Contracts": [
            (
                "Supplier framework agreement",
                Document.Status.APPROVED,
                ("contract",),
                [
                    ("framework-agreement.docx", "First draft."),
                    ("framework-agreement.docx", "Liability capped."),
                    ("framework-agreement.docx", "Signed version."),
                ],
            ),
            (
                "Non-disclosure agreement",
                Document.Status.REVIEW,
                ("contract", "confidential"),
                [("nda.docx", "From the legal template.")],
            ),
        ],
        "Templates": [
            (
                "Letter template",
                Document.Status.APPROVED,
                ("template",),
                [
                    ("letter.dotx", "Company letterhead."),
                    ("letter.dotx", "New address."),
                ],
            ),
        ],
    },
    "Engineering": {
        "Procedures": [
            (
                "Release procedure",
                Document.Status.APPROVED,
                ("procedure",),
                [
                    ("release-procedure.pdf", "Written down."),
                    ("release-procedure.pdf", "Rollback added."),
                ],
            ),
            (
                "Architecture notes",
                Document.Status.DRAFT,
                (),
                [("architecture.md", "Started.")],
            ),
        ],
        "Templates": [
            (
                "Report template",
                Document.Status.APPROVED,
                ("template",),
                [("report.dotx", "Engineering report cover.")],
            ),
        ],
    },
    "Human resources": {
        "Onboarding": [
            (
                "Welcome guide",
                Document.Status.REVIEW,
                ("procedure",),
                [
                    ("welcome-guide.docx", "First version."),
                    ("welcome-guide.docx", "Holidays section."),
                ],
            ),
            (
                "Salary grid",
                Document.Status.APPROVED,
                ("confidential",),
                [("salary-grid.pdf", "2026 grid.")],
            ),
        ],
    },
}

EDITOR_MODELS = ("folder", "document", "documentversion", "tag")


def permissions(*codenames: str) -> list[Permission]:
    return list(
        Permission.objects.filter(
            content_type__app_label__in=("documents", "generic_teams"),
            codename__in=codenames,
        )
    )


class Command(BaseCommand):
    help = "Teams, people, folders and documents to try the example with."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        groups = self.groups()
        teams = {
            name: Team.objects.get_or_create(
                name=name, defaults={"color": color}
            )[0]
            for name, color in TEAMS.items()
        }
        User = get_user_model()

        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={"is_staff": True, "is_superuser": True},
        )
        if created:
            admin.set_password("demo")
            admin.save()

        for username, (first_name, team_names, group) in PEOPLE.items():
            user, created = User.objects.get_or_create(
                username=username, defaults={"first_name": first_name}
            )
            if created:
                user.set_password("demo")
                user.save()
            user.groups.add(groups[group])

            for name in team_names:
                teams[name].members.add(user)

        tags = {
            name: Tag.objects.get_or_create(
                name=name, defaults={"color": color}
            )[0]
            for name, color in TAGS.items()
        }

        for team_name, folders in DOCUMENTS.items():
            for folder_name, documents in folders.items():
                folder, _created = Folder.objects.get_or_create(
                    team=teams[team_name], name=folder_name
                )

                if folder.documents.exists():
                    continue

                for title, status, tag_names, files in documents:
                    document = self.document(folder, title, status, files)
                    document.tags.set([tags[name] for name in tag_names])

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded. Sign in as admin, alice, bob, carol, viewer or "
                "manager - password demo."
            )
        )

    def groups(self) -> dict[str, Group]:
        editors = Group.objects.get_or_create(name="Editors")[0]
        editors.permissions.set(
            permissions(
                *(
                    f"{verb}_{model}"
                    for model in EDITOR_MODELS
                    for verb in ("view", "add", "change", "delete")
                ),
                "view_team",
            )
        )
        readers = Group.objects.get_or_create(name="Readers")[0]
        readers.permissions.set(
            permissions(
                *(f"view_{model}" for model in EDITOR_MODELS), "view_team"
            )
        )
        managers = Group.objects.get_or_create(name="Managers")[0]
        managers.permissions.set(
            permissions(
                *(
                    f"{verb}_{model}"
                    for model in (*EDITOR_MODELS, "team")
                    for verb in ("view", "add", "change", "delete")
                ),
                "see_every_team",
            )
        )

        return {"Editors": editors, "Readers": readers, "Managers": managers}

    def document(self, folder, title, status, files) -> Document:
        editor = folder.team.members.order_by("username").first()
        document = None

        with acting_as(editor, source="seed_documents"):
            for index, (name, note) in enumerate(files, start=1):
                content = ContentFile(
                    samples.make(
                        name,
                        title,
                        [note, f"Version {index}.", folder.team.name],
                    ),
                    name=name,
                )

                if document is None:
                    document = Document(
                        title=title,
                        folder=folder,
                        status=status,
                        created_by=editor,
                    )
                    document.file.save(name, content, save=False)
                    document.save()
                else:
                    document.file.save(name, content)

                versions.record_version(
                    document, user=editor, comment=note, file_name=name
                )
                document.refresh_from_db()

        return document

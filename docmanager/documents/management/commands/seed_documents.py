"""Demonstration data: teams and their leaders, people, folders,
documents and versions, numbers, review circuits and reviews under
way, and a wiki per team beside one for everyone.

    python manage.py seed_documents
    python manage.py seed_documents --roles-only

Every account's password is ``demo``. Running it again changes nothing
already there: the people and teams are found by name, and documents
are only added to a folder that has none.

``--roles-only`` makes the groups alone - Editors, Readers, Quality
and Managers, with their permissions - for a document manager that
starts empty (DEMO_DATA=0 in the Docker stack).
"""

from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone
from django.utils.text import slugify

from documents import codification, samples, versions, workflows
from documents.models import (
    Codification,
    Document,
    DocumentType,
    Folder,
    Review,
    ReviewTask,
    StepKind,
    StepRule,
    Tag,
    TeamWiki,
    Workflow,
    WorkflowStep,
)
from generic.history import acting_as
from generic.teams.models import Team
from generic.wiki.models import DEFAULT_WIKI_SLUG, Wiki, WikiPage

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
    # In no team: reads what the reviews ask of him, as a role.
    "quentin": ("Quentin", (), "Quality"),
}

#: team: (leaders, code, pattern, number every new document)
CODIFICATION = {
    "Legal": (("alice",), "LEG", "{team}-{type}-{year}-{seq:04}", True),
    "Engineering": (("bob",), "ENG", "ENG/{type}/{seq:05}", False),
    "Human resources": (
        ("carol",),
        "HR",
        "{team}-{yy}{month}-{seq:03}",
        False,
    ),
}

#: name: (code, colour)
TYPES = {
    "Contract": ("CTR", "#7c3aed"),
    "Procedure": ("PRC", "#0891b2"),
    "Template": ("TPL", "#ca8a04"),
    "Guide": ("GDE", "#db2777"),
    "Note": ("NOT", "#64748b"),
}

#: type: (every so many months, periodic review workflow)
PERIODIC = {
    "Procedure": (12, "Procedure validation"),
    "Contract": (24, None),
}

#: team: [(folder, subfolder)] - folders inside folders.
SUBFOLDERS = {
    "Legal": [("Contracts", "Suppliers")],
    "Engineering": [("Procedures", "Archive")],
}

#: A document's type, by its title.
TYPE_OF = {
    "Supplier framework agreement": "Contract",
    "Non-disclosure agreement": "Contract",
    "Supplier contract 2027": "Contract",
    "Letter template": "Template",
    "Release procedure": "Procedure",
    "Architecture notes": "Note",
    "Report template": "Template",
    "Welcome guide": "Guide",
    "Salary grid": "Note",
}

#: name: (team or None, description, [(name, kind, rule, people, roles,
#: leaders, members, days)])
WORKFLOWS = {
    "Quick approval": (
        None,
        "One step: the team's leaders approve.",
        [
            (
                "Approval",
                StepKind.APPROVAL,
                StepRule.ANY,
                (),
                (),
                True,
                False,
                3,
            ),
        ],
    ),
    "Contract review": (
        "Legal",
        "A lawyer and quality read it, then a manager signs it off.",
        [
            (
                "Legal and quality review",
                StepKind.REVIEW,
                StepRule.ALL,
                ("viewer",),
                ("Quality",),
                False,
                False,
                5,
            ),
            (
                "Sign-off",
                StepKind.APPROVAL,
                StepRule.ANY,
                ("manager",),
                (),
                False,
                False,
                2,
            ),
        ],
    ),
    "Procedure validation": (
        "Engineering",
        "Reviewed by the leaders, approved by quality, read by the team.",
        [
            (
                "Technical review",
                StepKind.REVIEW,
                StepRule.ANY,
                (),
                (),
                True,
                False,
                5,
            ),
            (
                "Quality approval",
                StepKind.APPROVAL,
                StepRule.ANY,
                (),
                ("Quality",),
                False,
                False,
                3,
            ),
            (
                "Read by the team",
                StepKind.ACKNOWLEDGEMENT,
                StepRule.ALL,
                (),
                (),
                False,
                True,
                10,
            ),
        ],
    ),
}

#: Reviews under way: (document, workflow, starter, message, answers),
#: an answer being (username, approve, comment).
REVIEWS = [
    (
        "Non-disclosure agreement",
        "Contract review",
        "alice",
        "Standard NDA for the new supplier - please check clause 4.",
        [("viewer", True, "Clause 4 is fine.")],
    ),
    (
        "Welcome guide",
        "Quick approval",
        "carol",
        "Holidays section added.",
        [],
    ),
    (
        "Release procedure",
        "Procedure validation",
        "alice",
        "Rollback added: who approves?",
        [("bob", True, "Tested on staging.")],
    ),
]

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

EDITOR_MODELS = (
    "folder",
    "document",
    "documentversion",
    "tag",
    "comment",
    "workflow",
    "workflowstep",
    "review",
    "reviewstep",
)
#: What everyone reads beside: the settings of the numbering.
SETTINGS_MODELS = ("documenttype", "codification")
WIKI_PAGE = tuple(
    f"{verb}_wikipage" for verb in ("view", "add", "change", "delete")
)

#: wiki: (team or None for everyone's, editing teams, description,
#: pages). A page is (address, title, parent's address, HTML).
WIKIS = {
    "Company": (
        None,
        ("Human resources",),
        "What everyone needs to know.",
        [
            (
                "welcome",
                "Welcome",
                None,
                "<p>Each team keeps its documents in its folders and its "
                "know-how in its wiki. This one is everyone's to read; "
                "Human resources write it.</p>",
            ),
            (
                "naming-files",
                "Naming files",
                "welcome",
                "<ul><li>Lower case, dashes between words.</li><li>No "
                "version in the name: the document keeps its versions."
                "</li></ul>",
            ),
        ],
    ),
    "Legal handbook": (
        "Legal",
        (),
        "How the legal team works.",
        [
            (
                "contract-review",
                "Contract review",
                None,
                "<ol><li>Upload the draft to <em>Contracts</em>: it gets "
                "its number, LEG-CTR-...</li><li><em>Send for review</em>"
                " with the <strong>Contract review</strong> workflow."
                "</li><li>Merge it into the letter template to send it."
                "</li></ol>",
            ),
        ],
    ),
    "Engineering handbook": (
        "Engineering",
        (),
        "Procedures and conventions of the engineering team.",
        [
            (
                "releases",
                "Releases",
                None,
                "<p>Follow the <em>Release procedure</em> document; note "
                "each release here.</p>",
            ),
            (
                "on-call",
                "On call",
                "releases",
                "<p>One engineer a week, named on Monday.</p>",
            ),
        ],
    ),
    "HR handbook": (
        "Human resources",
        ("Human resources",),
        "Onboarding and people matters - the HR team's only.",
        [
            (
                "onboarding",
                "Onboarding",
                None,
                "<p>Send the <em>Welcome guide</em> the week before the "
                "first day.</p>",
            ),
        ],
    ),
}


def permissions(*codenames: str) -> list[Permission]:
    return list(
        Permission.objects.filter(
            content_type__app_label__in=(
                "documents",
                "generic_teams",
                "generic_wiki",
                "auth",
            ),
            codename__in=codenames,
        )
    )


class Command(BaseCommand):
    help = "Teams, people, folders and documents to try the example with."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--roles-only",
            action="store_true",
            help="Only the groups and their permissions: no demo data.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        groups = self.groups()

        if options["roles_only"]:
            self.stdout.write(f"Groups: {', '.join(groups)}.")
            return

        teams = {
            name: Team.objects.get_or_create(
                name=name, defaults={"color": color}
            )[0]
            for name, color in TEAMS.items()
        }
        User = get_user_model()

        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "is_staff": True,
                "is_superuser": True,
                "email": "admin@example.com",
            },
        )
        if created:
            admin.set_password("demo")
            admin.save()

        for username, (first_name, team_names, group) in PEOPLE.items():
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first_name,
                    # Where the reviews' e-mails go: the console, here.
                    "email": f"{username}@example.com",
                },
            )
            if created:
                user.set_password("demo")
                user.save()
            user.groups.add(groups[group])

            for name in team_names:
                teams[name].members.add(user)

        for team_name, (
            leaders,
            code,
            pattern,
            on_create,
        ) in CODIFICATION.items():
            team = teams[team_name]
            team.leaders.add(*User.objects.filter(username__in=leaders))
            Codification.objects.get_or_create(
                team=team,
                defaults={
                    "code": code,
                    "pattern": pattern,
                    "on_create": on_create,
                },
            )

        kinds = {
            name: DocumentType.objects.get_or_create(
                name=name, defaults={"code": code, "color": color}
            )[0]
            for name, (code, color) in TYPES.items()
        }
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
                    document = self.document(
                        folder, title, status, files, kinds[TYPE_OF[title]]
                    )
                    document.tags.set([tags[name] for name in tag_names])

        for team_name, pairs in SUBFOLDERS.items():
            for parent_name, name in pairs:
                parent = Folder.objects.get(
                    team=teams[team_name], name=parent_name, parent=None
                )
                Folder.objects.get_or_create(
                    team=teams[team_name], parent=parent, name=name
                )

        self.placeholder(kinds["Contract"], teams["Legal"])
        # Every seeded document numbered, by its team's pattern.
        for document in Document.objects.filter(code__isnull=True).order_by(
            "pk"
        ):
            codification.codify(document)

        with override_settings(DOCUMENT_REVIEW_CHANNELS=["notification"]):
            self.workflows(teams)

        self.periodic(kinds)
        # Files sent before their text was read: read now.
        versions.fill_text()

        self.wikis(teams, admin)
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded. Sign in as admin, alice, bob, carol, viewer, "
                "quentin or manager - password demo."
            )
        )

    def periodic(self, kinds: dict[str, DocumentType]) -> None:
        """Types read again every so often - and the release procedure
        due soon, to see the reminders (*Tasks* > *Periodic reviews*)."""
        for name, (months, workflow) in PERIODIC.items():
            kind = kinds[name]

            if kind.review_months is None:
                kind.review_months = months
                kind.review_workflow = (
                    Workflow.objects.filter(name=workflow).first()
                    if workflow
                    else None
                )
                kind.save(update_fields=("review_months", "review_workflow"))

        Document.objects.filter(
            title="Release procedure", review_on__isnull=True
        ).update(review_on=timezone.localdate() + datetime.timedelta(days=10))

    def placeholder(self, kind: DocumentType, team: Team) -> None:
        """A number reserved for a contract not written yet: no file."""
        folder = Folder.objects.get(team=team, name="Contracts")
        editor = team.members.order_by("username").first()

        with acting_as(editor, source="seed_documents"):
            Document.objects.get_or_create(
                title="Supplier contract 2027",
                folder=folder,
                defaults={
                    "document_type": kind,
                    "description": "To be written once the tender ends; "
                    "its number is already on the purchase order.",
                    "created_by": editor,
                },
            )

    def workflows(self, teams: dict[str, Team]) -> None:
        User = get_user_model()

        for name, (team, description, steps) in WORKFLOWS.items():
            workflow, created = Workflow.objects.get_or_create(
                name=name,
                defaults={
                    "team": teams[team] if team else None,
                    "description": description,
                },
            )

            if not created:
                continue

            for position, (
                step_name,
                kind,
                rule,
                people,
                roles,
                leaders,
                members,
                days,
            ) in enumerate(steps, start=1):
                step = WorkflowStep.objects.create(
                    workflow=workflow,
                    position=position,
                    name=step_name,
                    kind=kind,
                    rule=rule,
                    team_leaders=leaders,
                    team_members=members,
                    days=days,
                )
                step.users.set(User.objects.filter(username__in=people))
                step.groups.set(Group.objects.filter(name__in=roles))

        if Review.objects.exists():
            return

        for title, workflow, starter, message, answers in REVIEWS:
            user = User.objects.get(username=starter)
            review = Review.objects.create(
                document=Document.objects.get(title=title),
                workflow=Workflow.objects.get(name=workflow),
                message=message,
                started_by=user,
            )
            workflows.start(review, user=user)

            for username, approve, comment in answers:
                task = ReviewTask.objects.get(
                    review=review,
                    assignee__username=username,
                    status=ReviewTask.Status.PENDING,
                )
                workflows.decide(
                    task,
                    user=task.assignee,
                    approve=approve,
                    comment=comment,
                )

    def wikis(self, teams: dict[str, Team], author) -> None:
        for position, (
            name,
            (team, editing, description, pages),
        ) in enumerate(WIKIS.items()):
            # Everyone's wiki is the first one, the framework's own "main"
            # - made by its migrations - renamed while still empty.
            slug = DEFAULT_WIKI_SLUG if team is None else slugify(name)
            wiki, created = Wiki.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "description": description,
                    "position": position,
                },
            )

            if not created and wiki.name == "Wiki" and not wiki.pages.exists():
                wiki.name, wiki.description = name, description
                wiki.save(update_fields=("name", "description"))

            if team or editing:
                link, created = TeamWiki.objects.get_or_create(
                    wiki=wiki, defaults={"team": teams[team] if team else None}
                )

                if created:
                    link.editing_teams.set([teams[name] for name in editing])

            for order, (slug, title, parent, content) in enumerate(pages):
                WikiPage.objects.get_or_create(
                    wiki=wiki,
                    slug=slug,
                    defaults={
                        "title": title,
                        "parent": (
                            WikiPage.objects.filter(
                                wiki=wiki, slug=parent
                            ).first()
                            if parent
                            else None
                        ),
                        "position": order,
                        "content": content,
                        "created_by": author,
                        "updated_by": author,
                    },
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
                *(f"view_{model}" for model in SETTINGS_MODELS),
                "view_team",
                *WIKI_PAGE,
            )
        )
        readers = Group.objects.get_or_create(name="Readers")[0]
        readers.permissions.set(
            permissions(
                *(f"view_{model}" for model in EDITOR_MODELS),
                *(f"view_{model}" for model in SETTINGS_MODELS),
                "view_team",
                "view_wikipage",
            )
        )
        # A role reviews are asked of: reads, and writes a comment.
        quality = Group.objects.get_or_create(name="Quality")[0]
        quality.permissions.set(
            permissions(
                *(f"view_{model}" for model in EDITOR_MODELS),
                *(f"view_{model}" for model in SETTINGS_MODELS),
                "add_comment",
                "view_wikipage",
            )
        )
        managers = Group.objects.get_or_create(name="Managers")[0]
        managers.permissions.set(
            permissions(
                *(
                    f"{verb}_{model}"
                    for model in (
                        *EDITOR_MODELS,
                        *SETTINGS_MODELS,
                        "team",
                        "teamwiki",
                        "wiki",
                    )
                    for verb in ("view", "add", "change", "delete")
                ),
                *WIKI_PAGE,
                "see_every_team",
            )
        )

        return {
            "Editors": editors,
            "Readers": readers,
            "Managers": managers,
            "Quality": quality,
        }

    def document(self, folder, title, status, files, kind) -> Document:
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
                        document_type=kind,
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

            # Approved already: its last version is the published one.
            if status == Document.Status.APPROVED:
                versions.publish(document, user=editor)
                document.refresh_from_db()

        return document

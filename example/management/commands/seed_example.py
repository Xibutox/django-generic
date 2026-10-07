"""Fill the example with something worth clicking through.

Creates three users so the permission behaviour can be seen:

    admin   superuser, sees everything
    viewer  works tickets and logs time: the ticket, comment and time
            entry permissions, and read access to customers, teams,
            agents and tags so the relation fields can search them
    guest   holds nothing: every page answers 403

All three share the password ``demo``. Throwaway local accounts.

And a desk big enough for the summary pages to mean something: a few
large customers carry most of the 240 tickets, and every ticket has its
comments and its time entries. Running the command again tops up what
is missing without touching what is there.
"""

from __future__ import annotations

import datetime
import random
from decimal import Decimal
from typing import Any

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from example.models import (
    Agent,
    Article,
    ArticleFamily,
    BomLine,
    Customer,
    Equipment,
    Maintenance,
    Supplier,
    Tag,
    Team,
    Ticket,
    TicketComment,
    TimeEntry,
)
from generic.events.models import Message, Notification, NotificationLevel

TICKET_COUNT = 240

TEAMS = [
    ("Front office", "FO"),
    ("Infrastructure", "INFRA"),
    ("Data platform", "DATA"),
]

AGENTS = [
    "Camille Rousseau",
    "Yanis Bertrand",
    "Norah Lef\u00e8vre",
    "Tomas Klein",
    "Aur\u00e9lie Meunier",
    "Sofiane Bakri",
    "Elena Vasquez",
    "Marek Nowak",
]

CUSTOMERS = [
    (
        "Northwind Traders",
        "NWT",
        "enterprise",
        "Lyon",
        "https://northwind.example",
    ),
    (
        "Contoso Pharma",
        "CTP",
        "enterprise",
        "Basel",
        "https://contoso.example",
    ),
    (
        "Ville de Grenoble",
        "VDG",
        "public",
        "Grenoble",
        "https://grenoble.example",
    ),
    ("Fabrikam Studio", "FAB", "small", "Nantes", "https://fabrikam.example"),
    ("Tailspin Travel", "TST", "small", "Bordeaux", ""),
    (
        "Adatum Logistics",
        "ADL",
        "enterprise",
        "Lille",
        "https://adatum.example",
    ),
    ("R\u00e9gion Occitanie", "OCC", "public", "Toulouse", ""),
    ("Litware Labs", "LWL", "small", "Rennes", ""),
]

#: How often each customer raises a ticket: two large accounts carry
#: most of them, as in life - and as a summary page needs.
CUSTOMER_WEIGHTS = [30, 18, 12, 10, 8, 10, 7, 5]

#: Name, colour, background. Some tags only have a colour, which tints
#: them; others a background, drawn exactly: both styles show.
TAGS = [
    ("regression", "#dc2626", ""),
    ("hardware", "#0891b2", ""),
    ("billing", "#78350f", "#fde68a"),
    ("security", "#ffffff", "#7c3aed"),
    ("onboarding", "#16a34a", ""),
]

SUBJECTS = [
    "Login fails after password reset",
    "Invoice PDF is blank",
    "VPN drops every ten minutes",
    "Export times out on large accounts",
    "Two-factor codes rejected",
    "Nightly sync left duplicates",
    "Printer queue stuck",
    "Dashboard shows stale figures",
    "New joiner has no mailbox",
    "Backup job failed silently",
    "Search returns nothing for accents",
    "Mobile app crashes on upload",
    "Rate limit hit during import",
    "Certificate expires next week",
    "Report totals do not reconcile",
    "Slow response on the tickets page",
    "Webhook retries never stop",
    "Access revoked for a leaver",
]

COMMENTS = [
    "Reproduced on staging.",
    "Waiting on the customer for logs.",
    "Rolled back the last deploy.",
    "Escalated to the platform team.",
    "Fix merged, awaiting release.",
    "Cannot reproduce on the current build.",
]

WORK = [
    "Investigation",
    "Call with the customer",
    "Fix and deploy",
    "Testing on staging",
    "Writing the post-mortem",
    "Waiting on a supplier",
]

#: What the viewer may do: work tickets, their comments and their time,
#: and look up the records a ticket points at.
VIEWER_PERMISSIONS = (
    "view_ticket",
    "add_ticket",
    "change_ticket",
    "delete_ticket",
    "view_ticketcomment",
    "add_ticketcomment",
    "change_ticketcomment",
    "delete_ticketcomment",
    "view_timeentry",
    "add_timeentry",
    "change_timeentry",
    "delete_timeentry",
    "view_customer",
    "view_team",
    "view_agent",
    "view_tag",
    # The equipment, read: its pages are worked out from the models.
    "view_supplier",
    "view_equipment",
    "view_maintenance",
    # The articles and their bills, read: the trees, without the Add.
    "view_article",
    "view_articlefamily",
    "view_bomline",
)

SUPPLIERS = [
    (
        "Bureau Direct",
        "orders@bureau-direct.example",
        "+33 4 72 00 10 10",
        "https://bureau-direct.example",
        "France",
        True,
    ),
    (
        "Nordic Devices",
        "sales@nordic-devices.example",
        "+46 8 555 010 20",
        "https://nordic-devices.example",
        "Sweden",
        False,
    ),
    (
        "Headway Audio",
        "contact@headway.example",
        "+44 20 7946 0101",
        "https://headway.example",
        "United Kingdom",
        False,
    ),
    (
        "Pixel Works",
        "hello@pixel-works.example",
        "+49 30 5550 1234",
        "https://pixel-works.example",
        "Germany",
        True,
    ),
]

#: What each kind of equipment is, who sells it and what it costs.
EQUIPMENT = {
    "laptop": (
        ["ThinkBook 14", "Latitude 5440", "MacBook Air 13"],
        ["Bureau Direct", "Nordic Devices"],
        (850, 1600),
    ),
    "screen": (
        ["UltraSharp 27", "ProArt 24", "ThinkVision 32"],
        ["Pixel Works", "Bureau Direct"],
        (180, 520),
    ),
    "phone": (["Pixel 8", "iPhone 14"], ["Nordic Devices"], (450, 900)),
    "headset": (
        ["Evolve2 55", "Zone Wireless", "SC 660"],
        ["Headway Audio"],
        (90, 260),
    ),
}

EQUIPMENT_COUNT = 40

MAINTENANCE = [
    "Battery replaced",
    "Screen cable reseated",
    "Keyboard replaced",
    "Firmware updated",
    "Dead pixel check",
    "Ear cushions replaced",
    "Hinge tightened",
    "Yearly check",
]


#: Families of articles: (name, parent).
FAMILIES = [
    ("Bicycles", None),
    ("City bikes", "Bicycles"),
    ("Mountain bikes", "Bicycles"),
    ("Components", None),
    ("Frames", "Components"),
    ("Wheels", "Components"),
    ("Drivetrain", "Components"),
    ("Fasteners", "Components"),
    ("Electrical", None),
    ("Cabinets", "Electrical"),
    ("Terminals", "Electrical"),
    ("Cables", "Electrical"),
    ("Materials", None),
    ("Metals", "Materials"),
    ("Coatings", "Materials"),
]

#: Articles: (reference, name, kind, unit, unit cost, family).
ARTICLES = [
    ("BK-100", "City bicycle", "product", "pcs", "0", "City bikes"),
    ("BK-200", "Mountain bicycle", "product", "pcs", "0", "Mountain bikes"),
    ("FR-200", "City frame assembly", "assembly", "pcs", "0", "Frames"),
    ("FR-250", "Mountain frame assembly", "assembly", "pcs", "0", "Frames"),
    ("TB-210", "Tube set", "assembly", "pcs", "0", "Frames"),
    ("WH-300", "Wheel assembly", "assembly", "pcs", "0", "Wheels"),
    ("HB-310", "Hub assembly", "assembly", "pcs", "0", "Wheels"),
    ("BR-311", "Ball bearing 6001", "part", "pcs", "2.40", "Wheels"),
    ("AX-312", "Hub axle", "assembly", "pcs", "0", "Wheels"),
    ("RM-320", "Rim 28 inch", "assembly", "pcs", "0", "Wheels"),
    ("SP-330", "Spoke 2 mm", "part", "pcs", "0.35", "Wheels"),
    ("TY-340", "Tyre 700x35", "part", "pcs", "14.90", "Wheels"),
    ("DT-400", "Drivetrain", "assembly", "pcs", "0", "Drivetrain"),
    ("CH-410", "Chain 8 speed", "part", "pcs", "11.50", "Drivetrain"),
    ("CR-420", "Crankset", "assembly", "pcs", "0", "Drivetrain"),
    ("CA-421", "Crank arm", "part", "pcs", "9.80", "Drivetrain"),
    ("SC-001", "Screw M5x12", "part", "pcs", "0.04", "Fasteners"),
    ("NT-002", "Nut M5", "part", "pcs", "0.02", "Fasteners"),
    ("MT-001", "Steel tube 28 mm", "material", "m", "6.20", "Metals"),
    ("MT-002", "Steel bar 10 mm", "material", "kg", "3.10", "Metals"),
    ("MT-003", "Aluminium profile", "material", "m", "4.75", "Metals"),
    ("PT-001", "Powder coating", "material", "kg", "12.00", "Coatings"),
    ("CB-900", "Control cabinet", "product", "pcs", "0", "Cabinets"),
    ("EN-910", "Steel enclosure 800x600", "part", "pcs", "245.00", "Cabinets"),
    ("TS-920", "Terminal rail assembly", "assembly", "pcs", "0", "Terminals"),
    ("HN-930", "Cable harness", "assembly", "pcs", "0", "Cables"),
]

#: Bills of materials: assembly -> [(position, component, quantity)].
BOMS = {
    "BK-100": [
        (10, "FR-200", "1"),
        (20, "WH-300", "2"),
        (30, "DT-400", "1"),
        (40, "SC-001", "12"),
        (50, "NT-002", "12"),
    ],
    "BK-200": [
        (10, "FR-250", "1"),
        (20, "WH-300", "2"),
        (30, "DT-400", "1"),
        (40, "SC-001", "16"),
    ],
    "FR-200": [(10, "TB-210", "1"), (20, "PT-001", "0.4")],
    "FR-250": [
        (10, "TB-210", "1"),
        (20, "MT-003", "1.2"),
        (30, "PT-001", "0.5"),
    ],
    "TB-210": [(10, "MT-001", "4.2")],
    "WH-300": [
        (10, "HB-310", "1"),
        (20, "RM-320", "1"),
        (30, "SP-330", "32"),
        (40, "TY-340", "1"),
    ],
    "HB-310": [(10, "BR-311", "2"), (20, "AX-312", "1"), (30, "SC-001", "4")],
    "AX-312": [(10, "MT-002", "0.35")],
    "RM-320": [(10, "MT-003", "2.1")],
    "DT-400": [(10, "CH-410", "1"), (20, "CR-420", "1")],
    "CR-420": [(10, "CA-421", "2"), (20, "SC-001", "5")],
    "CB-900": [
        (10, "EN-910", "1"),
        (20, "TS-920", "1"),
        (30, "HN-930", "1"),
        (40, "SC-001", "24"),
    ],
}

#: The terminal rail holds this many terminal blocks: a level of more
#: than a thousand records, unfolded a page at a time.
TERMINAL_COUNT = 1200

#: And the harness this many cables.
CABLE_COUNT = 60


class Command(BaseCommand):
    help = "Create the example users and a support desk."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--password",
            default="demo",
            help="Password for the example users (default: demo).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Seeded so two runs describe the same desk, and a bug report
        # about "the third row" means something.
        random.seed(20240501)

        users = self.create_users(options["password"])
        teams = self.create_teams()
        agents = self.create_agents(teams)
        customers = self.create_customers(agents)
        tags = self.create_tags()
        tickets = self.create_tickets(teams, agents, customers, tags)
        self.create_time_entries(tickets, agents)
        self.create_notifications(users)
        self.create_wiki_pages(users)
        self.create_schedule()
        self.create_mailing(users)
        self.create_api_token(users)
        self.work_a_few_tickets(tickets, agents, users)
        self.attach_a_file(tickets, users)
        # Last: what came before draws the same numbers as it always did.
        self.create_equipment(agents)
        self.create_manufacturing()

        self.stdout.write(
            self.style.SUCCESS(
                f"{Customer.objects.count()} customers, "
                f"{Team.objects.count()} teams, "
                f"{Agent.objects.count()} agents, "
                f"{Ticket.objects.count()} tickets, "
                f"{TicketComment.objects.count()} comments, "
                f"{TimeEntry.objects.count()} time entries, "
                f"{Equipment.objects.count()} pieces of equipment, "
                f"{Article.objects.count()} articles."
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Sign in as admin / viewer / guest, password "
                f"'{options['password']}'."
            )
        )

    # -- a few days of work, so the History tab has a story ------------

    def work_a_few_tickets(
        self,
        tickets: list[Ticket],
        agents: list[Agent],
        users: dict[str, Any],
    ) -> None:
        """Move three tickets along, as two different people.

        Creating a record leaves one version and a History tab reading
        "Created", which shows nothing of what the tab is for. These
        are the edits a desk makes in a week: picked up, worked,
        closed - each recorded as whoever did it.
        """
        from generic.history import acting_as

        if not tickets or not agents:
            return

        for offset, ticket in enumerate(tickets[:3]):
            # Each edit its own block, so each is its own version:
            # inside one block they would be one change, which is what
            # a single form save is.
            with acting_as(users["viewer"]):
                ticket.assignee = agents[offset % len(agents)]
                ticket.priority = Ticket.Priority.HIGH
                ticket.save()

            with acting_as(users["admin"]):
                ticket.status = (
                    Ticket.Status.PENDING
                    if offset % 2
                    else Ticket.Status.CLOSED
                )
                ticket.description = (
                    f"{ticket.description}\n\nAnswered by the desk."
                ).strip()
                ticket.save()

    def attach_a_file(
        self,
        tickets: list[Ticket],
        users: dict[str, Any],
    ) -> None:
        """The customer's log on the first ticket: a file to download.

        Written to MEDIA_ROOT like any upload; its page links it
        through the ticket's own endpoint, and the form offers to
        replace or remove it.
        """
        from django.core.files.base import ContentFile

        from generic.history import acting_as

        if not tickets or tickets[0].attachment:
            return

        ticket = tickets[0]
        log = (
            "2026-03-02 09:14:07 ERROR Export timed out after 30 s\n"
            "2026-03-02 09:14:52 ERROR Export timed out after 30 s\n"
            "2026-03-02 09:16:30 WARNING Retried by the customer\n"
        )

        with acting_as(users["viewer"]):
            ticket.attachment.save(
                "customer-log.txt", ContentFile(log.encode()), save=True
            )

    # -- schedules -----------------------------------------------------

    def create_schedule(self) -> None:
        """A nightly run of the digest, for the Schedules page to show.

        Only where the scheduler is installed: the framework does not
        need it, and neither does the rest of this example.
        """
        if not apps.is_installed("django_celery_beat"):
            return

        crontab = apps.get_model("django_celery_beat", "CrontabSchedule")
        periodic = apps.get_model("django_celery_beat", "PeriodicTask")

        schedule, _created = crontab.objects.get_or_create(
            minute="30",
            hour="7",
            day_of_week="1-5",
            day_of_month="*",
            month_of_year="*",
        )
        periodic.objects.get_or_create(
            name="Overdue ticket digest",
            defaults={
                "task": "example.overdue_digest",
                "crontab": schedule,
                "description": (
                    "Every working morning, count what is late and tell "
                    "the desk."
                ),
            },
        )

    def create_mailing(self, users: dict[str, Any]) -> None:
        """Every weekday at eight, the open urgent tickets for admin.

        With the dispatcher on the scheduler every five minutes where
        it is installed; the development stack's console mailer then
        shows the mail in the worker's log.
        """
        from generic.mailings.dispatch import TASK
        from generic.mailings.models import ScheduledMailing
        from generic.mailings.schedule import next_run

        admin = users["admin"]
        mailing, created = ScheduledMailing.objects.get_or_create(
            name="Open urgent tickets",
            owner=admin,
            defaults={
                "table": "site.example.ticket",
                "state": {
                    "columns": [
                        "reference",
                        "title",
                        "customer",
                        "team",
                        "assignee",
                        "due_on",
                    ],
                    "order": [["due_on", "asc"]],
                    "filters": {
                        "match": "all",
                        "conditions": [
                            {
                                "column": "status",
                                "operator": "any_of",
                                "value": ["open", "pending"],
                            },
                            {
                                "column": "priority",
                                "operator": "any_of",
                                "value": ["urgent"],
                            },
                        ],
                    },
                    "search": "",
                },
                "frequency": ScheduledMailing.Frequency.WEEKDAYS,
                "time": "08:00",
            },
        )

        if created:
            mailing.next_run_at = next_run(mailing)
            mailing.save(update_fields=["next_run_at"])

        if not apps.is_installed("django_celery_beat"):
            return

        interval = apps.get_model("django_celery_beat", "IntervalSchedule")
        periodic = apps.get_model("django_celery_beat", "PeriodicTask")
        every, _created = interval.objects.get_or_create(
            every=5, period="minutes"
        )
        periodic.objects.get_or_create(
            name="Scheduled mailings",
            defaults={
                "task": TASK,
                "interval": every,
                "description": "Sends the mailings whose time has come.",
            },
        )

    def create_api_token(self, users: dict[str, Any]) -> None:
        """A read token for admin, printed once, as the account page does.

        Only a hash is kept: a second run cannot print it again, and
        makes none - revoke it on the account page to get a new one.
        """
        if not apps.is_installed("generic.tokens"):
            return

        from generic.tokens.models import ApiToken

        admin = users["admin"]

        if ApiToken.objects.filter(user=admin, name="Seed script").exists():
            return

        _instance, token = ApiToken.objects.create(
            user=admin,
            name="Seed script",
            scope=ApiToken.Scope.READ,
            expiry=datetime.timedelta(days=90),
        )
        self.stdout.write(
            f"A read-only API token for admin (shown once): {token}\n"
            f"  curl -H 'Authorization: Token {token}' "
            f"http://127.0.0.1:8000/api/example/ticket/?length=5"
        )

    # -- the equipment ---------------------------------------------------

    def create_equipment(self, agents: list[Agent]) -> None:
        """Suppliers, what the desk bought from them, and its repairs.

        Found again by serial number, so a second run adds only what is
        missing. The pages are auto() ones: nothing here is shaped for
        them.
        """
        suppliers = {}

        for name, email, phone, website, country, preferred in SUPPLIERS:
            suppliers[name], _created = Supplier.objects.get_or_create(
                name=name,
                defaults={
                    "email": email,
                    "phone": phone,
                    "website": website,
                    "country": country,
                    "is_preferred": preferred,
                },
            )

        kinds = list(EQUIPMENT)
        states = ["in_use"] * 6 + ["spare"] * 2 + ["repair", "retired"]
        today = timezone.localdate()

        for index in range(EQUIPMENT_COUNT):
            kind = kinds[index % len(kinds)]
            names, sellers, (low, high) = EQUIPMENT[kind]
            state = random.choice(states)
            item, created = Equipment.objects.get_or_create(
                serial_number=f"EQ-{kind[:2].upper()}-{1000 + index}",
                defaults={
                    "name": random.choice(names),
                    "kind": kind,
                    "state": state,
                    "supplier": suppliers[random.choice(sellers)],
                    "assigned_to": (
                        random.choice(agents) if state == "in_use" else None
                    ),
                    "purchased_on": today
                    - datetime.timedelta(days=random.randint(30, 1100)),
                    "price": Decimal(random.randint(low, high)),
                },
            )

            if not created or random.random() < 0.55:
                continue

            for visit in range(random.randint(1, 3)):
                Maintenance.objects.create(
                    equipment=item,
                    performed_on=today
                    - datetime.timedelta(days=random.randint(1, 400)),
                    description=random.choice(MAINTENANCE),
                    cost=Decimal(random.choice([0, 0, 35, 60, 120])),
                    is_done=visit > 0 or state != "repair",
                )

    def create_manufacturing(self) -> None:
        """Article families, articles and their bills of materials.

        A bicycle five levels deep, sharing its wheels with a second
        one, and a control cabinet whose terminal rail holds more than
        a thousand terminal blocks. Found again by reference: a second
        run adds only what is missing.
        """
        families: dict[str, ArticleFamily] = {}

        for name, parent in FAMILIES:
            families[name], _created = ArticleFamily.objects.get_or_create(
                name=name, defaults={"parent": families.get(parent)}
            )

        articles: dict[str, Article] = {}

        for reference, name, kind, unit, cost, family in ARTICLES:
            articles[reference], _created = Article.objects.get_or_create(
                reference=reference,
                defaults={
                    "name": name,
                    "kind": kind,
                    "unit": unit,
                    "unit_cost": Decimal(cost),
                    "family": families[family],
                },
            )

        def series(prefix, name, count, cost, family):
            references = [
                f"{prefix}-{index:04}" for index in range(1, count + 1)
            ]
            existing = set(
                Article.objects.filter(reference__in=references).values_list(
                    "reference", flat=True
                )
            )
            Article.objects.bulk_create(
                Article(
                    reference=reference,
                    name=f"{name} {reference[len(prefix) + 1:]}",
                    kind="part",
                    unit="pcs",
                    unit_cost=Decimal(cost),
                    family=families[family],
                )
                for reference in references
                if reference not in existing
            )

            return list(
                Article.objects.filter(reference__in=references).order_by(
                    "reference"
                )
            )

        terminals = series(
            "TB", "Terminal block", TERMINAL_COUNT, "0.85", "Terminals"
        )
        cables = series("CBL", "Cable", CABLE_COUNT, "1.60", "Cables")
        bills = {
            reference: [
                (position, articles[child], Decimal(quantity))
                for position, child, quantity in lines
            ]
            for reference, lines in BOMS.items()
        }
        bills["TS-920"] = [
            (index * 10, terminal, Decimal(1))
            for index, terminal in enumerate(terminals, start=1)
        ]
        bills["HN-930"] = [
            (index * 10, cable, Decimal(2))
            for index, cable in enumerate(cables, start=1)
        ]

        for reference, lines in bills.items():
            assembly = articles[reference]

            if assembly.bom_lines.exists():
                continue

            BomLine.objects.bulk_create(
                BomLine(
                    parent=assembly,
                    child=child,
                    position=position,
                    quantity=quantity,
                )
                for position, child, quantity in lines
            )

    # -- users ---------------------------------------------------------

    def create_users(self, password: str) -> dict[str, Any]:
        user_model = get_user_model()

        admin, _created = user_model.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@example.test",
                "first_name": "Ada",
                "last_name": "Admin",
            },
        )
        admin.is_staff = True
        admin.is_superuser = True
        admin.set_password(password)
        admin.save()

        viewer, _created = user_model.objects.get_or_create(
            username="viewer",
            defaults={
                "email": "camille.rousseau@example.test",
                "first_name": "Camille",
                "last_name": "Rousseau",
            },
        )
        viewer.set_password(password)
        viewer.is_staff = False
        viewer.is_superuser = False
        viewer.save()
        viewer.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label="example",
                codename__in=VIEWER_PERMISSIONS,
            )
        )

        guest, _created = user_model.objects.get_or_create(
            username="guest",
            defaults={"email": "guest@example.test"},
        )
        guest.set_password(password)
        guest.is_staff = False
        guest.is_superuser = False
        guest.save()
        guest.user_permissions.clear()

        users = {"admin": admin, "viewer": viewer, "guest": guest}
        self.create_groups(users)

        return users

    def create_groups(self, users: dict[str, Any]) -> None:
        """Two jobs, so the Groups page has something to describe.

        The viewer keeps the permissions they were given directly - a
        real desk has both - which is also what makes the difference
        visible on their page: some of what they may do comes from the
        group, the rest is theirs alone.
        """
        agents, _created = Group.objects.get_or_create(name="Desk agents")
        agents.permissions.set(
            Permission.objects.filter(
                content_type__app_label="example",
                codename__in=VIEWER_PERMISSIONS,
            )
        )

        readers, _created = Group.objects.get_or_create(name="Read only")
        readers.permissions.set(
            Permission.objects.filter(
                content_type__app_label="example",
                codename__startswith="view_",
            )
        )

        users["viewer"].groups.set([agents])
        users["guest"].groups.clear()

    # -- data ------------------------------------------------------------

    def create_teams(self) -> list[Team]:
        return [
            Team.objects.get_or_create(
                code=code,
                defaults={"name": name},
            )[0]
            for name, code in TEAMS
        ]

    def create_agents(self, teams: list[Team]) -> list[Agent]:
        agents = []

        for index, name in enumerate(AGENTS):
            local = name.lower().replace(" ", ".")
            agent, _created = Agent.objects.get_or_create(
                name=name,
                defaults={
                    "email": f"{local}@example.test",
                    "team": teams[index % len(teams)],
                    "is_active": index % 7 != 0,
                    "hired_on": datetime.date(2018 + index % 6, 3, 1),
                    "capacity_hours": Decimal(
                        random.choice(["21.00", "28.00", "35.00"])
                    ),
                },
            )
            agents.append(agent)

        return agents

    def create_customers(self, agents: list[Agent]) -> list[Customer]:
        customers = []

        for index, row in enumerate(CUSTOMERS):
            name, code, segment, city, website = row
            customer, _created = Customer.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "segment": segment,
                    "city": city,
                    "website": website,
                    "account_manager": agents[index % len(agents)],
                    "customer_since": datetime.date(
                        2015 + index, 1 + index, 1
                    ),
                    "notes": (
                        f"{name} has worked with the desk since "
                        f"{2015 + index}.\nEscalations go to the account "
                        f"manager first."
                    ),
                },
            )
            customers.append(customer)

        return customers

    def create_tags(self) -> list[Tag]:
        tags = []

        for name, color, background in TAGS:
            tag, created = Tag.objects.get_or_create(
                name=name,
                defaults={"color": color, "background": background},
            )

            # Tags seeded before they had colours get them now.
            if not created and not (tag.color or tag.background):
                tag.color, tag.background = color, background
                tag.save(update_fields=["color", "background"])

            tags.append(tag)

        return tags

    def create_tickets(
        self,
        teams: list[Team],
        agents: list[Agent],
        customers: list[Customer],
        tags: list[Tag],
    ) -> list[Ticket]:
        priorities = [choice[0] for choice in Ticket.Priority.choices]
        statuses = [choice[0] for choice in Ticket.Status.choices]
        now = timezone.now()
        tickets = []
        comments = []

        for index in range(TICKET_COUNT):
            subject = SUBJECTS[index % len(SUBJECTS)]
            reference = f"SD-{1000 + index}"
            customer = random.choices(customers, weights=CUSTOMER_WEIGHTS)[0]
            # The recent tickets are still open; the old ones mostly done.
            status = statuses[index % 2] if index < 40 else statuses[index % 4]

            ticket, created = Ticket.objects.get_or_create(
                reference=reference,
                defaults={
                    "title": subject,
                    "description": (
                        f"{subject}. Reported by {customer} and triaged "
                        f"the same day."
                    ),
                    "team": teams[index % len(teams)],
                    "customer": customer,
                    # Every fourth ticket is unassigned, so the table
                    # has empty cells to render.
                    "assignee": (
                        None if index % 4 == 0 else agents[index % len(agents)]
                    ),
                    "priority": priorities[index % len(priorities)],
                    "status": status,
                    "is_billable": index % 3 == 0,
                    "estimated_hours": Decimal(
                        random.choice(["0.50", "2.00", "8.00", "16.00"])
                    ),
                    # Only closed tickets carry a score, so the column
                    # has nulls.
                    "satisfaction": (
                        round(random.uniform(2.0, 5.0), 1)
                        if status == Ticket.Status.CLOSED
                        else None
                    ),
                    "opened_at": now
                    - datetime.timedelta(days=index * 2 + 1, hours=index % 24),
                    "due_on": (
                        None
                        if index % 5 == 0
                        else (
                            now + datetime.timedelta(days=index % 30 - 5)
                        ).date()
                    ),
                },
            )

            if not created:
                # A desk seeded before customers existed gets them now.
                if ticket.customer_id is None:
                    ticket.customer = customer
                    ticket.save(update_fields=["customer"])

                tickets.append(ticket)
                continue

            ticket.tags.set(random.sample(tags, k=random.randint(0, 2)))

            for position in range(1, random.randint(1, 5)):
                comments.append(
                    TicketComment(
                        ticket=ticket,
                        author=random.choice(AGENTS),
                        body=random.choice(COMMENTS),
                        position=position,
                    )
                )

            tickets.append(ticket)

        TicketComment.objects.bulk_create(comments)

        return tickets

    def create_time_entries(
        self,
        tickets: list[Ticket],
        agents: list[Agent],
    ) -> None:
        """A few entries per ticket, for the tickets that have none."""
        today = timezone.localdate()
        logged = set(
            TimeEntry.objects.values_list("ticket_id", flat=True).distinct()
        )
        entries = []

        for ticket in tickets:
            if ticket.pk in logged:
                continue

            team = [
                agent for agent in agents if agent.team_id == ticket.team_id
            ]
            opened = timezone.localtime(ticket.opened_at).date()
            span = max(0, min((today - opened).days, 20))

            for _entry in range(random.randint(0, 7)):
                entries.append(
                    TimeEntry(
                        ticket=ticket,
                        agent=random.choice(team or agents),
                        spent_on=opened
                        + datetime.timedelta(days=random.randint(0, span)),
                        hours=Decimal(
                            random.choice(
                                [
                                    "0.25",
                                    "0.50",
                                    "1.00",
                                    "1.50",
                                    "2.00",
                                    "4.00",
                                ]
                            )
                        ),
                        is_billable=ticket.is_billable
                        or random.random() < 0.3,
                        note=random.choice(WORK),
                    )
                )

        # In bulk: no signal per row, so no event storm while seeding.
        TimeEntry.objects.bulk_create(entries)

    def create_notifications(self, users: dict[str, Any]) -> None:
        """A message to everyone and a reminder, so the bell has a count.

        The message is what an administrator writes on the Messages
        screen, sent the same way; the reminder is what project code
        stores for one person.
        """
        from generic.events.messages import send

        welcome = "Welcome to the support desk"

        if not Message.objects.filter(title=welcome).exists():
            send(
                Message.objects.create(
                    title=welcome,
                    body="Press Ctrl+K anywhere to search pages and records.",
                    url="/",
                    everyone=True,
                    # Not by e-mail: a seed has no business in an inbox.
                    delivery=Message.Delivery.IN_APP,
                    sender=users["admin"],
                )
            )

        for key in ("admin", "viewer"):
            user = users[key]

            if Notification.objects.filter(
                Q(user=user) & Q(title__startswith="SD-1002")
            ).exists():
                continue

            Notification.objects.create(
                user=user,
                title="SD-1002 is due soon",
                body="The VPN ticket reaches its due date this week.",
                level=NotificationLevel.WARNING,
                url="/example/ticket/",
            )

    def create_wiki_pages(self, users: dict[str, Any]) -> None:
        """Two wikis: the desk's handbook, its first page pinned to the
        dashboard, and the infrastructure team's runbooks."""
        from django.apps import apps

        # The wiki is optional: a project without it seeds without it.
        if not apps.is_installed("generic.wiki"):
            return

        from django.core.files.base import ContentFile

        from generic.wiki.models import Wiki, WikiFile, WikiPage

        # The first wiki, made by the migration, named for the desk.
        handbook = Wiki.objects.default()

        if handbook.name == "Wiki":
            handbook.name = "Desk handbook"
            handbook.description = (
                "What everyone on the desk should know: triage, "
                "escalation, shortcuts."
            )
            handbook.save()

        runbooks, _created = Wiki.objects.get_or_create(
            slug="infrastructure",
            defaults={
                "name": "Infrastructure runbooks",
                "description": "How the infrastructure team keeps the "
                "service running.",
                "position": 1,
            },
        )

        # A file attached to a page from its editor: a block of the
        # page, linking to where readers download it.
        checklist = WikiFile.objects.filter(
            original_name="triage-checklist.txt"
        ).first()

        if checklist is None:
            text = (
                b"[ ] Customer opened\n[ ] Priority set\n"
                b"[ ] Team set\n[ ] Assigned, or left to the lead\n"
            )
            checklist = WikiFile(
                original_name="triage-checklist.txt",
                size=len(text),
                uploaded_by=users["admin"],
            )
            checklist.file.save(
                "triage-checklist.txt", ContentFile(text), save=True
            )

        pages = [
            (
                "welcome",
                "Welcome to the desk",
                None,
                0,
                True,
                "<p>This wiki holds what everyone on the desk should "
                "know. This page is pinned to the dashboard, so it is the "
                "first thing people see.</p><ul><li>Read "
                '<a href="/wiki/main/triage/">how we triage</a> before taking '
                "your first ticket.</li><li>Press <strong>Ctrl+K</strong> "
                "anywhere to find a page, a ticket or a customer.</li>"
                "<li>Admins change any page with its <em>Edit</em> "
                "button; every version is kept.</li></ul>",
            ),
            (
                "triage",
                "How we triage",
                None,
                1,
                False,
                "<h2>Within the hour</h2><ol><li>Open the customer: its "
                "summary shows its open tickets and the time already "
                "spent.</li><li>Set the priority and the team.</li><li>"
                "Assign the ticket, or leave it to the team's lead.</li>"
                "</ol><p>The same steps, to print:</p>"
                '<p class="wiki-file"><a href="'
                f'{checklist.get_absolute_url()}">triage-checklist.txt'
                "</a></p><h2>Priorities</h2><p><strong>Urgent</strong> means "
                "someone cannot work; <strong>high</strong> means they "
                "work around it.</p><blockquote>When in doubt, ask the "
                "team rather than guess.</blockquote>",
            ),
            (
                "escalation",
                "Escalating a ticket",
                "triage",
                0,
                False,
                "<p>Escalate when an <strong>urgent</strong> ticket has "
                "had no answer within the hour, or when the customer asks "
                "for it.</p><ol><li>Say why in a comment.</li><li>Tell "
                "the account manager, named on the customer's summary."
                "</li><li>Move the ticket to Infrastructure when the "
                "cause is on our side.</li></ol>",
            ),
            (
                "shortcuts",
                "Shortcuts",
                None,
                2,
                False,
                "<ul><li><strong>Ctrl+K</strong>: search pages and "
                "records.</li><li><strong>Ctrl+S</strong>: save the form "
                "you are in.</li><li>Double-click a row to open it; "
                "right-click it for its menu.</li></ul><p>The API behind "
                "every screen can be browsed too:</p>"
                '<pre class="ql-syntax">/api/example/ticket/'
                "?search[value]=invoice</pre>",
            ),
        ]

        pages = [(handbook, *page) for page in pages] + [
            (
                runbooks,
                "on-call",
                "On call",
                None,
                0,
                False,
                "<p>One engineer is on call each week, named in the "
                "Infrastructure team's summary.</p><ol><li>Acknowledge "
                "within fifteen minutes.</li><li>Open a ticket for every "
                "incident, even one fixed at once.</li></ol>",
            ),
            (
                runbooks,
                "restarting-a-service",
                "Restarting a service",
                "on-call",
                0,
                False,
                "<p>Say it in the incident's ticket first, then:</p>"
                '<pre class="ql-syntax">systemctl restart desk-web'
                "</pre><p>Check the dashboard's charts move again.</p>",
            ),
        ]

        for wiki, slug, title, parent, position, pinned, content in pages:
            WikiPage.objects.get_or_create(
                wiki=wiki,
                slug=slug,
                defaults={
                    "title": title,
                    "parent": (
                        WikiPage.objects.filter(wiki=wiki, slug=parent).first()
                        if parent
                        else None
                    ),
                    "position": position,
                    "show_on_dashboard": pinned,
                    "content": content,
                    "created_by": users["admin"],
                    "updated_by": users["admin"],
                },
            )

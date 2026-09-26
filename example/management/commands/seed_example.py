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
    "Norah Lefevre",
    "Tomas Klein",
    "Aurelie Meunier",
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
    ("Region Occitanie", "OCC", "public", "Toulouse", ""),
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
        self.work_a_few_tickets(tickets, agents, users)
        # Last: what came before draws the same numbers as it always did.
        self.create_equipment(agents)

        self.stdout.write(
            self.style.SUCCESS(
                f"{Customer.objects.count()} customers, "
                f"{Team.objects.count()} teams, "
                f"{Agent.objects.count()} agents, "
                f"{Ticket.objects.count()} tickets, "
                f"{TicketComment.objects.count()} comments, "
                f"{TimeEntry.objects.count()} time entries, "
                f"{Equipment.objects.count()} pieces of equipment."
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
        """A few wiki pages, the first one pinned to the dashboard."""
        from django.apps import apps

        # The wiki is optional: a project without it seeds without it.
        if not apps.is_installed("generic.wiki"):
            return

        from generic.wiki.models import WikiPage

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
                '<a href="/wiki/triage/">how we triage</a> before taking '
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
                "</ol><h2>Priorities</h2><p><strong>Urgent</strong> means "
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

        for slug, title, parent, position, pinned, content in pages:
            WikiPage.objects.get_or_create(
                slug=slug,
                defaults={
                    "title": title,
                    "parent": (
                        WikiPage.objects.filter(slug=parent).first()
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

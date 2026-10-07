"""A few products to look at: python manage.py seed_products.

Dates are counted from today, so some steps are done, some late and
some coming up whenever it is run. A product already there is left as
it is: running it twice adds nothing.
"""

from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from products.models import Document, Product

STEPS = ("Concept", "Design review", "Prototype", "Validation", "Launch")

#: reference, name, owner, status, days from today to the first step,
#: how many steps are done.
PRODUCTS = (
    ("PRD-001", "Desk lamp", "Alice", "launched", -200, 5),
    ("PRD-002", "Wireless charger", "Bob", "development", -90, 2),
    ("PRD-003", "Smart thermostat", "Alice", "development", -40, 1),
    ("PRD-004", "Air purifier", "Chloe", "planned", 10, 0),
    ("PRD-005", "Bluetooth speaker", "Bob", "retired", -700, 5),
)


class Command(BaseCommand):
    help = "Create a few products with their milestones and documents."

    def handle(self, *args, **options):
        today = timezone.localdate()
        created = 0

        for reference, name, owner, status, start, done in PRODUCTS:
            product, new = Product.objects.get_or_create(
                reference=reference,
                defaults={
                    "name": name,
                    "owner": owner,
                    "status": status,
                    "description": f"The {name.lower()}, from idea to "
                    "launch.",
                },
            )
            if not new:
                continue
            created += 1

            for index, step in enumerate(STEPS):
                due_on = today + timedelta(days=start + 30 * index)
                product.milestones.create(
                    step=step,
                    due_on=due_on,
                    done_on=due_on if index < done else None,
                )

            spec = Document(
                product=product,
                title=f"{name} - specification",
                kind=Document.Kind.SPECIFICATION,
            )
            spec.file.save(
                f"{reference.lower()}-specification.txt",
                ContentFile(f"{reference} {name}\n\nWhat it must do.\n"),
            )
            parts = Document(
                product=product,
                title=f"{name} - parts list",
                kind=Document.Kind.OTHER,
            )
            parts.file.save(
                f"{reference.lower()}-parts.csv",
                ContentFile("part;quantity\ncase;1\nscrew;4\n"),
            )

        self.stdout.write(self.style.SUCCESS(f"{created} product(s) created."))

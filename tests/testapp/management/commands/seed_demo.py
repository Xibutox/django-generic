"""Populate the demo database with something worth looking at."""

from __future__ import annotations

import datetime
import random
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from tests.testapp.models import Author, Book, Chapter, Publisher

AUTHORS = [
    "Jane Austen",
    "George Orwell",
    "Virginia Woolf",
    "Gustave Flaubert",
    "Marguerite Yourcenar",
    "Italo Calvino",
]

TITLES = [
    "Emma",
    "Persuasion",
    "Essays",
    "Mrs Dalloway",
    "To the Lighthouse",
    "Madame Bovary",
    "Memoirs of Hadrian",
    "Invisible Cities",
    "The Baron in the Trees",
    "Northanger Abbey",
    "Coming Up for Air",
    "Orlando",
]


class Command(BaseCommand):
    help = "Create a demo user and a small library."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--password",
            default="demo",
            help="Password for the demo user (default: demo).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        random.seed(1)

        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username="demo",
            defaults={"email": "demo@example.test", "is_staff": True},
        )
        user.set_password(options["password"])
        user.is_superuser = True
        user.is_staff = True
        user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"User 'demo' {'created' if created else 'updated'}."
            )
        )

        publishers = [
            Publisher.objects.get_or_create(
                name=name,
                defaults={"country": country},
            )[0]
            for name, country in (
                ("Gallimard", "FR"),
                ("Penguin", "UK"),
                ("Einaudi", "IT"),
            )
        ]

        authors = [
            Author.objects.get_or_create(
                name=name,
                defaults={
                    "email": name.lower().replace(" ", ".") + "@example.test",
                    "birth_date": datetime.date(
                        random.randint(1775, 1930), 1, 1
                    ),
                },
            )[0]
            for name in AUTHORS
        ]

        genres = [choice[0] for choice in Book.Genre.choices]

        for index, title in enumerate(TITLES):
            book, created = Book.objects.get_or_create(
                title=title,
                defaults={
                    "author": authors[index % len(authors)],
                    "publisher": publishers[index % len(publishers)],
                    "genre": genres[index % len(genres)],
                    "pages": random.randint(90, 900),
                    "price": Decimal(random.randint(700, 3200)) / 100,
                    "rating": round(random.uniform(2.5, 5.0), 1),
                    "published_on": datetime.date(
                        random.randint(1810, 2020), 1, 1
                    ),
                    "is_available": index % 4 != 0,
                },
            )

            if created:
                for position in range(1, random.randint(2, 4)):
                    Chapter.objects.create(
                        book=book,
                        title=f"Chapter {position}",
                        position=position,
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"{Book.objects.count()} books, "
                f"{Chapter.objects.count()} chapters."
            )
        )

"""Test data factories.

Deterministic where it matters: filtering and ordering assertions need
known values, so tables under test are built from explicit fixtures and
these factories only fill in the fields a test does not care about.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import factory
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

from generic.events.models import Notification, NotificationLevel
from tests.testapp.models import Author, Book, Chapter, Publisher


class UserFactory(DjangoModelFactory):
    class Meta:
        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda user: f"{user.username}@example.test")
    is_active = True


class PublisherFactory(DjangoModelFactory):
    class Meta:
        model = Publisher

    name = factory.Sequence(lambda n: f"Publisher {n}")
    country = "FR"


class AuthorFactory(DjangoModelFactory):
    class Meta:
        model = Author

    name = factory.Sequence(lambda n: f"Author {n}")
    email = factory.LazyAttribute(
        lambda author: f"{author.name.lower().replace(' ', '.')}@test"
    )
    birth_date = datetime.date(1970, 1, 1)
    is_active = True


class BookFactory(DjangoModelFactory):
    class Meta:
        model = Book

    title = factory.Sequence(lambda n: f"Book {n}")
    author = factory.SubFactory(AuthorFactory)
    publisher = None
    genre = Book.Genre.FICTION
    pages = 100
    price = Decimal("10.00")
    rating = 3.5
    published_on = datetime.date(2020, 1, 1)
    released_at = datetime.datetime(
        2020,
        1,
        1,
        12,
        0,
        tzinfo=datetime.timezone.utc,
    )
    is_available = True


class ChapterFactory(DjangoModelFactory):
    class Meta:
        model = Chapter

    book = factory.SubFactory(BookFactory)
    title = factory.Sequence(lambda n: f"Chapter {n}")
    position = factory.Sequence(lambda n: n)


class NotificationFactory(DjangoModelFactory):
    class Meta:
        model = Notification

    user = factory.SubFactory(UserFactory)
    title = factory.Sequence(lambda n: f"Notification {n}")
    body = "Something happened."
    level = NotificationLevel.INFO
    url = ""

"""Models exercising the framework.

Chosen to cover every column type the table layer supports, plus a
parent/child pair for the inline forms and a protected relation for the
deletion preview.
"""

from __future__ import annotations

from django.db import models


class Publisher(models.Model):
    name = models.CharField(max_length=100)
    country = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Author(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, default="")
    birth_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Book(models.Model):
    class Genre(models.TextChoices):
        FICTION = "fiction", "Fiction"
        ESSAY = "essay", "Essay"
        POETRY = "poetry", "Poetry"

    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        Author,
        on_delete=models.CASCADE,
        related_name="books",
    )
    # PROTECT so the deletion preview has something to report.
    publisher = models.ForeignKey(
        Publisher,
        on_delete=models.PROTECT,
        related_name="books",
        null=True,
        blank=True,
    )
    genre = models.CharField(
        max_length=20,
        choices=Genre.choices,
        default=Genre.FICTION,
    )
    pages = models.PositiveIntegerField(default=0)
    price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
    )
    rating = models.FloatField(null=True, blank=True)
    published_on = models.DateField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title


class Chapter(models.Model):
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="chapters",
    )
    title = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "pk")
        constraints = (
            models.UniqueConstraint(
                fields=("book", "position"),
                name="testapp_chapter_unique_position",
            ),
        )

    def __str__(self) -> str:
        return self.title

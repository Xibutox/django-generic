from django.db import models


class Book(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        LENT = "lent", "Lent"

    title = models.CharField(max_length=200)
    author = models.CharField(max_length=120)
    pages = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.AVAILABLE
    )

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

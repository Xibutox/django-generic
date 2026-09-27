"""Models exercising the framework.

Chosen to cover every column type the table layer supports, plus a
parent/child pair for the inline forms and a protected relation for the
deletion preview.
"""

from __future__ import annotations

from django.core.validators import FileExtensionValidator
from django.db import models
from django_fsm import FSMField, transition


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


def has_a_summary(manuscript: "Manuscript") -> bool:
    return bool(manuscript.summary)


class Manuscript(models.Model):
    """A state machine: draft, submitted, accepted or rejected.

    Covers what transitions read from django-fsm-2: several sources, a
    permission, a condition, a transition asking for a field, and one
    marked dangerous.
    """

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True, default="")
    verdict = models.TextField("verdict", blank=True, default="")
    state = FSMField(choices=State.choices, default=State.DRAFT)

    class Meta:
        ordering = ("title",)
        permissions = [("accept_manuscript", "Can accept a manuscript")]

    def __str__(self) -> str:
        return self.title

    @transition(
        field=state,
        source=State.DRAFT,
        target=State.SUBMITTED,
        conditions=[has_a_summary],
        custom={"label": "Submit", "icon": "send"},
    )
    def submit(self) -> None:
        pass

    @transition(
        field=state,
        source=State.SUBMITTED,
        target=State.ACCEPTED,
        permission="testapp.accept_manuscript",
        custom={"label": "Accept", "fields": ("verdict",)},
    )
    def accept(self) -> None:
        pass

    @transition(
        field=state,
        source=[State.SUBMITTED, State.ACCEPTED],
        target=State.REJECTED,
        custom={
            "label": "Reject",
            "confirm": "Reject this manuscript?",
            "variant": "danger",
        },
    )
    def reject(self) -> None:
        pass


class Document(models.Model):
    """Files in a form: a required one, an optional one, a hidden one.

    With a many-to-many, a JSON field and inline notes beside them, so
    a form sent as ``_payload`` plus files can be checked to write
    everything JSON would have. ``scan`` is a plain file field rather
    than an image field: Pillow is not a dependency of the framework.
    """

    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="documents/")
    scan = models.FileField(
        upload_to="scans/",
        blank=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "pdf"])],
    )
    #: Stored, and shown by no screen: never downloadable.
    archive = models.FileField(upload_to="archives/", blank=True)
    authors = models.ManyToManyField(
        Author, related_name="documents", blank=True
    )
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title


class DocumentNote(models.Model):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="notes"
    )
    text = models.CharField(max_length=200)

    class Meta:
        ordering = ("pk",)

    def __str__(self) -> str:
        return self.text

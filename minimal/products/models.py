"""Products, the dated steps each one goes through, and its files."""

from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone


class Product(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        DEVELOPMENT = "development", "In development"
        LAUNCHED = "launched", "Launched"
        RETIRED = "retired", "Retired"

    reference = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=200)
    owner = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PLANNED
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["reference"]

    def __str__(self):
        return f"{self.reference} - {self.name}"


class Milestone(models.Model):
    """One step of a product: when it is due, and when it was done."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="milestones"
    )
    step = models.CharField(max_length=120)
    due_on = models.DateField("due on")
    done_on = models.DateField("done on", null=True, blank=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["due_on", "pk"]

    def __str__(self):
        return f"{self.product.reference} - {self.step}"

    @property
    def state(self):
        if self.done_on:
            return "done"
        return "late" if self.due_on < timezone.localdate() else "upcoming"


class Document(models.Model):
    """A file attached to a product: a specification, a drawing..."""

    class Kind(models.TextChoices):
        SPECIFICATION = "specification", "Specification"
        DRAWING = "drawing", "Drawing"
        CERTIFICATE = "certificate", "Certificate"
        OTHER = "other", "Other"

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="documents"
    )
    title = models.CharField(max_length=200)
    kind = models.CharField(
        max_length=20, choices=Kind.choices, default=Kind.OTHER
    )
    # Under MEDIA_ROOT, downloaded through the product's own endpoint, to
    # whoever may see it - never served as a static file.
    file = models.FileField(
        upload_to="products/%Y/%m/",
        validators=[
            FileExtensionValidator(
                ["pdf", "docx", "xlsx", "pptx", "png", "jpg", "txt", "csv"]
            )
        ],
    )
    added_at = models.DateTimeField("added", auto_now_add=True)

    class Meta:
        ordering = ["-added_at", "-pk"]

    def __str__(self):
        return self.title

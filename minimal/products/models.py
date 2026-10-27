"""Products, the dated steps each one goes through, and its files -
each file kept in every version it has had."""

from pathlib import PurePosixPath

from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.utils import timezone

FILE_TYPES = ["pdf", "docx", "xlsx", "pptx", "png", "jpg", "txt", "csv"]


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
    """A file attached to a product: a specification, a drawing...

    ``file`` is always its latest version, so the document's own
    download gives the latest; every file it has had is a
    :class:`DocumentVersion`, on its *Versions* tab.
    """

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
        validators=[FileExtensionValidator(FILE_TYPES)],
        help_text="A new file is a new version: the previous ones stay "
        "on the Versions tab.",
    )
    version = models.PositiveIntegerField(default=0, editable=False)
    added_at = models.DateTimeField("added", auto_now_add=True)

    class Meta:
        ordering = ["-added_at", "-pk"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # A file other than the latest version's is a new version,
        # whichever form or command sent it - named as it was sent,
        # before the storage gives it its own path.
        name = PurePosixPath(self.file.name).name if self.file else ""
        super().save(*args, **kwargs)

        if self.file and not self.versions.filter(
            number=self.version, file=self.file.name
        ):
            version = self.versions.create(file=self.file.name, file_name=name)
            self.version = version.number

    @property
    def file_name(self):
        """The name the latest version was sent with."""
        current = self.versions.filter(number=self.version).first()
        return current.file_name if current else ""


class DocumentVersion(models.Model):
    """One file a document has had, numbered 1, 2, 3... in the order
    sent. Never changed: a correction is the next version."""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="versions"
    )
    number = models.PositiveIntegerField("version", editable=False)
    file = models.FileField(
        upload_to="products/%Y/%m/",
        validators=[FileExtensionValidator(FILE_TYPES)],
    )
    # The name it had on its sender's disk, the name it downloads under.
    file_name = models.CharField(max_length=255, editable=False)
    note = models.CharField(
        "change note",
        max_length=200,
        blank=True,
        help_text="What changed, and why.",
    )
    added_at = models.DateTimeField("added", auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "number"], name="one_number_a_version"
            )
        ]

    def __str__(self):
        return f"{self.document} - v{self.number}"

    def save(self, *args, **kwargs):
        if self.pk:
            return super().save(*args, **kwargs)

        if not self.file_name:
            self.file_name = PurePosixPath(self.file.name).name

        with transaction.atomic():
            # The document's row locked: two files sent at once still
            # get two numbers.
            document = Document.objects.select_for_update().get(
                pk=self.document_id
            )
            self.number = document.version + 1
            super().save(*args, **kwargs)
            # The latest version is the document's file - what its
            # download gives. An update: no new version from it.
            Document.objects.filter(pk=document.pk).update(
                file=self.file.name, version=self.number
            )

"""The asset inventory (ISO/IEC 27002 5.9 to 5.13, 7.10, 7.13, 7.14).

An asset is anything worth protecting - information, software,
equipment, a service, a site - with an owner answerable for it and a
classification saying how much harm its disclosure would do. Who holds
it and when it came back (5.11), how it is maintained (7.13) and how it
was disposed of (7.10, 7.14) are kept beside it.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from iso.common import Classification, number

USER = settings.AUTH_USER_MODEL

#: ASSET-0001, ASSET-0002... one series for every kind.
REFERENCE_PATTERN = "ASSET-{seq:04}"

RATINGS = [(1, _("1 - Low")), (2, _("2 - Medium")), (3, _("3 - High"))]


class Asset(models.Model):
    class Kind(models.TextChoices):
        INFORMATION = "information", _("Information")
        SOFTWARE = "software", _("Software")
        HARDWARE = "hardware", _("Hardware")
        SERVICE = "service", _("Service")
        MEDIA = "media", _("Storage media")
        SITE = "site", _("Site")

    class Status(models.TextChoices):
        PLANNED = "planned", _("Planned")
        IN_STOCK = "in_stock", _("In stock")
        IN_USE = "in_use", _("In use")
        MAINTENANCE = "maintenance", _("Under maintenance")
        RETIRED = "retired", _("Retired")
        DISPOSED = "disposed", _("Disposed")

    reference = models.CharField(
        _("reference"), max_length=20, unique=True, blank=True, editable=False
    )
    name = models.CharField(_("name"), max_length=200)
    kind = models.CharField(_("kind"), max_length=12, choices=Kind.choices)
    description = models.TextField(_("description"), blank=True)
    owner = models.ForeignKey(
        USER,
        verbose_name=_("owner"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Answerable for the asset's protection."),
    )
    classification = models.CharField(
        _("classification"),
        max_length=12,
        choices=Classification.choices,
        default=Classification.INTERNAL,
    )
    confidentiality = models.PositiveSmallIntegerField(
        _("confidentiality"), choices=RATINGS, default=2
    )
    integrity = models.PositiveSmallIntegerField(
        _("integrity"), choices=RATINGS, default=2
    )
    availability = models.PositiveSmallIntegerField(
        _("availability"), choices=RATINGS, default=2
    )
    status = models.CharField(
        _("status"), max_length=12, choices=Status.choices, default="in_use"
    )
    location = models.CharField(_("location"), max_length=200, blank=True)
    serial_number = models.CharField(
        _("serial number"), max_length=100, blank=True
    )
    vendor = models.CharField(_("vendor"), max_length=200, blank=True)
    personal_data = models.BooleanField(
        _("holds personal data"), default=False
    )
    part_of = models.ForeignKey(
        "self",
        verbose_name=_("part of"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parts",
    )
    acquired_on = models.DateField(_("acquired on"), null=True, blank=True)
    review_on = models.DateField(_("next review on"), null=True, blank=True)

    class Meta:
        ordering = ("reference",)
        verbose_name = _("asset")
        verbose_name_plural = _("assets")

    def __str__(self) -> str:
        return f"{self.reference} {self.name}".strip()

    @property
    def criticality(self) -> int:
        """The highest of its three ratings: the asset is as critical as
        its most demanding need."""
        return max(self.confidentiality, self.integrity, self.availability)

    def save(self, *args, **kwargs) -> None:
        with transaction.atomic():
            number(self, REFERENCE_PATTERN, "iso.asset")
            super().save(*args, **kwargs)


class Assignment(models.Model):
    """An asset handed to a person, and when it came back (A.5.11)."""

    asset = models.ForeignKey(
        Asset,
        verbose_name=_("asset"),
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    holder = models.ForeignKey(
        USER,
        verbose_name=_("holder"),
        on_delete=models.PROTECT,
        related_name="asset_assignments",
    )
    assigned_on = models.DateField(
        _("assigned on"), default=timezone.localdate
    )
    due_back_on = models.DateField(_("due back on"), null=True, blank=True)
    returned_on = models.DateField(_("returned on"), null=True, blank=True)
    condition = models.CharField(
        _("condition on return"), max_length=200, blank=True
    )
    accepted_rules = models.BooleanField(
        _("accepted the rules of use"),
        default=False,
        help_text=_("The holder accepted the acceptable use rules (A.5.10)."),
    )

    class Meta:
        ordering = ("-assigned_on", "-pk")
        verbose_name = _("assignment")
        verbose_name_plural = _("assignments")

    def __str__(self) -> str:
        return f"{self.asset} - {self.holder}"

    @property
    def is_open(self) -> bool:
        return self.returned_on is None


class Maintenance(models.Model):
    """Maintenance done on an asset (A.7.13)."""

    class Kind(models.TextChoices):
        PREVENTIVE = "preventive", _("Preventive")
        CORRECTIVE = "corrective", _("Corrective")
        UPDATE = "update", _("Update")

    asset = models.ForeignKey(
        Asset,
        verbose_name=_("asset"),
        on_delete=models.CASCADE,
        related_name="maintenances",
    )
    performed_on = models.DateField(
        _("performed on"), default=timezone.localdate
    )
    kind = models.CharField(_("kind"), max_length=12, choices=Kind.choices)
    performed_by = models.CharField(_("performed by"), max_length=200)
    description = models.TextField(_("description"), blank=True)
    next_due_on = models.DateField(_("next due on"), null=True, blank=True)

    class Meta:
        ordering = ("-performed_on", "-pk")
        verbose_name = _("maintenance")
        verbose_name_plural = _("maintenances")

    def __str__(self) -> str:
        return f"{self.asset} - {self.performed_on}"


class Disposal(models.Model):
    """How an asset left: its data destroyed, by whom (A.7.10, A.7.14).

    Saving one marks the asset disposed.
    """

    class Method(models.TextChoices):
        WIPE = "wipe", _("Secure erase")
        DEGAUSS = "degauss", _("Degaussing")
        SHRED = "shred", _("Physical destruction")
        CRYPTO = "crypto", _("Cryptographic erase")
        RETURN = "return", _("Returned to the vendor")
        DELETE = "delete", _("Data deletion")

    asset = models.OneToOneField(
        Asset,
        verbose_name=_("asset"),
        on_delete=models.CASCADE,
        related_name="disposal",
    )
    disposed_on = models.DateField(
        _("disposed on"), default=timezone.localdate
    )
    method = models.CharField(
        _("method"), max_length=10, choices=Method.choices
    )
    standard = models.CharField(
        _("standard followed"),
        max_length=200,
        blank=True,
        help_text=_("For example NIST SP 800-88 Purge."),
    )
    performed_by = models.CharField(_("performed by"), max_length=200)
    verified_by = models.ForeignKey(
        USER,
        verbose_name=_("verified by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    certificate = models.FileField(
        _("certificate"), upload_to="iso/disposals/", blank=True
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        ordering = ("-disposed_on", "-pk")
        verbose_name = _("disposal")
        verbose_name_plural = _("disposals")

    def __str__(self) -> str:
        return f"{self.asset} - {self.get_method_display()}"

    def save(self, *args, **kwargs) -> None:
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.asset.status != Asset.Status.DISPOSED:
                self.asset.status = Asset.Status.DISPOSED
                self.asset.save(update_fields=["status"])

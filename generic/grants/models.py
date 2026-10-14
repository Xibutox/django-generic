"""One person asking for a right the project gives on request only."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AccessRequest(models.Model):
    """Somebody asking to export tables, or to download files.

    One open request per person and kind: asking again reminds the
    people who decide - no more than once an
    ``ACCESS_REQUEST_INTERVAL`` - rather than adding a row. The two
    rights themselves are permissions of this model, so they are given
    like any other: to a person, to a group, or by granting a request.
    """

    class Kind(models.TextChoices):
        EXPORT = "export", _("Export tables")
        DOWNLOAD = "download", _("Download files")

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting")
        GRANTED = "granted", _("Granted")
        REFUSED = "refused", _("Refused")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("asked by"),
        on_delete=models.CASCADE,
        related_name="generic_access_requests",
    )
    kind = models.CharField(_("right"), max_length=12, choices=Kind.choices)
    status = models.CharField(
        _("status"),
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )
    #: Why they need it, in their words.
    message = models.TextField(_("message"), blank=True, default="")
    #: The page they asked from: what they were trying to export.
    page = models.CharField(_("asked from"), max_length=500, blank=True)
    asked_at = models.DateTimeField(_("asked on"), default=timezone.now)
    #: The last time they asked - the first time, or a reminder.
    last_asked_at = models.DateTimeField(
        _("last asked on"), default=timezone.now
    )
    times_asked = models.PositiveIntegerField(_("times asked"), default=1)
    #: When the people who decide were last told.
    notified_at = models.DateTimeField(
        _("last notified on"), null=True, blank=True
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("decided by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(_("decided on"), null=True, blank=True)

    class Meta:
        verbose_name = _("access request")
        verbose_name_plural = _("access requests")
        ordering = ("-last_asked_at", "-pk")
        indexes = (
            models.Index(
                fields=("user", "kind", "status"),
                name="generic_accessrequest_open",
            ),
        )
        permissions = (
            ("export_rows", _("Can export tables")),
            ("download_files", _("Can download files")),
            ("validate_accessrequest", _("Can validate access requests")),
        )

    def __str__(self) -> str:
        return f"{self.user}: {self.get_kind_display()}"

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

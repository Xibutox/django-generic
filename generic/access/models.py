"""One look at one record: its page opened, or one of its files
downloaded."""

from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AccessEntry(models.Model):
    """Who opened which record, or downloaded which of its files."""

    class Action(models.TextChoices):
        VIEWED = "viewed", _("Opened")
        DOWNLOADED = "downloaded", _("Downloaded")

    content_type = models.ForeignKey(
        ContentType,
        verbose_name=_("model"),
        on_delete=models.CASCADE,
    )
    object_id = models.CharField(_("record"), max_length=64)
    #: ``app.model:pk`` - one value a list filters on, from a link on
    #: the record's page.
    record_key = models.CharField(
        _("record key"), max_length=120, db_index=True
    )
    #: What the record was called then: it may be gone since.
    label = models.CharField(_("record"), max_length=200, blank=True)
    action = models.CharField(
        _("access"),
        max_length=12,
        choices=Action.choices,
        default=Action.VIEWED,
    )
    #: The file downloaded, or what was opened when not the page itself.
    detail = models.CharField(_("detail"), max_length=255, blank=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generic_access_entries",
    )
    #: Their name then, for the day the account is gone.
    user_label = models.CharField(_("by"), max_length=200, blank=True)
    address = models.GenericIPAddressField(_("address"), null=True, blank=True)
    at = models.DateTimeField(_("when"), default=timezone.now)

    class Meta:
        verbose_name = _("access")
        verbose_name_plural = _("access log")
        ordering = ("-at", "-pk")
        indexes = (
            models.Index(fields=("-at",), name="generic_access_at_idx"),
        )

    def __str__(self) -> str:
        return f"{self.user_label}: {self.label} ({self.get_action_display()})"

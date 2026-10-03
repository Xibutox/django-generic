"""The counters behind numbers: one row per series."""

from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Sequence(models.Model):
    """The last number given in one series.

    A series is named by its ``key`` - ``"documents:LEG-CTR-2026-#"`` -
    so a pattern holding the year starts again at 1 every year, and
    each team, each type, gets its own count.
    """

    key = models.CharField(_("series"), max_length=255, unique=True)
    value = models.PositiveBigIntegerField(_("last number"), default=0)
    updated_at = models.DateTimeField(_("updated at"), default=timezone.now)

    class Meta:
        ordering = ("key",)
        verbose_name = _("number sequence")
        verbose_name_plural = _("number sequences")

    def __str__(self) -> str:
        return f"{self.key}: {self.value}"

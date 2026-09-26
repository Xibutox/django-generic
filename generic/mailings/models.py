"""The mailing: which table, as whom, to whom, and when."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ScheduledMailing(models.Model):
    """A table sent by e-mail, on a schedule, to some people."""

    class Format(models.TextChoices):
        XLSX = "xlsx", _("Excel")
        CSV = "csv", _("CSV")

    class Frequency(models.TextChoices):
        DAILY = "daily", _("Every day")
        WEEKDAYS = "weekdays", _("Every weekday")
        WEEKLY = "weekly", _("Every week")
        MONTHLY = "monthly", _("Every month")

    class Weekday(models.IntegerChoices):
        MONDAY = 0, _("Monday")
        TUESDAY = 1, _("Tuesday")
        WEDNESDAY = 2, _("Wednesday")
        THURSDAY = 3, _("Thursday")
        FRIDAY = 4, _("Friday")
        SATURDAY = 5, _("Saturday")
        SUNDAY = 6, _("Sunday")

    name = models.CharField(
        _("name"),
        max_length=120,
        help_text=_("The subject of every e-mail."),
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("owner"),
        on_delete=models.CASCADE,
        related_name="generic_mailings",
        null=True,
        blank=True,
        editable=False,
    )
    #: The list's state key: ``site.<app>.<model>``.
    table = models.CharField(
        _("table"),
        max_length=150,
        db_index=True,
        help_text=_("The list it sends, as the site names it."),
    )
    #: What a saved view holds: columns, order, filters, search.
    state = models.JSONField(
        _("layout"),
        default=dict,
        blank=True,
        help_text=_("Columns, order, filters and search of the list."),
    )
    format = models.CharField(
        _("format"),
        max_length=4,
        choices=Format.choices,
        default=Format.XLSX,
    )
    frequency = models.CharField(
        _("frequency"),
        max_length=10,
        choices=Frequency.choices,
        default=Frequency.WEEKDAYS,
    )
    time = models.TimeField(
        _("time"),
        default="08:00",
        help_text=_("In the application's time zone."),
    )
    weekday = models.PositiveSmallIntegerField(
        _("day of the week"),
        choices=Weekday.choices,
        default=Weekday.MONDAY,
        help_text=_("For a weekly mailing."),
    )
    day_of_month = models.PositiveSmallIntegerField(
        _("day of the month"),
        default=1,
        help_text=_("For a monthly mailing: 1 to 28, so every month has it."),
    )
    include_owner = models.BooleanField(
        _("send it to me"),
        default=True,
    )
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("people"),
        blank=True,
        related_name="+",
    )
    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name=_("groups"),
        blank=True,
        related_name="+",
        help_text=_("Every active member of these groups."),
    )
    send_when_empty = models.BooleanField(
        _("send when empty"),
        default=False,
        help_text=_("Otherwise a list with no rows is not sent."),
    )
    is_active = models.BooleanField(_("active"), default=True)
    next_run_at = models.DateTimeField(
        _("next sending"),
        null=True,
        blank=True,
        editable=False,
        db_index=True,
    )
    last_sent_at = models.DateTimeField(
        _("last sent"),
        null=True,
        blank=True,
        editable=False,
    )
    last_error = models.TextField(
        _("last problem"),
        blank=True,
        default="",
        editable=False,
    )
    created_at = models.DateTimeField(
        _("created at"), default=timezone.now, editable=False
    )

    class Meta:
        ordering = ("name", "pk")
        verbose_name = _("scheduled mailing")
        verbose_name_plural = _("scheduled mailings")

    def __str__(self) -> str:
        return self.name

    def recipients(self) -> list[Any]:
        """Active accounts with an address, each once."""
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        condition = models.Q(pk__in=self.users.values("pk")) | models.Q(
            groups__in=self.groups.values("pk")
        )

        if self.include_owner and self.owner_id:
            condition |= models.Q(pk=self.owner_id)

        return list(
            user_model._default_manager.filter(condition, is_active=True)
            .exclude(email="")
            .distinct()
            .order_by("pk")
        )

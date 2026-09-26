"""Stored notifications, and the messages people write to each other.

An event is transient: it reaches whoever is connected right now. A
notification is the durable half, so a user who was offline still finds
out. The two are linked but independent - broadcasting a transient event
never has to touch the database.

A message is what an administrator writes to some people, or to all of
them: it reaches each of them as a notification, an e-mail or both, as
they chose, and stays behind as the record of what was said to whom.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.conf import settings
from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRelation,
)
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class NotificationLevel(models.IntegerChoices):
    INFO = 1, _("Info")
    SUCCESS = 2, _("Success")
    WARNING = 3, _("Warning")
    CRITICAL = 4, _("Critical")


class NotificationQuerySet(models.QuerySet):
    def for_user(self, user: Any) -> "NotificationQuerySet":
        return self.filter(user=user)

    def unread(self) -> "NotificationQuerySet":
        return self.filter(read_at__isnull=True)

    def read(self) -> "NotificationQuerySet":
        return self.filter(read_at__isnull=False)

    def mark_read(self) -> int:
        """Mark the selection read, leaving already read rows alone."""
        return self.unread().update(read_at=timezone.now())

    def mark_unread(self) -> int:
        return self.read().update(read_at=None)


class NotificationManager(
    models.Manager.from_queryset(NotificationQuerySet)  # type: ignore[misc]
):
    def notify(
        self,
        users: Iterable[Any],
        *,
        title: str,
        body: str = "",
        level: int = NotificationLevel.INFO,
        url: str = "",
        content_object: Any = None,
        **extra: Any,
    ) -> list["Notification"]:
        """Create one notification per user in a single query.

        Returns the created rows so a caller can publish them; the
        ``post_save`` signal does not fire for a bulk create, which is
        why :func:`generic.events.bus.publish_notifications` exists.
        """
        content_type = None
        object_id = None

        if content_object is not None:
            content_type = ContentType.objects.get_for_model(content_object)
            object_id = content_object.pk

        notifications = [
            self.model(
                user=user,
                title=title,
                body=body,
                level=level,
                url=url,
                content_type=content_type,
                object_id=object_id,
                **extra,
            )
            for user in users
        ]

        return self.bulk_create(notifications)


class Notification(models.Model):
    """A message addressed to one user."""

    objects = NotificationManager()

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("User"),
        help_text=_("Recipient of this notification."),
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )

    title = models.CharField(
        verbose_name=_("Title"),
        max_length=200,
    )

    body = models.TextField(
        verbose_name=_("Body"),
        blank=True,
        default="",
    )

    level = models.PositiveSmallIntegerField(
        verbose_name=_("Level"),
        choices=NotificationLevel.choices,
        default=NotificationLevel.INFO,
        db_index=True,
    )

    url = models.CharField(
        verbose_name=_("Link"),
        help_text=_("Where clicking the notification leads."),
        max_length=500,
        blank=True,
        default="",
    )

    # Optional link to whatever the notification is about.
    content_type = models.ForeignKey(
        ContentType,
        verbose_name=_("Model"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    object_id = models.PositiveBigIntegerField(
        verbose_name=_("Object id"),
        null=True,
        blank=True,
    )
    content_object = GenericForeignKey("content_type", "object_id")

    created_at = models.DateTimeField(
        verbose_name=_("Created at"),
        default=timezone.now,
        db_index=True,
    )

    read_at = models.DateTimeField(
        verbose_name=_("Read at"),
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        indexes = (
            # Every unread badge query filters on exactly this pair.
            models.Index(
                fields=("user", "read_at"),
                name="generic_notif_user_read_idx",
            ),
        )

    def __str__(self) -> str:
        return self.title

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self, *, commit: bool = True) -> None:
        if self.read_at is not None:
            return

        self.read_at = timezone.now()

        if commit:
            self.save(update_fields=["read_at"])

    def mark_unread(self, *, commit: bool = True) -> None:
        if self.read_at is None:
            return

        self.read_at = None

        if commit:
            self.save(update_fields=["read_at"])


class Message(models.Model):
    """Something an administrator said to some people.

    Written once and sent as it is saved - one notification per
    recipient, pointing back here - then never edited: it is the record
    of what was said. Deleting it withdraws the notifications it left
    in the recipients' lists; an e-mail, once sent, stays sent.
    """

    class Delivery(models.TextChoices):
        PREFERENCE = "preference", _("As each person chose")
        IN_APP = "in_app", _("In the application")
        EMAIL = "email", _("By e-mail")
        BOTH = "both", _("Both")

    title = models.CharField(
        verbose_name=_("Title"),
        max_length=200,
    )

    body = models.TextField(
        verbose_name=_("Message"),
        blank=True,
        default="",
    )

    level = models.PositiveSmallIntegerField(
        verbose_name=_("Level"),
        choices=NotificationLevel.choices,
        default=NotificationLevel.INFO,
    )

    url = models.CharField(
        verbose_name=_("Link"),
        help_text=_(
            "Where clicking the notification leads: an address on this "
            "site, such as /tickets/, or a full one."
        ),
        max_length=500,
        blank=True,
        default="",
    )

    everyone = models.BooleanField(
        verbose_name=_("Everyone"),
        default=False,
        help_text=_("Every active account, whatever is chosen below."),
    )

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("People"),
        blank=True,
        related_name="+",
    )

    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name=_("Groups"),
        help_text=_("Every active member of these groups."),
        blank=True,
        related_name="+",
    )

    delivery = models.CharField(
        verbose_name=_("Delivered"),
        max_length=12,
        choices=Delivery.choices,
        default=Delivery.PREFERENCE,
        help_text=_(
            "In the application: the bell, the notifications page, and a "
            "toast on every page open. Each person chooses in their "
            "preferences unless this says otherwise."
        ),
    )

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Sent by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )

    sent_at = models.DateTimeField(
        verbose_name=_("Sent at"),
        default=timezone.now,
        editable=False,
        db_index=True,
    )

    recipient_count = models.PositiveIntegerField(
        verbose_name=_("Recipients"),
        default=0,
        editable=False,
    )

    #: The notifications it left. Deleting the message takes them along.
    notifications = GenericRelation(Notification)

    class Meta:
        ordering = ("-sent_at", "-pk")
        verbose_name = _("Message")
        verbose_name_plural = _("Messages")

    def __str__(self) -> str:
        return self.title

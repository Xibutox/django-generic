"""One version of one record.

The row holds the record's own fields as they were, not the difference
from the version before: a difference is derived when the history is
read, and derived values do not go stale when the model gains or loses
a field.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class HistoryQuerySet(models.QuerySet):
    def of(self, thing: Any) -> "HistoryQuerySet":
        """Every entry of one record, or of one model."""
        from django.db.models import Model
        from django.utils.encoding import force_str

        content_type = ContentType.objects.get_for_model(thing)

        if isinstance(thing, type) and issubclass(thing, Model):
            return self.filter(content_type=content_type)

        return self.filter(
            content_type=content_type,
            object_id=force_str(thing.pk),
        )


class HistoryEntry(models.Model):
    """What a record looked like after one change to it."""

    objects = HistoryQuerySet.as_manager()

    class Action(models.TextChoices):
        CREATED = "created", _("Created")
        UPDATED = "updated", _("Changed")
        DELETED = "deleted", _("Deleted")

    content_type = models.ForeignKey(
        ContentType,
        verbose_name=_("model"),
        on_delete=models.CASCADE,
    )
    #: Text, like a watch's, so a model keyed on a UUID or a code keeps
    #: a history too.
    object_id = models.CharField(_("record"), max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")

    #: What the record was called at that point. The record itself may
    #: be gone - the last entry is the one saying so - and a history
    #: that could only read live rows could not show that.
    label = models.CharField(_("record"), max_length=200, blank=True)

    #: 1 for the first entry, counted per record. Two writes of one
    #: unit of work share a version: they are one change.
    version = models.PositiveIntegerField(_("version"), default=1)
    action = models.CharField(
        _("change"),
        max_length=10,
        choices=Action.choices,
        default=Action.UPDATED,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generic_history_entries",
    )
    #: Their name as it was written then, kept for the day the account
    #: is deleted and the entry still has to say who.
    user_label = models.CharField(_("by"), max_length=200, blank=True)
    #: What was doing the changing when it was not a person at a screen:
    #: a task, an import, a command.
    source = models.CharField(_("source"), max_length=80, blank=True)

    at = models.DateTimeField(_("when"), default=timezone.now)

    #: The unit of work this entry belongs to - one request, or one
    #: ``acting_as`` block. Several saves of the same record inside one
    #: are the same change, and fold into a single entry.
    batch = models.CharField(max_length=32, blank=True, default="")

    #: The record's own fields, by field name, JSON-safe. Relations are
    #: held as keys; what they were called is looked up when read.
    values = models.JSONField(_("values"), default=dict, blank=True)

    class Meta:
        verbose_name = _("history entry")
        verbose_name_plural = _("history")
        ordering = ("-at", "-pk")
        indexes = (
            # A record's own history, newest first: the tab's query.
            models.Index(
                fields=("content_type", "object_id", "-version"),
                name="generic_history_target_idx",
            ),
            models.Index(fields=("-at",), name="generic_history_at_idx"),
        )

    def __str__(self) -> str:
        return f"{self.label or self.object_id} ({self.version})"

    @property
    def model_label(self) -> str:
        """``app.model``, as the client names a model everywhere else."""
        return f"{self.content_type.app_label}.{self.content_type.model}"

    @property
    def who(self) -> str:
        """Who made the change, in words, however little is known."""
        if self.user_label:
            return self.user_label

        if self.user is not None:
            return str(self.user)

        return str(self.source or _("the application"))

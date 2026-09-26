"""What one user asked to be told about.

A watch is one row: this user, this model, and either one record of it
or all of them. Everything else on the row is how they want to hear -
which changes, through which channels - so the same table answers both
"tell me about this ticket" and "tell me about every ticket", and the
delivery reads one shape either way.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from generic.delivery import ALL, CHANNELS, preferred_channels

#: What can happen to a record. A watch on one record never sees
#: ``created`` - it did not exist to be watched - which is why the
#: default differs between the two kinds.
EVENTS = ("created", "updated", "deleted")

EVENT_LABELS = {
    "created": _("Created"),
    "updated": _("Changed"),
    "deleted": _("Deleted"),
}

CHANNEL_LABELS = {
    "notification": _("Notification"),
    "mail": _("E-mail"),
}


class WatchQuerySet(models.QuerySet):
    def of(self, model: Any) -> "WatchQuerySet":
        """Every watch on this model, whole or one record of it."""
        return self.filter(
            content_type=ContentType.objects.get_for_model(model)
        )

    def whole_model(self) -> "WatchQuerySet":
        return self.filter(object_id="")

    def records(self) -> "WatchQuerySet":
        return self.exclude(object_id="")


class Watch(models.Model):
    """One user, one model or one record of it, and how to be told."""

    objects = WatchQuerySet.as_manager()

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        on_delete=models.CASCADE,
        related_name="generic_watches",
    )
    content_type = models.ForeignKey(
        ContentType,
        verbose_name=_("model"),
        on_delete=models.CASCADE,
    )
    #: Text, so a model keyed on a UUID or a code can be watched too.
    #: Empty means the model itself, every record of it.
    object_id = models.CharField(
        _("record"),
        max_length=64,
        blank=True,
        default="",
        help_text=_("Empty to watch every record of the model."),
    )
    content_object = GenericForeignKey("content_type", "object_id")

    #: What the record was called when it was watched. Kept so a watch
    #: still reads as something after the record is deleted - which is
    #: one of the things it exists to announce.
    label = models.CharField(_("label"), max_length=200, blank=True)

    events = models.JSONField(
        _("changes"),
        default=list,
        blank=True,
        help_text=_("Which changes are worth a message."),
    )
    channels = models.JSONField(
        _("how"),
        default=list,
        blank=True,
        help_text=_("Empty to follow the choice made in your preferences."),
    )

    created_at = models.DateTimeField(_("watched since"), default=timezone.now)

    class Meta:
        verbose_name = _("watch")
        verbose_name_plural = _("watches")
        ordering = ("-created_at", "-pk")
        constraints = (
            models.UniqueConstraint(
                fields=("user", "content_type", "object_id"),
                name="generic_watch_once_each",
            ),
        )
        indexes = (
            # Every change looks for the watches on its own model.
            models.Index(
                fields=("content_type", "object_id"),
                name="generic_watch_target_idx",
            ),
        )

    def __str__(self) -> str:
        return self.target_label

    # -- reading ---------------------------------------------------------

    @property
    def is_whole_model(self) -> bool:
        return not self.object_id

    @property
    def model_label(self) -> str:
        """``app.model``, as the client names a model everywhere else."""
        return f"{self.content_type.app_label}.{self.content_type.model}"

    @property
    def target_label(self) -> str:
        """What is being watched, in words."""
        model = self.content_type.model_class()

        if not self.is_whole_model:
            return self.label or f"{self.content_type.model} {self.object_id}"

        name = (
            model._meta.verbose_name_plural
            if model is not None
            else self.content_type.model
        )

        return str(name)

    def wants(self, change: str) -> bool:
        return change in (self.events or default_events(self.is_whole_model))

    def resolve_channels(self) -> tuple[str, ...]:
        """The channels this watch delivers through.

        Empty means the user never said, for this watch, so their own
        preference answers - and keeps answering if they change it.
        """
        chosen = tuple(name for name in (self.channels or ()) if name in ALL)

        return chosen or preferred_channels(self.user)

    def as_client(self) -> dict[str, Any]:
        return {
            "id": self.pk,
            "model": self.model_label,
            "objectId": self.object_id,
            "label": str(self),
            "wholeModel": self.is_whole_model,
            "events": list(self.events or default_events(self.is_whole_model)),
            "channels": list(self.resolve_channels()),
        }


def default_events(whole_model: bool) -> list[str]:
    """What a new watch listens for, until it is told otherwise."""
    return list(EVENTS) if whole_model else ["updated", "deleted"]


def clean_events(values: Any, whole_model: bool) -> list[str]:
    """The declared changes, refused down to the ones that exist."""
    if not isinstance(values, (list, tuple)):
        return default_events(whole_model)

    kept = [name for name in values if name in EVENTS]

    if not whole_model:
        kept = [name for name in kept if name != "created"]

    return kept


def clean_channels(values: Any) -> list[str]:
    """The declared channels, refused down to the ones that deliver."""
    if not isinstance(values, (list, tuple)):
        return []

    return [name for name in values if name in CHANNELS and name in ALL]

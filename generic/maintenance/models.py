"""What a planned restart is, as a row."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

#: What the comment says when the person announcing writes nothing. Not
#: translated at runtime: both languages are stored, because the people
#: reading do not all read the same one.
DEFAULT_COMMENT_EN = (
    "The application will be unavailable for a few minutes while the "
    "server restarts. Finish what you are doing and save your work."
)
DEFAULT_COMMENT_FR = (
    "L'application sera indisponible quelques minutes, le temps du "
    "redémarrage du serveur. Terminez ce que vous faites et "
    "enregistrez votre travail."
)


class RestartAnnouncementQuerySet(models.QuerySet):
    def pending(self) -> "RestartAnnouncementQuerySet":
        """Announced, not cancelled, and still in the future."""
        return self.filter(
            cancelled_at__isnull=True,
            scheduled_at__gt=timezone.now(),
        )

    def current(self) -> "RestartAnnouncement | None":
        """The next restart everyone should know about."""
        return self.pending().order_by("scheduled_at").first()


class RestartAnnouncement(models.Model):
    """A restart, announced before it happens."""

    objects = RestartAnnouncementQuerySet.as_manager()

    scheduled_at = models.DateTimeField(
        _("restart at"),
        help_text=_("When the server goes down, in your own time zone."),
    )
    duration_minutes = models.PositiveSmallIntegerField(
        _("estimated duration"),
        default=5,
        help_text=_("How long it is expected to be unavailable, in minutes."),
    )
    #: The checkbox that decides whether anything happens on its own.
    is_manual = models.BooleanField(
        _("manual operation"),
        default=True,
        help_text=_(
            "Tick it when you restart the server yourself: the "
            "application only warns people. Untick it and the server "
            "restarts itself at the hour announced."
        ),
    )
    comment_en = models.TextField(
        _("comment (English)"),
        default=DEFAULT_COMMENT_EN,
        help_text=_("Shown to everyone reading the application in English."),
    )
    comment_fr = models.TextField(
        _("comment (French)"),
        default=DEFAULT_COMMENT_FR,
        help_text=_("Shown to everyone reading the application in French."),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("announced by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generic_restart_announcements",
    )
    created_at = models.DateTimeField(_("announced at"), default=timezone.now)
    cancelled_at = models.DateTimeField(
        _("cancelled at"),
        null=True,
        blank=True,
    )
    #: Stamped when the restart was actually carried out, so a process
    #: coming back up does not run it a second time.
    restarted_at = models.DateTimeField(
        _("restarted at"),
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("-scheduled_at", "-pk")
        verbose_name = _("restart announcement")
        verbose_name_plural = _("restart announcements")

    def __str__(self) -> str:
        return str(
            _("Restart at %(time)s") % {"time": self.scheduled_at.isoformat()}
        )

    # -- state ---------------------------------------------------------

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None

    @property
    def seconds_until(self) -> int:
        """Seconds left before the restart; negative once it is past."""
        return int((self.scheduled_at - timezone.now()).total_seconds())

    def comment_for(self, language: str) -> str:
        """The comment in the language a reader is being served."""
        return (
            self.comment_fr
            if str(language or "").lower().startswith("fr")
            else self.comment_en
        )

    def as_client(self, phase: str = "announced") -> dict[str, Any]:
        """What the browser draws the banner from.

        Both comments travel: one event reaches everyone, and the people
        it reaches are not reading the same language.
        """
        return {
            "id": self.pk,
            "phase": phase,
            "scheduledAt": self.scheduled_at.isoformat(),
            "durationMinutes": self.duration_minutes,
            "isManual": self.is_manual,
            "secondsUntil": self.seconds_until,
            "comment": {"en": self.comment_en, "fr": self.comment_fr},
        }

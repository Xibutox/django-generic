"""One security event: a sign-in, a refusal, a right given, an export."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class SecurityEvent(models.Model):
    """What happened to whose account, from where, and when."""

    class Kind(models.TextChoices):
        SIGNED_IN = "signed_in", _("Signed in")
        SIGNED_OUT = "signed_out", _("Signed out")
        SIGN_IN_FAILED = "sign_in_failed", _("Sign-in failed")
        LOCKED_OUT = "locked_out", _("Sign-in locked")
        PASSWORD_CHANGED = "password_changed", _("Password changed")
        TOKEN_CREATED = "token_created", _("API token created")
        TOKEN_DELETED = "token_deleted", _("API token deleted")
        ACCESS_GRANTED = "access_granted", _("Right granted")
        ACCESS_REFUSED = "access_refused", _("Right refused")
        EXPORTED = "exported", _("Rows exported")

    kind = models.CharField(_("event"), max_length=24, choices=Kind.choices)
    #: The account it is about, when there is one - a failed sign-in
    #: may name an account that does not exist.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("account"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generic_security_events",
    )
    #: The name typed or held then: the account may be gone since, or
    #: never have existed.
    username = models.CharField(_("account name"), max_length=150)
    #: Who did it, when not the account itself: the administrator who
    #: set a password, granted a right.
    actor_label = models.CharField(_("by"), max_length=200, blank=True)
    detail = models.CharField(_("detail"), max_length=255, blank=True)
    address = models.GenericIPAddressField(_("address"), null=True, blank=True)
    user_agent = models.CharField(_("browser"), max_length=255, blank=True)
    at = models.DateTimeField(_("when"), default=timezone.now)

    class Meta:
        verbose_name = _("security event")
        verbose_name_plural = _("security events")
        ordering = ("-at", "-pk")
        indexes = (
            models.Index(fields=("-at",), name="generic_security_at_idx"),
            models.Index(
                fields=("kind", "-at"), name="generic_security_kind_idx"
            ),
        )

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.username}"

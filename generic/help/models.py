"""What an administrator sets for everyone from the help page."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

#: The schemes a link drawn in the frame may use. Anything else -
#: ``javascript:`` first of all - would run in every page.
WEB_SCHEMES = ("http", "https")


def validate_link(value: str) -> None:
    """A web address, or ``mailto:`` an address, and nothing else.

    A ticket service is usually a web page, but a team without one
    takes bug reports by e-mail.
    """
    value = str(value or "").strip()

    if not value:
        return

    if value.lower().startswith("mailto:"):
        address = value[len("mailto:") :].split("?", 1)[0]

        try:
            validate_email(address)
        except ValidationError:
            raise ValidationError(
                _("Enter an e-mail address after mailto:."),
                code="invalid",
            )

        return

    # Not URLValidator: it wants a dotted domain, and a ticket service
    # on the intranet is often reached as http://tickets/.
    try:
        parts = urlsplit(value)
    except ValueError:  # an unclosed [ in the host, for one
        parts = urlsplit("")

    if (
        parts.scheme.lower() not in WEB_SCHEMES
        or not parts.netloc
        or any(character.isspace() for character in value)
    ):
        raise ValidationError(
            _("Enter an address starting with https://, http:// or mailto:."),
            code="invalid",
        )


def safe_link(value: Any) -> str:
    """``value`` if the frame may draw it as a link, else nothing.

    The row is validated on save, but the setting it falls back to is
    the project's own text: it is checked the same way on its way out.
    """
    value = str(value or "").strip()

    try:
        validate_link(value)
    except ValidationError:
        return ""

    return value


class HelpSettings(models.Model):
    """The one row of help settings an administrator keeps.

    One row for the whole application: ``HelpSettings.current()`` reads
    it, and creates it the first time it is changed.
    """

    bug_report_url = models.CharField(
        _("link to report a bug"),
        max_length=500,
        blank=True,
        validators=[validate_link],
        help_text=_(
            "Where everyone reports a bug: your ticket service's page "
            "for a new ticket, or mailto: an address. Shown in the top "
            "bar of every page. Empty, the project's default is shown, "
            "if it has one."
        ),
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("changed by"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_at = models.DateTimeField(_("changed at"), default=timezone.now)

    class Meta:
        verbose_name = _("help settings")
        verbose_name_plural = _("help settings")

    def __str__(self) -> str:
        return str(_("Help settings"))

    @classmethod
    def current(cls) -> "HelpSettings":
        """The row, or an unsaved one holding the defaults."""
        return cls.objects.order_by("pk").first() or cls()

    @classmethod
    def bug_report_link(cls) -> str:
        """Where to report a bug: the row's link, else the setting's.

        ``GENERIC["BUG_REPORT_URL"]`` is the project's default; an
        administrator's link replaces it without a deployment.
        """
        from generic.conf import generic_settings

        try:
            saved = cls.objects.values_list(
                "bug_report_url", flat=True
            ).first()
        except Exception:  # pragma: no cover - before the first migrate
            saved = None

        return safe_link(saved) or safe_link(generic_settings.BUG_REPORT_URL)

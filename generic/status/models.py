"""The other servers a status page shows beside its own."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

#: Where ``generic.urls`` puts the status endpoint when it is mounted
#: as the installation guide says, under ``api/generic/``. An address
#: holding nothing but a host is completed with it.
DEFAULT_STATUS_PATH = "api/generic/status/"


def status_address(url: str) -> str:
    """The status endpoint behind what somebody pasted.

    A bare site (``https://erp.example.com``) gets the usual endpoint;
    anything with a path is taken as the endpoint itself, because a
    project may mount ``generic.urls`` elsewhere.
    """
    parts = urlsplit(str(url or "").strip())
    path = parts.path

    if path in ("", "/"):
        path = "/" + DEFAULT_STATUS_PATH

    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def validate_status_url(value: str) -> None:
    parts = urlsplit(str(value or "").strip())

    # Another scheme (file:, ftp:, gopher:) would let whoever edits the
    # list make this server read what it should not.
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValidationError(
            _("Enter the address of a site: http:// or https://.")
        )

    if parts.username or parts.password:
        raise ValidationError(
            _(
                "Leave the credentials out of the address: the token "
                "goes in its own field."
            )
        )


class StatusServer(models.Model):
    """A server running django-generic, whose status this one shows."""

    name = models.CharField(_("name"), max_length=100)
    url = models.URLField(
        _("address"),
        max_length=500,
        validators=[validate_status_url],
        help_text=_(
            "The other server's address (https://erp.example.com), or "
            "its status endpoint when generic.urls is mounted elsewhere: "
            "its Server status page shows the one to copy."
        ),
    )
    #: Kept as it was typed: this server must send it, so it cannot be
    #: hashed. Write only in every form, never sent back to a browser.
    token = models.CharField(
        _("token"),
        max_length=200,
        blank=True,
        default="",
        help_text=_(
            "The other server's STATUS_TOKEN. Empty keeps the current "
            "one; leave it empty on a new server only if it needs none."
        ),
    )
    description = models.CharField(
        _("description"),
        max_length=200,
        blank=True,
        default="",
        help_text=_("What runs there, for whoever reads the page."),
    )
    is_active = models.BooleanField(
        _("shown"),
        default=True,
        help_text=_("Untick it to keep the server without asking it."),
    )
    position = models.PositiveSmallIntegerField(
        _("position"),
        default=0,
        help_text=_("Servers are shown in this order, then by name."),
    )

    class Meta:
        ordering = ("position", "name", "pk")
        verbose_name = _("monitored server")
        verbose_name_plural = _("monitored servers")
        permissions = (("view_status", _("Can view the server status")),)

    def __str__(self) -> str:
        return self.name

    @property
    def status_url(self) -> str:
        return status_address(self.url)

    @property
    def site_url(self) -> str:
        """The other server's own address, for a link to it."""
        parts = urlsplit(self.url)

        return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))

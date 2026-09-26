"""A personal API token: knox's hash and expiry, and what a person needs.

It extends knox's abstract token - the hash, the key knox finds it by,
the expiry - with the name, scope and last use a person manages it by,
in a table of its own. Knox's own ``AuthToken`` is left alone, unused:
swapping it (``KNOX_TOKEN_MODEL``) would leave behind the table knox's
first migration creates regardless, which PostgreSQL then refuses to
truncate between tests.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from knox.models import AbstractAuthToken


class ApiToken(AbstractAuthToken):
    """A personal API token. The token itself is never stored."""

    class Scope(models.TextChoices):
        READ = "read", _("Read only")
        READ_WRITE = "read_write", _("Read and write")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    name = models.CharField(
        _("name"),
        max_length=80,
        default="",
        help_text=_("What uses it: a script, a report, a colleague's tool."),
    )
    scope = models.CharField(
        _("scope"),
        max_length=12,
        choices=Scope.choices,
        default=Scope.READ,
    )
    last_used_at = models.DateTimeField(
        _("last used"), null=True, blank=True, editable=False
    )

    class Meta:
        ordering = ("name", "created")
        verbose_name = _("API token")
        verbose_name_plural = _("API tokens")

    def __str__(self) -> str:
        return self.name or self.token_key

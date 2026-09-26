"""The token knox uses: its hash and expiry, and what a person needs.

``KNOX_TOKEN_MODEL = "generic_tokens.ApiToken"`` makes this the model
knox reads and writes - knox's own ``AuthToken`` is then swapped out -
so each token is one row: the hash knox checks, the expiry it enforces,
and the name, scope and last use a person manages it by.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _
from knox.models import AbstractAuthToken


class ApiToken(AbstractAuthToken):
    """A personal API token. The token itself is never stored."""

    class Scope(models.TextChoices):
        READ = "read", _("Read only")
        READ_WRITE = "read_write", _("Read and write")

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

"""Teams: who works on which records.

A team is a set of people. A record belongs to a team through a field
its resource names (``ModelResource.team_field``), and a person sees
the records of the teams they are a member of - several teams, if they
are in several. Groups still say what a person may *do* (the model
permissions); teams say *which records* they do it to.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

#: The permission that lifts the restriction: its holders - and
#: superusers, who hold every permission - see every team's records.
SEE_EVERY_TEAM = "generic_teams.see_every_team"


class Team(models.Model):
    name = models.CharField(_("name"), max_length=100, unique=True)
    description = models.TextField(_("description"), blank=True, default="")
    color = models.CharField(
        _("colour"),
        max_length=30,
        blank=True,
        default="",
        help_text=_("How the team's tag is drawn."),
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("members"),
        related_name="generic_teams",
        blank=True,
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        ordering = ("name",)
        verbose_name = _("team")
        verbose_name_plural = _("teams")
        permissions = (
            ("see_every_team", _("Can see the records of every team")),
        )

    def __str__(self) -> str:
        return self.name

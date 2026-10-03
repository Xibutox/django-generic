"""Teams on the People screens.

A member sees the teams they are in; whoever sees every team - and
holds the model permissions - makes them and says who is in each.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, QuerySet
from django.utils.translation import gettext_lazy as _

from generic.accounts.resources import GROUP
from generic.sites import ModelResource, display, site
from generic.teams.models import Team


class TeamResource(ModelResource):
    icon = "groups"
    group = GROUP
    order = 4
    description = _("Who works on which records.")

    # A team's own record is in the team: members see theirs.
    team_field = "pk"

    list_display = (
        "name",
        "member_count",
        "leaders",
        "members",
        "created_at",
    )
    search_fields = ("name", "description")
    ordering = ("name",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("name", "color"),
                    "description",
                    "leaders",
                    "members",
                )
            },
        ),
    )
    detail_stats = ("member_count",)
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "description",
                    "leaders",
                    "members",
                    "created_at",
                )
            },
        ),
    )
    readonly_fields = ("created_at",)
    form_overrides = {"color": {"widget": "color"}}

    def get_list_queryset(self, request: Any) -> QuerySet:
        return (
            super()
            .get_list_queryset(request)
            .annotate(member_total=Count("members", distinct=True))
        )

    @display(description=_("Members"), ordering="member_total")
    def member_count(self, team: Team) -> int:
        total = getattr(team, "member_total", None)

        return team.members.count() if total is None else total


def register_screens() -> None:
    if not site.is_registered(Team):
        site.register(Team, TeamResource)

"""The risk register's screens.

The list ranks risks by score, coloured by level, with the residual
level beside it; a heat map of likelihood by impact sits above it and
follows its filters. A risk's page holds its treatment plan, the assets
it threatens and the controls that treat it. *Accept* is its owner's
decision on the residual risk (6.1.3 f), kept with their name and date.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from generic.sites import (
    Board,
    Chart,
    ModelResource,
    RelatedTable,
    TabularInline,
    TagStyle,
    action,
    register,
)
from iso.common import (
    AMBER,
    BLUE,
    DARK_RED,
    GREEN,
    GREY,
    GROUP_RISKS,
    PURPLE,
    RED,
    next_year,
)
from iso.risks.models import Risk, TreatmentAction

LEVEL_COLORS = {
    "low": GREEN,
    "medium": AMBER,
    "high": RED,
    "critical": {"background": DARK_RED, "color": "#ffffff"},
}
STATUS_COLORS = {
    "identified": GREY,
    "assessed": PURPLE,
    "treating": BLUE,
    "accepted": GREEN,
    "closed": GREY,
}
STILL_OPEN = {
    "column": "status",
    "operator": "none_of",
    "value": ["closed"],
}


class TreatmentActionInline(TabularInline):
    model = TreatmentAction
    fields = ("title", "control", "owner", "due_on", "status")
    extra = 1
    classes = ("tab",)
    verbose_name_plural = _("Treatment plan")


@register(Risk)
class RiskResource(ModelResource):
    icon = "warning"
    group = GROUP_RISKS
    order = 0
    description = _(
        "Risks to the assets: rating, owner, treatment, residual risk "
        "(6.1.2, 6.1.3, 8.2, 8.3)."
    )
    list_display = (
        "reference",
        "title",
        "owner",
        "score",
        "level",
        "treatment",
        "residual_level",
        "status",
        "next_review_on",
    )
    search_fields = ("reference", "title", "threat", "vulnerability")
    tag_fields = {
        "level": TagStyle(colors=LEVEL_COLORS),
        "residual_level": TagStyle(colors=LEVEL_COLORS),
        "status": TagStyle(colors=STATUS_COLORS),
    }
    presets = {
        _("High and critical"): {
            "filters": {
                "match": "all",
                "conditions": [
                    STILL_OPEN,
                    {
                        "column": "level",
                        "operator": "any_of",
                        "value": ["high", "critical"],
                    },
                ],
            },
        },
        _("Review due"): {
            "filters": {
                "match": "all",
                "conditions": [
                    STILL_OPEN,
                    {
                        "column": "next_review_on",
                        "operator": "older_than_days",
                        "value": 1,
                    },
                ],
            },
            "order": [["next_review_on", "asc"]],
        },
    }
    fieldsets = (
        (None, {"fields": (("title", "category"), ("owner", "status"))}),
        (
            _("Scenario"),
            {"fields": (("threat", "vulnerability"), "assets", "description")},
        ),
        (
            _("Assessment"),
            {
                "fields": (("likelihood", "impact"),),
                "description": _(
                    "Before treatment. The score is likelihood times impact."
                ),
            },
        ),
        (
            _("Treatment"),
            {
                "fields": (
                    "treatment",
                    "controls",
                    ("residual_likelihood", "residual_impact"),
                    ("identified_on", "next_review_on"),
                )
            },
        ),
    )
    inlines = (TreatmentActionInline,)
    detail_fieldsets = (
        (None, {"fields": ("title", "category", "owner", "status")}),
        (
            _("Scenario"),
            {"fields": ("threat", "vulnerability", "description")},
        ),
        (
            _("Treatment"),
            {
                "fields": (
                    "treatment",
                    "residual_score",
                    "accepted_by",
                    "accepted_on",
                    "next_review_on",
                )
            },
        ),
    )
    detail_stats = ("score", "level", "residual_level")
    related_tables = (
        RelatedTable("actions", icon="checklist"),
        RelatedTable("assets", icon="inventory_2"),
        RelatedTable("controls", icon="verified_user"),
    )
    editable_fields = ("status",)
    boards = (
        Board(
            "treatment",
            field="status",
            title=_("Treatment board"),
            icon="view_kanban",
            description=_("Every risk in the column of its status."),
            color="level",
            fields=("owner", "level", "next_review_on"),
            editable=True,
            navigation=True,
        ),
    )
    charts = (
        Chart(
            "matrix",
            title=_("Risk matrix"),
            description=_("How many risks for each likelihood and impact."),
            type="heatmap",
            group_by="impact",
            split_by="likelihood",
        ),
        Chart(
            "by_level",
            title=_("By level"),
            type="donut",
            group_by="level",
            colors=LEVEL_COLORS,
        ),
    )
    list_charts = ("matrix", "by_level")
    actions = ("accept", "mark_reviewed", "delete_selected")

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        if name == "accept":
            return (
                obj.status != Risk.Status.ACCEPTED
                and request.user.has_perm("risks.accept_risk")
            )
        return True

    @action(
        description=_("Accept the residual risk"),
        icon="handshake",
        permissions=("risks.accept_risk",),
        confirm=_("Accept the residual risk of the selected risks?"),
        help=_(
            "Records that you, as risk owner, accept the risk left once "
            "its controls work - with your name and today's date."
        ),
    )
    def accept(self, request: Any, queryset: Any) -> dict:
        today = timezone.localdate()
        count = 0
        for risk in queryset.exclude(status=Risk.Status.ACCEPTED):
            if risk.residual_score is None and risk.treatment != "accept":
                continue
            risk.status = Risk.Status.ACCEPTED
            risk.accepted_by = request.user
            risk.accepted_on = today
            risk.save(update_fields=["status", "accepted_by", "accepted_on"])
            count += 1
        skipped = queryset.count() - count
        message = ngettext(
            "%(count)s risk accepted.", "%(count)s risks accepted.", count
        ) % {"count": count}
        if skipped:
            message += " " + gettext(
                "A risk being treated needs its residual rating first."
            )
            return {"message": message, "level": "warning"}
        return {"message": message, "level": "success"}

    @action(
        description=_("Mark reviewed"),
        icon="event_repeat",
        permissions=("change",),
        confirm=_("Mark the selected risks reviewed today?"),
        help=_("Records today's review and sets the next one a year away."),
    )
    def mark_reviewed(self, request: Any, queryset: Any) -> str:
        today = timezone.localdate()
        count = 0
        for risk in queryset:
            risk.next_review_on = next_year(today)
            risk.save(update_fields=["next_review_on"])
            count += 1
        return ngettext(
            "%(count)s risk reviewed.", "%(count)s risks reviewed.", count
        ) % {"count": count}


@register(TreatmentAction)
class TreatmentActionResource(ModelResource):
    icon = "checklist"
    group = GROUP_RISKS
    order = 1
    description = _("The risk treatment plan, step by step (6.1.3, 8.3).")
    list_display = (
        "title",
        "risk",
        "control",
        "owner",
        "due_on",
        "status",
        "done_on",
    )
    search_fields = ("title", "risk__reference", "risk__title")
    tag_fields = {
        "status": TagStyle(
            colors={
                "planned": GREY,
                "in_progress": BLUE,
                "done": GREEN,
                "cancelled": GREY,
            }
        )
    }
    presets = {
        _("Overdue"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "any_of",
                        "value": ["planned", "in_progress"],
                    },
                    {
                        "column": "due_on",
                        "operator": "older_than_days",
                        "value": 1,
                    },
                ],
            },
            "order": [["due_on", "asc"]],
        },
    }

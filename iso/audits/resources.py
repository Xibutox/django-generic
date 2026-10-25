"""Audits, nonconformities and corrective actions.

An audit's page lists what it found; a nonconformity's page its
actions. *Verify effectiveness* is the check 10.2 d asks for: done by
someone other than the action's owner, it records who and when, and
closes the nonconformity once every action is effective.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from generic.sites import (
    Chart,
    ModelResource,
    RelatedTable,
    TabularInline,
    TagStyle,
    action,
    display,
    register,
)
from iso.audits.models import Audit, CorrectiveAction, Nonconformity
from iso.common import (
    AMBER,
    BLUE,
    DARK_RED,
    GREEN,
    GREY,
    GROUP_AUDITS,
    PURPLE,
    RED,
)

GRADE_COLORS = {
    "major": {"background": DARK_RED, "color": "#ffffff"},
    "minor": RED,
    "observation": AMBER,
    "opportunity": BLUE,
}
ACTION_COLORS = {
    "planned": GREY,
    "in_progress": BLUE,
    "done": PURPLE,
    "effective": GREEN,
    "ineffective": RED,
}


@register(Audit)
class AuditResource(ModelResource):
    icon = "plagiarism"
    group = GROUP_AUDITS
    order = 0
    description = _(
        "The audit programme: audits, scope, conclusions (9.2, A.5.35)."
    )
    list_display = (
        "reference",
        "title",
        "kind",
        "planned_on",
        "status",
        "lead_auditor",
        "finding_count",
    )
    search_fields = ("reference", "title", "scope")
    tag_fields = {
        "status": TagStyle(
            colors={
                "planned": GREY,
                "in_progress": BLUE,
                "reported": AMBER,
                "closed": GREEN,
            }
        )
    }
    fieldsets = (
        (None, {"fields": (("title", "kind"), ("planned_on", "status"))}),
        (_("Scope"), {"fields": ("scope", "criteria", "controls")}),
        (
            _("Team and result"),
            {
                "fields": (
                    ("lead_auditor", "auditors"),
                    "performed_on",
                    "conclusion",
                    "report",
                )
            },
        ),
    )
    detail_stats = ("finding_count",)
    related_tables = (
        RelatedTable("findings", icon="report"),
        RelatedTable("controls", icon="verified_user"),
    )

    def get_list_queryset(self, request: Any) -> Any:
        return (
            super()
            .get_list_queryset(request)
            .annotate(findings_count=Count("findings", distinct=True))
        )

    @display(description=_("Findings"), ordering="findings_count")
    def finding_count(self, audit: Audit) -> int:
        count = getattr(audit, "findings_count", None)
        return audit.findings.count() if count is None else count


class CorrectiveActionInline(TabularInline):
    model = CorrectiveAction
    fields = ("title", "kind", "owner", "due_on", "status")
    extra = 1
    classes = ("tab",)
    verbose_name_plural = _("Actions")


@register(Nonconformity)
class NonconformityResource(ModelResource):
    icon = "report"
    group = GROUP_AUDITS
    order = 1
    custom_fields = True
    description = _(
        "Nonconformities from audits, incidents and reviews, and their "
        "causes (10.2)."
    )
    list_display = (
        "reference",
        "title",
        "grade",
        "source",
        "requirement",
        "owner",
        "raised_on",
        "status",
        "open_actions",
    )
    search_fields = ("reference", "title", "description", "requirement")
    tag_fields = {
        "grade": TagStyle(colors=GRADE_COLORS),
        "status": TagStyle(
            colors={
                "open": RED,
                "planned": BLUE,
                "verifying": AMBER,
                "closed": GREEN,
            }
        ),
    }
    presets = {
        _("Open"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "none_of",
                        "value": ["closed"],
                    }
                ],
            },
        },
    }
    fieldsets = (
        (None, {"fields": ("title", ("grade", "status"), "description")}),
        (
            _("Origin"),
            {"fields": (("source", "audit"), ("requirement", "control"))},
        ),
        (
            _("Handling"),
            {"fields": (("owner", "raised_on"), "root_cause")},
        ),
    )
    inlines = (CorrectiveActionInline,)
    detail_stats = ("grade", "status", "open_actions")
    related_tables = (RelatedTable("actions", icon="build_circle"),)
    charts = (
        Chart(
            "by_grade",
            title=_("By grade"),
            type="bar",
            group_by="grade",
            split_by="status",
            stacked=True,
        ),
    )
    list_charts = ("by_grade",)

    def get_list_queryset(self, request: Any) -> Any:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                open_count=Count(
                    "actions",
                    filter=~Q(actions__status="effective"),
                    distinct=True,
                )
            )
        )

    @display(description=_("Actions not effective yet"), ordering="open_count")
    def open_actions(self, nc: Nonconformity) -> int:
        count = getattr(nc, "open_count", None)
        if count is None:
            count = nc.actions.exclude(status="effective").count()
        return count


@register(CorrectiveAction)
class CorrectiveActionResource(ModelResource):
    icon = "build_circle"
    group = GROUP_AUDITS
    order = 2
    description = _("Corrective actions and their effectiveness (10.2).")
    list_display = (
        "title",
        "nonconformity",
        "kind",
        "owner",
        "due_on",
        "status",
        "verified_by",
        "verified_on",
    )
    search_fields = ("title", "nonconformity__reference")
    tag_fields = {"status": TagStyle(colors=ACTION_COLORS)}
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
    actions = ("verify_effective", "verify_ineffective")

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        return obj.status == CorrectiveAction.Status.DONE

    def verify(self, request: Any, queryset: Any, effective: bool) -> dict:
        today = timezone.localdate()
        done = queryset.filter(status=CorrectiveAction.Status.DONE)
        # Nobody checks their own work.
        mine = done.filter(owner=request.user).count()
        count = 0
        for item in done.exclude(owner=request.user):
            item.status = (
                CorrectiveAction.Status.EFFECTIVE
                if effective
                else CorrectiveAction.Status.INEFFECTIVE
            )
            item.verified_by = request.user
            item.verified_on = today
            item.save(update_fields=["status", "verified_by", "verified_on"])
            count += 1
            nc = item.nonconformity
            if (
                effective
                and not nc.actions.exclude(
                    status=CorrectiveAction.Status.EFFECTIVE
                ).exists()
            ):
                nc.status = Nonconformity.Status.CLOSED
                nc.save()
        message = ngettext(
            "%(count)s action verified.", "%(count)s actions verified.", count
        ) % {"count": count}
        if mine:
            message += " " + gettext(
                "The actions you own are left to someone else to verify."
            )
            return {"message": message, "level": "warning"}
        return {"message": message, "level": "success"}

    @action(
        description=_("Verify: effective"),
        icon="verified",
        permissions=("change",),
        confirm=_("Confirm the selected actions removed the cause?"),
        help=_(
            "Records that the action removed the cause, with your name. "
            "The nonconformity closes once all its actions are effective."
        ),
    )
    def verify_effective(self, request: Any, queryset: Any) -> dict:
        return self.verify(request, queryset, effective=True)

    @action(
        description=_("Verify: not effective"),
        icon="unpublished",
        permissions=("change",),
        confirm=_("Record that the selected actions did not work?"),
        help=_("Records that the cause is still there: plan another action."),
    )
    def verify_ineffective(self, request: Any, queryset: Any) -> dict:
        return self.verify(request, queryset, effective=False)

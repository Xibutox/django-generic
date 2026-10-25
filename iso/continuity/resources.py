"""Services and their impact analysis, continuity plans, exercises.

The services' list is the business impact analysis: criticality, RTO,
RPO and MTPD side by side, with the date each service was last tested.
An exercise shows whether the recovery times achieved met the targets.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from generic.sites import (
    Chart,
    ModelResource,
    RelatedTable,
    TagStyle,
    display,
    register,
)
from iso.common import (
    AMBER,
    BLUE,
    GREEN,
    GREY,
    GROUP_CONTINUITY,
    RED,
    SEVERITY_COLORS,
)
from iso.continuity.models import ContinuityPlan, Exercise, Service

RESULT_COLORS = {
    "planned": BLUE,
    "passed": GREEN,
    "partial": AMBER,
    "failed": RED,
}


@register(Service)
class ServiceResource(ModelResource):
    icon = "dns"
    group = GROUP_CONTINUITY
    order = 1
    description = _(
        "Business impact analysis: what each service can bear " "(A.5.30)."
    )
    list_display = (
        "name",
        "criticality",
        "rto_hours",
        "rpo_hours",
        "mtpd_hours",
        "owner",
        "analysed_on",
        "last_tested",
    )
    search_fields = ("name", "description")
    tag_fields = {"criticality": TagStyle(colors=SEVERITY_COLORS)}
    fieldsets = (
        (None, {"fields": ("name", ("owner", "criticality"), "description")}),
        (
            _("Impact analysis"),
            {
                "fields": (
                    ("rto_hours", "rpo_hours", "mtpd_hours"),
                    "impact",
                    "analysed_on",
                )
            },
        ),
        (_("Dependencies"), {"fields": ("assets",)}),
    )
    detail_stats = ("criticality", "rto_hours", "rpo_hours", "last_tested")
    related_tables = (
        RelatedTable("plans", icon="health_and_safety"),
        RelatedTable("exercises", icon="fitness_center"),
        RelatedTable("assets", icon="inventory_2"),
    )
    charts = (
        Chart(
            "by_criticality",
            title=_("By criticality"),
            type="donut",
            group_by="criticality",
            colors=SEVERITY_COLORS,
        ),
    )
    list_charts = ("by_criticality",)

    def get_list_queryset(self, request: Any) -> Any:
        return (
            super()
            .get_list_queryset(request)
            .annotate(tested_on=Max("exercises__held_on"))
        )

    @display(description=_("Last tested"), ordering="tested_on")
    def last_tested(self, service: Service) -> Any:
        if hasattr(service, "tested_on"):
            return service.tested_on
        latest = service.exercises.aggregate(last=Max("held_on"))
        return latest["last"]


@register(ContinuityPlan)
class ContinuityPlanResource(ModelResource):
    icon = "health_and_safety"
    group = GROUP_CONTINUITY
    order = 2
    description = _(
        "How each service is recovered, and kept secure meanwhile " "(A.5.29)."
    )
    list_display = ("title", "version", "status", "owner", "next_test_on")
    search_fields = ("title", "procedure")
    tag_fields = {
        "status": TagStyle(
            colors={"draft": GREY, "approved": GREEN, "retired": GREY}
        )
    }
    presets = {
        _("Test due"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "next_test_on",
                        "operator": "older_than_days",
                        "value": 1,
                    }
                ],
            },
            "order": [["next_test_on", "asc"]],
        },
    }
    fieldsets = (
        (None, {"fields": ("title", ("owner", "status", "version"))}),
        (None, {"fields": ("services", "next_test_on", "document")}),
        (
            _("Plan"),
            {"fields": ("activation", "procedure", "security_measures")},
        ),
    )
    detail_stats = ("status", "version", "next_test_on")
    related_tables = (
        RelatedTable("services", icon="dns"),
        RelatedTable("exercises", icon="fitness_center"),
    )


@register(Exercise)
class ExerciseResource(ModelResource):
    icon = "fitness_center"
    group = GROUP_CONTINUITY
    order = 3
    description = _(
        "Plan exercises and backup restore tests, against the targets "
        "(A.5.30, A.8.13, A.8.14)."
    )
    list_display = (
        "title",
        "kind",
        "service",
        "held_on",
        "result",
        "achieved_rto_hours",
        "achieved_rpo_hours",
        "met",
    )
    search_fields = ("title", "findings")
    tag_fields = {
        "result": TagStyle(colors=RESULT_COLORS),
        "kind": TagStyle(colors={"restore": BLUE}),
    }
    fieldsets = (
        (None, {"fields": ("title", ("kind", "held_on"))}),
        (None, {"fields": (("plan", "service"), "participants")}),
        (
            _("Result"),
            {
                "fields": (
                    "result",
                    ("achieved_rto_hours", "achieved_rpo_hours"),
                    "findings",
                )
            },
        ),
    )
    detail_stats = ("result", "achieved_rto_hours", "met")
    charts = (
        Chart(
            "results",
            title=_("Results"),
            type="bar",
            group_by="held_on",
            split_by="result",
            stacked=True,
            period="quarter",
            colors=RESULT_COLORS,
        ),
    )
    list_charts = ("results",)

    def get_queryset(self, request: Any) -> Any:
        return super().get_queryset(request).select_related("service")

    @display(description=_("Targets met"), boolean=True)
    def met(self, exercise: Exercise) -> bool | None:
        return exercise.target_met

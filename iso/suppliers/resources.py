"""Suppliers, their agreements and assessments.

The suppliers' list shows at a glance who is critical, who reaches
personal data, who runs a cloud service and whose review is due; a
supplier's page holds its agreements - with how many of the security
clauses were signed - and the history of its assessments.
"""

from __future__ import annotations

from typing import Any

from django.db.models import OuterRef, Subquery
from django.utils.translation import gettext_lazy as _

from generic.sites import (
    Chart,
    ModelResource,
    RelatedTable,
    TabularInline,
    TagStyle,
    display,
    register,
)
from iso.common import (
    AMBER,
    BLUE,
    GREEN,
    GREY,
    GROUP_ASSETS,
    PURPLE,
    RED,
    SEVERITY_COLORS,
)
from iso.suppliers.models import Agreement, Assessment, Supplier

RESULT_COLORS = {"approved": GREEN, "conditions": AMBER, "rejected": RED}


class AgreementInline(TabularInline):
    model = Agreement
    fields = (
        "title",
        "kind",
        "starts_on",
        "ends_on",
        "security_clauses",
        "confidentiality",
        "incident_notification",
        "right_to_audit",
    )
    extra = 0
    classes = ("tab",)
    verbose_name_plural = _("Agreements")


@register(Supplier)
class SupplierResource(ModelResource):
    icon = "local_shipping"
    group = GROUP_ASSETS
    order = 5
    description = _(
        "Suppliers, the data they reach, their agreements and "
        "assessments (A.5.19-5.23)."
    )
    list_display = (
        "name",
        "criticality",
        "data_access",
        "cloud_service",
        "status",
        "last_result",
        "next_review_on",
        "owner",
    )
    search_fields = ("name", "services", "certifications")
    tag_fields = {
        "criticality": TagStyle(colors=SEVERITY_COLORS),
        "status": TagStyle(
            colors={
                "prospect": GREY,
                "active": BLUE,
                "review": AMBER,
                "ended": GREY,
            }
        ),
        "data_access": TagStyle(
            colors={
                "none": GREY,
                "internal": BLUE,
                "confidential": AMBER,
                "personal": PURPLE,
            }
        ),
    }
    presets = {
        _("Review due"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "none_of",
                        "value": ["ended"],
                    },
                    {
                        "column": "next_review_on",
                        "operator": "older_than_days",
                        "value": 1,
                    },
                ],
            },
        },
        _("Cloud services"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {"column": "cloud_service", "operator": "is_true"}
                ],
            },
        },
    }
    fieldsets = (
        (None, {"fields": (("name", "status"), "services")}),
        (
            _("Risk"),
            {
                "fields": (
                    ("criticality", "data_access"),
                    "cloud_service",
                    ("certifications", "certification_expires_on"),
                )
            },
        ),
        (
            _("Relationship"),
            {
                "fields": (
                    ("owner", "next_review_on"),
                    ("contact_name", "contact_email"),
                    "website",
                    "notes",
                )
            },
        ),
    )
    inlines = (AgreementInline,)
    detail_stats = ("criticality", "last_result", "next_review_on")
    related_tables = (
        RelatedTable("agreements", icon="contract"),
        RelatedTable("assessments", icon="fact_check"),
    )
    charts = (
        Chart(
            "by_criticality",
            title=_("By criticality"),
            type="bar",
            group_by="criticality",
            split_by="data_access",
            stacked=True,
        ),
    )
    list_charts = ("by_criticality",)

    def get_list_queryset(self, request: Any) -> Any:
        latest = Assessment.objects.filter(supplier=OuterRef("pk")).order_by(
            "-assessed_on", "-pk"
        )
        return (
            super()
            .get_list_queryset(request)
            .annotate(latest_result=Subquery(latest.values("result")[:1]))
        )

    @display(
        description=_("Last assessment"),
        ordering="latest_result",
        tags=True,
    )
    def last_result(self, supplier: Supplier) -> Any:
        if hasattr(supplier, "latest_result"):
            value = supplier.latest_result
        else:
            latest = supplier.assessments.first()
            value = latest.result if latest else None
        if not value:
            return []
        label = Assessment.Result(value).label
        return [{"label": label, "color": RESULT_COLORS.get(value)}]


@register(Agreement)
class AgreementResource(ModelResource):
    icon = "contract"
    group = GROUP_ASSETS
    order = 6
    description = _("Supplier agreements and their security clauses (A.5.20).")
    list_display = (
        "title",
        "supplier",
        "kind",
        "starts_on",
        "ends_on",
        "clauses",
    )
    search_fields = ("title", "supplier__name")
    fieldsets = (
        (None, {"fields": ("supplier", ("title", "kind"))}),
        (None, {"fields": (("starts_on", "ends_on"), "document")}),
        (
            _("Security clauses"),
            {
                "fields": (
                    ("security_clauses", "confidentiality"),
                    ("incident_notification", "right_to_audit"),
                    ("subcontracting", "exit_clause"),
                )
            },
        ),
    )

    @display(description=_("Clauses signed"))
    def clauses(self, agreement: Agreement) -> str:
        return f"{agreement.clauses_signed} / {len(Agreement.CLAUSES)}"


@register(Assessment)
class AssessmentResource(ModelResource):
    icon = "fact_check"
    group = GROUP_ASSETS
    order = 7
    description = _("Supplier assessments and reviews (A.5.21, A.5.22).")
    list_display = (
        "supplier",
        "assessed_on",
        "method",
        "score",
        "result",
        "assessor",
        "next_assessment_on",
    )
    search_fields = ("supplier__name", "findings")
    tag_fields = {"result": TagStyle(colors=RESULT_COLORS)}

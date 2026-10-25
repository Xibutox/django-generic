"""The asset inventory's screens.

The list answers the auditor's first questions - what is there, who
owns it, how sensitive it is, who holds it now - and each asset's page
keeps its assignments, maintenance and parts. Labels print the
classification beside a QR code to the asset's page (A.5.13).
"""

from __future__ import annotations

from typing import Any

from django.db.models import OuterRef, Subquery
from django.db.models.functions import Greatest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from generic.sites import (
    Chart,
    Labels,
    ModelResource,
    RelatedTable,
    TagStyle,
    action,
    display,
    register,
)
from iso.assets.models import Asset, Assignment, Disposal, Maintenance
from iso.common import (
    AMBER,
    BLUE,
    CLASSIFICATION_COLORS,
    DARK_RED,
    GREEN,
    GREY,
    GROUP_ASSETS,
    PURPLE,
)

STATUS_COLORS = {
    "planned": GREY,
    "in_stock": PURPLE,
    "in_use": BLUE,
    "maintenance": AMBER,
    "retired": GREY,
    "disposed": DARK_RED,
}


@register(Asset)
class AssetResource(ModelResource):
    icon = "inventory_2"
    group = GROUP_ASSETS
    order = 0
    custom_fields = True
    description = _(
        "Every asset, its owner, classification and holder (A.5.9-5.13)."
    )
    list_display = (
        "reference",
        "name",
        "kind",
        "classification",
        "owner",
        "holder",
        "criticality",
        "status",
        "location",
    )
    list_display_hidden = ("location",)
    search_fields = ("reference", "name", "serial_number", "description")
    tag_fields = {
        "classification": TagStyle(colors=CLASSIFICATION_COLORS),
        "status": TagStyle(colors=STATUS_COLORS),
    }
    presets = {
        _("Personal data"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {"column": "personal_data", "operator": "is_true"}
                ],
            },
        },
        _("Confidential and restricted"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "classification",
                        "operator": "any_of",
                        "value": ["confidential", "restricted"],
                    }
                ],
            },
        },
    }
    fieldsets = (
        (None, {"fields": (("name", "kind"), ("owner", "status"))}),
        (
            _("Classification"),
            {
                "fields": (
                    "classification",
                    ("confidentiality", "integrity", "availability"),
                    "personal_data",
                ),
                "description": _(
                    "How much harm a disclosure, an alteration or a loss "
                    "would do."
                ),
            },
        ),
        (
            _("Details"),
            {
                "fields": (
                    ("location", "part_of"),
                    ("vendor", "serial_number"),
                    ("acquired_on", "review_on"),
                    "description",
                )
            },
        ),
    )
    detail_stats = ("classification", "criticality", "holder")
    related_tables = (
        RelatedTable("assignments", icon="badge"),
        RelatedTable("maintenances", icon="build"),
        RelatedTable("parts", icon="account_tree"),
    )
    labels = Labels(fields=("classification", "owner", "location"))
    charts = (
        Chart("by_kind", title=_("By kind"), type="donut", group_by="kind"),
        Chart(
            "by_classification",
            title=_("By classification"),
            type="bar",
            group_by="classification",
        ),
    )
    list_charts = ("by_kind", "by_classification")

    def get_list_queryset(self, request: Any) -> Any:
        open_assignment = Assignment.objects.filter(
            asset=OuterRef("pk"), returned_on__isnull=True
        ).order_by("-assigned_on")
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                rating=Greatest(
                    "confidentiality", "integrity", "availability"
                ),
                holder_name=Subquery(
                    open_assignment.values("holder__username")[:1]
                ),
            )
        )

    @display(description=_("Criticality"), ordering="rating")
    def criticality(self, asset: Asset) -> int:
        return getattr(asset, "rating", None) or asset.criticality

    @display(description=_("Held by"), ordering="holder_name")
    def holder(self, asset: Asset) -> str:
        if hasattr(asset, "holder_name"):
            return asset.holder_name or ""
        current = asset.assignments.filter(returned_on__isnull=True).first()
        return str(current.holder) if current else ""


@register(Assignment)
class AssignmentResource(ModelResource):
    icon = "badge"
    group = GROUP_ASSETS
    order = 1
    description = _("Who holds which asset, and its return (A.5.11).")
    list_display = (
        "asset",
        "holder",
        "assigned_on",
        "due_back_on",
        "returned_on",
        "accepted_rules",
    )
    search_fields = ("asset__name", "asset__reference", "holder__username")
    presets = {
        _("Not returned"): {
            "filters": {
                "match": "all",
                "conditions": [{"column": "returned_on", "operator": "empty"}],
            },
        },
    }
    actions = ("mark_returned", "delete_selected")

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        if name == "mark_returned":
            return obj.returned_on is None
        return True

    @action(
        description=_("Mark returned"),
        icon="assignment_return",
        permissions=("change",),
        confirm=_("Mark the selected assets returned today?"),
        help=_("Records that the asset came back today."),
    )
    def mark_returned(self, request: Any, queryset: Any) -> str:
        today = timezone.localdate()
        count = 0
        for assignment in queryset.filter(returned_on__isnull=True):
            assignment.returned_on = today
            assignment.save(update_fields=["returned_on"])
            count += 1
        return ngettext(
            "%(count)s asset returned.", "%(count)s assets returned.", count
        ) % {"count": count}


@register(Maintenance)
class MaintenanceResource(ModelResource):
    icon = "build"
    group = GROUP_ASSETS
    order = 2
    description = _("Maintenance done on the assets (A.7.13).")
    list_display = (
        "asset",
        "performed_on",
        "kind",
        "performed_by",
        "next_due_on",
    )
    search_fields = ("asset__name", "performed_by", "description")
    tag_fields = {
        "kind": TagStyle(
            colors={"preventive": GREEN, "corrective": AMBER, "update": BLUE}
        )
    }


@register(Disposal)
class DisposalResource(ModelResource):
    icon = "delete_sweep"
    group = GROUP_ASSETS
    order = 3
    description = _(
        "How assets and media were disposed of, data destroyed (A.7.14)."
    )
    list_display = (
        "asset",
        "disposed_on",
        "method",
        "standard",
        "performed_by",
        "verified_by",
    )
    search_fields = ("asset__name", "asset__reference", "performed_by")
    fieldsets = (
        (None, {"fields": ("asset", ("disposed_on", "method"), "standard")}),
        (
            _("Proof"),
            {
                "fields": (
                    ("performed_by", "verified_by"),
                    "certificate",
                    "notes",
                )
            },
        ),
    )

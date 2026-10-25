"""Controls and the Statement of Applicability; obligations.

The controls' list *is* the Statement of Applicability: its preset
shows the columns the standard asks for, and the export menu hands it
over as a spreadsheet. A control's page gathers its evidence, the
obligations it answers and - with ``iso.risks`` installed - the risks
it treats.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from generic.sites import (
    Chart,
    ModelResource,
    RelatedTable,
    TagStyle,
    action,
    register,
)
from iso.common import AMBER, BLUE, GREEN, GREY, GROUP_RISKS, RED, is_installed
from iso.compliance.models import Control, ControlEvidence, Obligation

STATUS_COLORS = {
    "not_started": GREY,
    "planned": BLUE,
    "partial": AMBER,
    "implemented": GREEN,
}


@register(Control)
class ControlResource(ModelResource):
    icon = "verified_user"
    group = GROUP_RISKS
    order = 2
    label_plural = _("Controls (SoA)")
    custom_fields = True
    description = _(
        "The 93 Annex A controls: applicability, justification, "
        "implementation - the Statement of Applicability (6.1.3)."
    )
    list_display = (
        "code",
        "title",
        "theme",
        "applicable",
        "status",
        "owner",
        "reviewed_on",
        "justification",
        "implementation",
    )
    list_display_hidden = ("justification", "implementation")
    search_fields = ("code", "title", "justification", "implementation")
    ordering = ("position",)
    tag_fields = {"status": TagStyle(colors=STATUS_COLORS)}
    presets = {
        _("Statement of Applicability"): {
            "columns": [
                "code",
                "title",
                "applicable",
                "justification",
                "status",
                "implementation",
            ],
            "order": [["code", "asc"]],
            "pageLength": 100,
        },
        _("Applicable, not implemented"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {"column": "applicable", "operator": "is_true"},
                    {
                        "column": "status",
                        "operator": "none_of",
                        "value": ["implemented"],
                    },
                ],
            },
        },
    }
    fieldsets = (
        (None, {"fields": (("code", "theme"), "title")}),
        (
            _("Applicability"),
            {"fields": ("applicable", "justification")},
        ),
        (
            _("Implementation"),
            {
                "fields": (
                    ("status", "owner"),
                    "implementation",
                    "evidence",
                    "reviewed_on",
                )
            },
        ),
    )
    readonly_fields = ("code", "theme")
    detail_stats = ("applicable", "status", "owner")
    # The risks a control treats, where the risk register is installed:
    # resources.py runs once the apps are loaded, so the question has an
    # answer here.
    related_tables = (
        RelatedTable("evidence_items", icon="attach_file"),
        RelatedTable("obligations", icon="gavel"),
    ) + (
        (RelatedTable("risks", icon="warning"),)
        if is_installed("iso.risks")
        else ()
    )
    bulk_edit_fields = ("applicable", "status", "owner", "reviewed_on")
    charts = (
        Chart(
            "implementation",
            title=_("Implementation by theme"),
            type="bar",
            group_by="theme",
            split_by="status",
            stacked=True,
            colors=STATUS_COLORS,
        ),
        Chart(
            "by_status",
            title=_("Implementation"),
            type="donut",
            group_by="status",
            colors=STATUS_COLORS,
        ),
    )
    list_charts = ("implementation", "by_status")
    actions = ("mark_reviewed",)

    def has_add_permission(self, request: Any) -> bool:
        # The catalogue is the standard's: 93 rows, loaded once.
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    @action(
        description=_("Mark reviewed"),
        icon="event_available",
        permissions=("change",),
        confirm=_("Mark the selected controls reviewed today?"),
        help=_("Records today as the date the control was last reviewed."),
    )
    def mark_reviewed(self, request: Any, queryset: Any) -> str:
        today = timezone.localdate()
        count = 0
        for control in queryset:
            control.reviewed_on = today
            control.save(update_fields=["reviewed_on"])
            count += 1
        return ngettext(
            "%(count)s control reviewed.",
            "%(count)s controls reviewed.",
            count,
        ) % {"count": count}


@register(ControlEvidence)
class ControlEvidenceResource(ModelResource):
    icon = "attach_file"
    group = GROUP_RISKS
    show_in_navigation = False
    list_display = ("title", "control", "collected_on", "collected_by", "file")
    search_fields = ("title", "control__code", "control__title")

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        if change:
            return serializer.save()
        return serializer.save(collected_by=request.user)


@register(Obligation)
class ObligationResource(ModelResource):
    icon = "gavel"
    group = GROUP_RISKS
    order = 3
    description = _(
        "Laws, regulations, contracts and standards to meet (A.5.31)."
    )
    list_display = (
        "title",
        "kind",
        "source",
        "owner",
        "status",
        "next_review_on",
    )
    search_fields = ("title", "source", "requirement")
    tag_fields = {
        "status": TagStyle(
            colors={
                "not_assessed": GREY,
                "compliant": GREEN,
                "partial": AMBER,
                "non_compliant": RED,
            }
        ),
        "kind": TagStyle(colors={"law": BLUE, "regulation": BLUE}),
    }
    fieldsets = (
        (None, {"fields": ("title", ("kind", "jurisdiction"), "source")}),
        (None, {"fields": ("requirement", "url")}),
        (
            _("Compliance"),
            {
                "fields": (
                    ("owner", "status"),
                    "controls",
                    ("assessed_on", "next_review_on"),
                )
            },
        ),
    )
    related_tables = (RelatedTable("controls", icon="verified_user"),)
    charts = (
        Chart(
            "by_status", title=_("Compliance"), type="donut", group_by="status"
        ),
    )
    list_charts = ("by_status",)

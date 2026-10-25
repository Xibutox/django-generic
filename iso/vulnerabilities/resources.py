"""The vulnerability register.

Open vulnerabilities by severity, the ones past their deadline marked,
fixes per month: whether the deadlines are kept is visible at a glance.
"""

from __future__ import annotations

from typing import Any

from django.db.models import BooleanField, Case, Q, Value, When
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from generic.sites import (
    Chart,
    ModelResource,
    RelatedTable,
    TagStyle,
    action,
    display,
    register,
)
from iso.common import (
    AMBER,
    BLUE,
    GREEN,
    GREY,
    GROUP_OPERATIONS,
    SEVERITY_COLORS,
)
from iso.vulnerabilities.models import Vulnerability

STILL_OPEN = {
    "column": "status",
    "operator": "any_of",
    "value": ["open", "in_progress"],
}


@register(Vulnerability)
class VulnerabilityResource(ModelResource):
    icon = "bug_report"
    group = GROUP_OPERATIONS
    order = 2
    custom_fields = True
    description = _(
        "Technical vulnerabilities, their severity and deadline (A.8.8)."
    )
    list_display = (
        "reference",
        "title",
        "identifier",
        "cvss",
        "severity",
        "status",
        "due_on",
        "overdue",
        "owner",
    )
    search_fields = ("reference", "title", "identifier", "description")
    tag_fields = {
        "severity": TagStyle(colors=SEVERITY_COLORS),
        "status": TagStyle(
            colors={
                "open": BLUE,
                "in_progress": AMBER,
                "fixed": GREEN,
                "accepted": GREY,
                "false_positive": GREY,
            }
        ),
    }
    presets = {
        _("Open"): {
            "filters": {"match": "all", "conditions": [STILL_OPEN]},
            "order": [["due_on", "asc"]],
        },
        _("Overdue"): {
            "filters": {
                "match": "all",
                "conditions": [{"column": "overdue", "operator": "is_true"}],
            },
            "order": [["due_on", "asc"]],
        },
    }
    fieldsets = (
        (None, {"fields": ("title", ("identifier", "source"), "description")}),
        (
            _("Severity"),
            {"fields": (("cvss", "severity"), "assets")},
        ),
        (
            _("Remediation"),
            {
                "fields": (
                    ("owner", "status"),
                    ("discovered_on", "due_on"),
                    "remediation",
                    "fixed_on",
                )
            },
        ),
    )
    detail_stats = ("severity", "due_on", "overdue")
    related_tables = (RelatedTable("assets", icon="inventory_2"),)
    charts = (
        Chart(
            "open_by_severity",
            title=_("By severity"),
            type="donut",
            group_by="severity",
        ),
        Chart(
            "discovered",
            title=_("Discovered"),
            type="bar",
            group_by="discovered_on",
            split_by="severity",
            stacked=True,
            period="month",
        ),
    )
    list_charts = ("open_by_severity", "discovered")
    actions = ("mark_fixed",)

    def get_list_queryset(self, request: Any) -> Any:
        today = timezone.localdate()
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                is_late=Case(
                    When(
                        Q(status__in=("open", "in_progress"))
                        & Q(due_on__lt=today),
                        then=Value(True),
                    ),
                    default=Value(False),
                    output_field=BooleanField(),
                )
            )
        )

    @display(
        description=_("Overdue"),
        boolean=True,
        ordering="is_late",
        filter_field="is_late",
        filter_type="boolean",
    )
    def overdue(self, vulnerability: Vulnerability) -> bool:
        if hasattr(vulnerability, "is_late"):
            return vulnerability.is_late
        return vulnerability.is_overdue

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        return obj.status in ("open", "in_progress")

    @action(
        description=_("Mark fixed"),
        icon="healing",
        permissions=("change",),
        confirm=_("Mark the selected vulnerabilities fixed today?"),
        help=_("Records the fix with today's date."),
    )
    def mark_fixed(self, request: Any, queryset: Any) -> str:
        count = 0
        for item in queryset.filter(status__in=("open", "in_progress")):
            item.status = Vulnerability.Status.FIXED
            item.save()
            count += 1
        return ngettext(
            "%(count)s vulnerability fixed.",
            "%(count)s vulnerabilities fixed.",
            count,
        ) % {"count": count}

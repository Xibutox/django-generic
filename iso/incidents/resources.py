"""Incidents: reported by anyone, worked by the security team.

Anybody holding ``incidents.add_incident`` reports an event; the
reporter and the time are stamped, never typed. The list shows what is
open by severity, the breaches whose 72 hours are running out, and an
incident's page keeps its timeline, its evidence with checksums and the
assets it touched.
"""

from __future__ import annotations

from typing import Any

from django.utils import formats, timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from generic.sites import (
    Board,
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
    GROUP_OPERATIONS,
    PURPLE,
    SEVERITY_COLORS,
)
from iso.incidents.models import Evidence, Incident, IncidentUpdate

STATUS_COLORS = {
    "reported": PURPLE,
    "triage": AMBER,
    "contained": BLUE,
    "resolved": GREEN,
    "closed": GREY,
    "not_incident": GREY,
}
STILL_OPEN = {
    "column": "status",
    "operator": "any_of",
    "value": ["reported", "triage", "contained"],
}


@register(Incident)
class IncidentResource(ModelResource):
    icon = "crisis_alert"
    group = GROUP_OPERATIONS
    order = 0
    custom_fields = True
    description = _(
        "Security events and incidents, their response and lessons "
        "(A.5.24-5.28, A.6.8)."
    )
    list_display = (
        "reference",
        "title",
        "category",
        "severity",
        "status",
        "handler",
        "detected_at",
        "personal_data_breach",
        "breach_deadline",
    )
    search_fields = ("reference", "title", "description")
    tag_fields = {
        "severity": TagStyle(colors=SEVERITY_COLORS),
        "status": TagStyle(colors=STATUS_COLORS),
    }
    presets = {
        _("Open"): {
            "filters": {"match": "all", "conditions": [STILL_OPEN]},
            "order": [["severity", "desc"]],
        },
        _("Personal data breaches"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {"column": "personal_data_breach", "operator": "is_true"}
                ],
            },
        },
    }
    fieldsets = (
        (None, {"fields": ("title", ("category", "severity"), "description")}),
        (
            _("Handling"),
            {"fields": (("status", "handler"), "detected_at", "assets")},
        ),
        (
            _("Personal data"),
            {
                "fields": (
                    "personal_data_breach",
                    ("authority_notified_at", "subjects_notified_at"),
                ),
                "description": _(
                    "A breach is notified to the authority within 72 hours "
                    "of its detection (GDPR art. 33)."
                ),
            },
        ),
        (
            _("Lessons"),
            {"fields": ("root_cause", "lessons_learned"), "classes": ("tab",)},
        ),
    )
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "category",
                    "severity",
                    "status",
                    "handler",
                    "reported_by",
                    "reported_at",
                    "detected_at",
                    "closed_at",
                )
            },
        ),
        (None, {"fields": ("description",)}),
        (
            _("Personal data"),
            {
                "fields": (
                    "personal_data_breach",
                    "breach_deadline",
                    "authority_notified_at",
                    "subjects_notified_at",
                )
            },
        ),
        (_("Lessons"), {"fields": ("root_cause", "lessons_learned")}),
    )
    detail_stats = ("severity", "status", "breach_deadline")
    related_tables = (
        RelatedTable("updates", icon="timeline"),
        RelatedTable("evidence", icon="fingerprint"),
        RelatedTable("assets", icon="inventory_2"),
    )
    editable_fields = ("status",)
    boards = (
        Board(
            "response",
            field="status",
            title=_("Response board"),
            icon="view_kanban",
            description=_("Every incident in the column of its status."),
            color="severity",
            fields=("severity", "handler", "detected_at"),
            editable=True,
            navigation=True,
        ),
    )
    charts = (
        Chart(
            "by_month",
            title=_("Incidents"),
            type="bar",
            group_by="detected_at",
            split_by="severity",
            stacked=True,
            period="month",
            periods=("week", "month", "quarter"),
        ),
        Chart(
            "by_category",
            title=_("By category"),
            type="donut",
            group_by="category",
        ),
    )
    list_charts = ("by_month", "by_category")

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        if change:
            return serializer.save()
        return serializer.save(reported_by=request.user)

    @display(description=_("Notify by"))
    def breach_deadline(self, incident: Incident) -> str:
        due = incident.notification_due
        if due is None:
            return ""
        text = formats.date_format(
            timezone.localtime(due), "SHORT_DATETIME_FORMAT"
        )
        if incident.authority_notified_at:
            return text
        if incident.notification_late:
            late = gettext("late")
            return f"{text} - {late}"
        return text


@register(IncidentUpdate)
class IncidentUpdateResource(ModelResource):
    icon = "timeline"
    group = GROUP_OPERATIONS
    show_in_navigation = False
    list_display = ("incident", "at", "kind", "text", "author")
    search_fields = ("incident__reference", "text")
    tag_fields = {
        "kind": TagStyle(
            colors={
                "note": GREY,
                "action": BLUE,
                "decision": PURPLE,
                "communication": AMBER,
            }
        )
    }

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        if change:
            return serializer.save()
        return serializer.save(author=request.user)


@register(Evidence)
class EvidenceResource(ModelResource):
    icon = "fingerprint"
    group = GROUP_OPERATIONS
    show_in_navigation = False
    list_display = (
        "title",
        "incident",
        "collected_at",
        "collected_by",
        "sha256",
    )
    search_fields = ("title", "incident__reference", "sha256")
    fieldsets = (
        (None, {"fields": ("incident", "title", "description", "file")}),
        (
            _("Custody"),
            {
                "fields": (
                    ("collected_at", "collected_by"),
                    "stored_at",
                    "custody",
                )
            },
        ),
    )
    # Who downloaded a piece of evidence is part of its custody.
    access_log = True

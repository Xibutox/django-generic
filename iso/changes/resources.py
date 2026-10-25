"""Change requests: submitted, decided, implemented, reviewed.

The buttons follow the request's life - *Submit*, *Approve* or
*Reject*, *Implemented*, *Close* - and a record's page offers only the
next steps. Approving needs ``changes.approve_changerequest`` and is
refused to the request's own requester (A.5.3). A calendar shows the
planned windows.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from generic.sites import (
    Calendar,
    Chart,
    ModelResource,
    RelatedTable,
    TagStyle,
    action,
    register,
)
from iso.changes.models import ChangeRequest
from iso.common import (
    AMBER,
    BLUE,
    DARK_RED,
    GREEN,
    GREY,
    GROUP_OPERATIONS,
    PURPLE,
    RED,
)

Status = ChangeRequest.Status

STATUS_COLORS = {
    "draft": GREY,
    "submitted": PURPLE,
    "approved": BLUE,
    "rejected": RED,
    "implemented": GREEN,
    "failed": {"background": DARK_RED, "color": "#ffffff"},
    "closed": GREY,
}

#: What each step needs the request to be in.
NEXT_STEPS = {
    "submit": (Status.DRAFT,),
    "approve": (Status.SUBMITTED,),
    "reject": (Status.SUBMITTED,),
    "mark_implemented": (Status.APPROVED,),
    "close": (Status.IMPLEMENTED, Status.FAILED, Status.REJECTED),
}


@register(ChangeRequest)
class ChangeRequestResource(ModelResource):
    icon = "published_with_changes"
    group = GROUP_OPERATIONS
    order = 3
    description = _(
        "Changes to systems: risk, tests, rollback, approval, review "
        "(A.8.32)."
    )
    list_display = (
        "reference",
        "title",
        "kind",
        "category",
        "risk",
        "status",
        "requested_by",
        "approved_by",
        "planned_start",
    )
    search_fields = ("reference", "title", "description")
    tag_fields = {
        "status": TagStyle(colors=STATUS_COLORS),
        "risk": TagStyle(colors={"low": GREEN, "medium": AMBER, "high": RED}),
        "kind": TagStyle(colors={"emergency": RED}),
    }
    presets = {
        _("Awaiting approval"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "any_of",
                        "value": ["submitted"],
                    }
                ],
            },
        },
    }
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    ("kind", "category"),
                    "description",
                    "reason",
                )
            },
        ),
        (
            _("Risk"),
            {"fields": ("assets", "risk", "impact")},
        ),
        (
            _("Plans"),
            {"fields": ("test_plan", "rollback_plan")},
        ),
        (
            _("Implementation"),
            {
                "fields": (
                    "implementer",
                    ("planned_start", "planned_end"),
                    "implemented_at",
                    "review",
                )
            },
        ),
    )
    readonly_fields = ("status",)
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "kind",
                    "category",
                    "risk",
                    "status",
                    "requested_by",
                    "approved_by",
                    "approved_at",
                    "implementer",
                )
            },
        ),
        (None, {"fields": ("description", "reason", "impact")}),
        (_("Plans"), {"fields": ("test_plan", "rollback_plan")}),
        (
            _("Implementation"),
            {
                "fields": (
                    "planned_start",
                    "planned_end",
                    "implemented_at",
                    "review",
                )
            },
        ),
    )
    detail_stats = ("status", "risk")
    related_tables = (RelatedTable("assets", icon="inventory_2"),)
    calendars = (
        Calendar(
            "planning",
            date="planned_start",
            end="planned_end",
            title=_("Change calendar"),
            icon="calendar_month",
            color="status",
            fields=("risk", "implementer"),
            navigation=True,
        ),
    )
    charts = (
        Chart(
            "by_month",
            title=_("Changes"),
            type="bar",
            group_by="planned_start",
            split_by="status",
            stacked=True,
            period="month",
        ),
    )
    list_charts = ("by_month",)
    actions = ("submit", "approve", "reject", "mark_implemented", "close")

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        if change:
            return serializer.save()
        return serializer.save(requested_by=request.user)

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        if obj.status not in NEXT_STEPS.get(name, (obj.status,)):
            return False
        if name in ("approve", "reject"):
            return obj.requested_by_id != request.user.pk
        return True

    def move(
        self,
        request: Any,
        queryset: Any,
        step: str,
        target: str,
        decide: bool = False,
    ) -> dict:
        count = 0
        skipped = 0
        for change in queryset:
            if change.status not in NEXT_STEPS[step]:
                skipped += 1
                continue
            if decide and change.requested_by_id == request.user.pk:
                skipped += 1
                continue
            change.status = target
            fields = ["status"]
            if decide:
                change.approved_by = request.user
                change.approved_at = timezone.now()
                fields += ["approved_by", "approved_at"]
            if target == Status.IMPLEMENTED and not change.implemented_at:
                change.implemented_at = timezone.now()
                fields.append("implemented_at")
            change.save(update_fields=fields)
            count += 1
        message = ngettext(
            "%(count)s change request updated.",
            "%(count)s change requests updated.",
            count,
        ) % {"count": count}
        if skipped:
            message += " " + gettext(
                "Requests at another step, or your own requests for a "
                "decision, were left as they are."
            )
            return {"message": message, "level": "warning"}
        return {"message": message, "level": "success"}

    @action(
        description=_("Submit"),
        icon="send",
        permissions=("change",),
        help=_("Sends the request for approval."),
    )
    def submit(self, request: Any, queryset: Any) -> dict:
        return self.move(request, queryset, "submit", Status.SUBMITTED)

    @action(
        description=_("Approve"),
        icon="thumb_up",
        permissions=("changes.approve_changerequest",),
        confirm=_("Approve the selected change requests?"),
        help=_(
            "Approves the change, with your name. Nobody approves their "
            "own request."
        ),
    )
    def approve(self, request: Any, queryset: Any) -> dict:
        return self.move(
            request, queryset, "approve", Status.APPROVED, decide=True
        )

    @action(
        description=_("Reject"),
        icon="thumb_down",
        permissions=("changes.approve_changerequest",),
        confirm=_("Reject the selected change requests?"),
        help=_("Refuses the change, with your name."),
    )
    def reject(self, request: Any, queryset: Any) -> dict:
        return self.move(
            request, queryset, "reject", Status.REJECTED, decide=True
        )

    @action(
        description=_("Implemented"),
        icon="rocket_launch",
        permissions=("change",),
        help=_("Records that the change was made, now."),
    )
    def mark_implemented(self, request: Any, queryset: Any) -> dict:
        return self.move(
            request, queryset, "mark_implemented", Status.IMPLEMENTED
        )

    @action(
        description=_("Close"),
        icon="inventory",
        permissions=("change",),
        help=_("Closes the request once it is reviewed."),
    )
    def close(self, request: Any, queryset: Any) -> dict:
        return self.move(request, queryset, "close", Status.CLOSED)

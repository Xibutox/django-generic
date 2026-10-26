"""The ISMS group: scope, context, interested parties, objectives,
policies and their acknowledgements, contacts, management reviews.

Each register is a list, a form and a record page; what the framework
cannot guess is said here: the latest reading of an objective against
its target, how many people acknowledged the current version of a
policy, the reviews whose actions are still open.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from generic.privacy import PersonalData
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
from iso.common import (
    AMBER,
    BLUE,
    GREEN,
    GREY,
    GROUP_ISMS,
    PURPLE,
    RED,
    next_year,
)
from iso.isms.models import (
    Acknowledgement,
    Contact,
    ContextIssue,
    InterestedParty,
    ManagementReview,
    Measurement,
    Objective,
    Policy,
    ReviewAction,
    Scope,
)

# Past its date: "more than a day ago", the filters' nearest words.
REVIEW_DUE = {
    "column": "next_review_on",
    "operator": "older_than_days",
    "value": 1,
}


@register(Scope)
class ScopeResource(ModelResource):
    icon = "crop_free"
    group = GROUP_ISMS
    order = 0
    description = _("What the ISMS covers, version by version (4.3).")
    list_display = ("title", "version", "status", "approved_by", "approved_on")
    search_fields = ("title", "statement")
    tag_fields = {
        "status": TagStyle(
            colors={"draft": AMBER, "approved": GREEN, "superseded": GREY}
        )
    }
    fieldsets = (
        (None, {"fields": (("title", "version"), "status")}),
        (None, {"fields": ("statement", "exclusions", "interfaces")}),
        (_("Approval"), {"fields": (("approved_by", "approved_on"),)}),
    )


@register(ContextIssue)
class ContextIssueResource(ModelResource):
    icon = "travel_explore"
    group = GROUP_ISMS
    order = 1
    description = _("Internal and external issues the ISMS answers (4.1).")
    list_display = (
        "title",
        "kind",
        "category",
        "effect",
        "climate_related",
        "reviewed_on",
    )
    search_fields = ("title", "description")
    tag_fields = {
        "kind": TagStyle(colors={"internal": BLUE, "external": PURPLE}),
        "effect": TagStyle(
            colors={"threat": RED, "opportunity": GREEN, "both": AMBER}
        ),
    }
    fieldsets = (
        (None, {"fields": ("title", ("kind", "category"), "effect")}),
        (
            None,
            {"fields": ("description", ("climate_related", "reviewed_on"))},
        ),
    )
    charts = (
        Chart(
            "by_category",
            title=_("By category"),
            type="bar",
            group_by="category",
            split_by="kind",
            stacked=True,
        ),
    )
    list_charts = ("by_category",)


@register(InterestedParty)
class InterestedPartyResource(ModelResource):
    icon = "diversity_3"
    group = GROUP_ISMS
    order = 2
    description = _("Who expects something of the ISMS, and what (4.2).")
    list_display = ("name", "kind", "addressed", "reviewed_on")
    search_fields = ("name", "requirements")
    fieldsets = (
        (None, {"fields": (("name", "kind"), "requirements")}),
        (
            _("Answer"),
            {
                "fields": (
                    ("addressed", "climate_requirements"),
                    "how_addressed",
                    "reviewed_on",
                )
            },
        ),
    )


@register(Measurement)
class MeasurementResource(ModelResource):
    icon = "monitoring"
    group = GROUP_ISMS
    show_in_navigation = False
    list_display = ("objective", "measured_on", "value", "comment")
    search_fields = ("objective__title", "comment")
    ordering = ("-measured_on",)
    charts = (
        Chart(
            "trend",
            title=_("Readings"),
            type="line",
            group_by="measured_on",
            value=Avg("value"),
            value_label=_("Value"),
            decimals=2,
            period="month",
            periods=("week", "month", "quarter"),
        ),
    )

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        if change:
            return serializer.save()
        return serializer.save(measured_by=request.user)


class MeasurementInline(TabularInline):
    model = Measurement
    fields = ("measured_on", "value", "comment")
    extra = 1
    classes = ("tab",)
    verbose_name_plural = _("Measurements")


@register(Objective)
class ObjectiveResource(ModelResource):
    icon = "flag"
    group = GROUP_ISMS
    order = 3
    description = _("Measurable objectives and their readings (6.2, 9.1).")
    list_display = (
        "title",
        "owner",
        "target_label",
        "latest_value",
        "met",
        "due_on",
        "status",
    )
    search_fields = ("title", "description")
    tag_fields = {
        "status": TagStyle(
            colors={
                "planned": GREY,
                "on_track": BLUE,
                "at_risk": RED,
                "achieved": GREEN,
                "abandoned": GREY,
            }
        )
    }
    fieldsets = (
        (None, {"fields": ("title", ("owner", "status"), "description")}),
        (
            _("Target"),
            {"fields": (("target", "unit", "direction"), "method", "due_on")},
        ),
    )
    inlines = (MeasurementInline,)
    detail_stats = ("target_label", "latest_value", "met")
    related_tables = (RelatedTable("measurements", icon="monitoring"),)
    detail_charts = ("measurements.trend",)
    charts = (
        Chart(
            "by_status", title=_("By status"), type="donut", group_by="status"
        ),
    )
    list_charts = ("by_status",)

    def get_list_queryset(self, request: Any) -> Any:
        latest = Measurement.objects.filter(objective=OuterRef("pk")).order_by(
            "-measured_on", "-pk"
        )
        return (
            super()
            .get_list_queryset(request)
            .annotate(latest_reading=Subquery(latest.values("value")[:1]))
        )

    @display(description=_("Target"))
    def target_label(self, objective: Objective) -> str:
        if objective.target is None:
            return ""
        return f"{objective.target} {objective.unit}".strip()

    @display(description=_("Latest value"), ordering="latest_reading")
    def latest_value(self, objective: Objective) -> Any:
        if hasattr(objective, "latest_reading"):
            return objective.latest_reading
        reading = objective.latest
        return reading.value if reading else None

    @display(description=_("Met"), boolean=True)
    def met(self, objective: Objective) -> bool | None:
        return objective.is_met(self.latest_value(objective))


@register(Acknowledgement)
class AcknowledgementResource(ModelResource):
    """Read only: an acknowledgement is given by the person, through the
    policy's *Acknowledge* action, never typed in on their behalf."""

    icon = "task_alt"
    group = GROUP_ISMS
    show_in_navigation = False
    list_display = ("policy", "version", "user", "acknowledged_at")
    search_fields = ("policy__code", "policy__title", "user__username")
    ordering = ("-acknowledged_at",)
    actions = ()
    undo = False

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@register(Policy)
class PolicyResource(ModelResource):
    icon = "policy"
    group = GROUP_ISMS
    order = 4
    custom_fields = True
    description = _(
        "Policies, their approval and review, and who read them (A.5.1)."
    )
    list_display = (
        "code",
        "title",
        "version",
        "status",
        "owner",
        "next_review_on",
        "acknowledged",
        "review_due",
    )
    search_fields = ("code", "title", "summary")
    tag_fields = {
        "status": TagStyle(
            colors={"draft": AMBER, "approved": GREEN, "retired": GREY}
        )
    }
    presets = {
        _("Review due"): {
            "filters": {"match": "all", "conditions": [REVIEW_DUE]},
            "order": [["next_review_on", "asc"]],
        },
    }
    fieldsets = (
        (None, {"fields": (("code", "title"), ("version", "status"))}),
        (None, {"fields": ("summary", ("document", "url"))}),
        (
            _("Approval and review"),
            {
                "fields": (
                    "owner",
                    ("approved_by", "approved_on"),
                    ("next_review_on", "requires_acknowledgement"),
                )
            },
        ),
    )
    detail_stats = ("acknowledged", "coverage")
    related_tables = (RelatedTable("acknowledgements", icon="task_alt"),)
    actions = ("acknowledge", "mark_reviewed", "delete_selected")

    def get_list_queryset(self, request: Any) -> Any:
        current = Acknowledgement.objects.filter(
            policy=OuterRef("pk"), version=OuterRef("version")
        )
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                acknowledged_count=Coalesce(
                    Subquery(
                        current.order_by()
                        .values("policy")
                        .annotate(total=Count("pk"))
                        .values("total")[:1]
                    ),
                    0,
                )
            )
        )

    @display(description=_("Acknowledged"), ordering="acknowledged_count")
    def acknowledged(self, policy: Policy) -> int:
        count = getattr(policy, "acknowledged_count", None)
        if count is None:
            count = policy.acknowledgements.filter(
                version=policy.version
            ).count()
        return count or 0

    @display(description=_("Coverage"))
    def coverage(self, policy: Policy) -> str:
        """The share of active accounts that acknowledged this version."""
        users = get_user_model().objects.filter(is_active=True).count()
        if not users:
            return ""
        return f"{round(100 * self.acknowledged(policy) / users)} %"

    @display(description=_("Review due"), boolean=True)
    def review_due(self, policy: Policy) -> bool:
        return bool(
            policy.next_review_on
            and policy.next_review_on < timezone.localdate()
        )

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        if name == "acknowledge":
            return (
                obj.status == Policy.Status.APPROVED
                and not obj.acknowledgements.filter(
                    user=request.user, version=obj.version
                ).exists()
            )
        return True

    @action(
        description=_("Acknowledge"),
        icon="task_alt",
        permissions=("view",),
        confirm=_("Confirm you read and accept the selected policies?"),
        help=_(
            "Records that you read the current version of the policy and "
            "accept it, with today's date."
        ),
    )
    def acknowledge(self, request: Any, queryset: Any) -> str:
        count = 0
        for policy in queryset.filter(status=Policy.Status.APPROVED):
            _ack, created = Acknowledgement.objects.get_or_create(
                policy=policy, version=policy.version, user=request.user
            )
            count += created
        return ngettext(
            "%(count)s policy acknowledged.",
            "%(count)s policies acknowledged.",
            count,
        ) % {"count": count}

    @action(
        description=_("Mark reviewed"),
        icon="event_repeat",
        permissions=("change",),
        confirm=_("Mark the selected policies reviewed today?"),
        help=_("Records today's review and sets the next one a year away."),
    )
    def mark_reviewed(self, request: Any, queryset: Any) -> str:
        today = timezone.localdate()
        count = 0
        for policy in queryset:
            policy.next_review_on = next_year(today)
            policy.save(update_fields=["next_review_on"])
            count += 1
        return ngettext(
            "%(count)s policy reviewed.",
            "%(count)s policies reviewed.",
            count,
        ) % {"count": count}


@register(Contact)
class ContactResource(ModelResource):
    icon = "contact_phone"
    group = GROUP_ISMS
    order = 5
    description = _("Authorities, CERTs and groups to call (A.5.5, A.5.6).")
    list_display = ("name", "kind", "phone", "email", "purpose")
    search_fields = ("name", "purpose", "email")
    # An authority's number is often a person's own line.
    personal_data = PersonalData(
        fields={"phone": "blank", "email": "blank"},
        email=("email",),
        action=False,
    )
    fieldsets = (
        (None, {"fields": (("name", "kind"), "purpose")}),
        (None, {"fields": (("phone", "email"), "url", "notes")}),
    )


class ReviewActionInline(TabularInline):
    model = ReviewAction
    fields = ("title", "owner", "due_on", "status")
    extra = 1
    classes = ("tab",)
    verbose_name_plural = _("Actions")


@register(ReviewAction)
class ReviewActionResource(ModelResource):
    icon = "checklist"
    group = GROUP_ISMS
    order = 7
    description = _("What management reviews decided, until done (9.3).")
    list_display = ("title", "review", "owner", "due_on", "status", "done_on")
    search_fields = ("title", "review__title")
    tag_fields = {
        "status": TagStyle(
            colors={"open": BLUE, "done": GREEN, "cancelled": GREY}
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
                        "value": ["open"],
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


@register(ManagementReview)
class ManagementReviewResource(ModelResource):
    icon = "groups"
    group = GROUP_ISMS
    order = 6
    description = _("Management reviews, their inputs and decisions (9.3).")
    list_display = ("title", "held_on", "status", "chair", "open_actions")
    search_fields = ("title", "inputs", "decisions")
    tag_fields = {"status": TagStyle(colors={"planned": BLUE, "held": GREEN})}
    fieldsets = (
        (None, {"fields": ("title", ("held_on", "status"), "chair")}),
        (None, {"fields": ("attendees",)}),
        (
            _("Minutes"),
            {"fields": ("inputs", "decisions"), "classes": ("tab",)},
        ),
    )
    inlines = (ReviewActionInline,)
    detail_stats = ("open_actions",)
    related_tables = (RelatedTable("actions", icon="checklist"),)

    def get_list_queryset(self, request: Any) -> Any:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                open_count=Count(
                    "actions", filter=Q(actions__status="open"), distinct=True
                )
            )
        )

    @display(description=_("Open actions"), ordering="open_count")
    def open_actions(self, review: ManagementReview) -> int:
        count = getattr(review, "open_count", None)
        if count is None:
            count = review.actions.filter(status="open").count()
        return count

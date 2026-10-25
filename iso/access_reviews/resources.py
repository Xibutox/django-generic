"""Access review campaigns and their decisions.

*Collect the accounts* fills a review from the accounts in its scope;
the reviewed accounts are then decided in their table - *Keep*,
*Revoke*, or edited in place - and *Apply the decisions* deactivates
the revoked accounts. Each decision keeps who took it and when.
Nobody reviews or revokes their own account, and only a superuser
deactivates a superuser.
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
    TagStyle,
    action,
    display,
    register,
)
from iso.access_reviews.models import AccessReview, AccessReviewItem
from iso.common import AMBER, BLUE, GREEN, GREY, GROUP_STAFF, RED

DECISION_COLORS = {
    "pending": GREY,
    "keep": GREEN,
    "revoke": RED,
    "modify": AMBER,
}


@register(AccessReview)
class AccessReviewResource(ModelResource):
    icon = "manage_accounts"
    group = GROUP_STAFF
    order = 3
    description = _(
        "Periodic reviews of who can do what, account by account "
        "(A.5.18, A.8.2)."
    )
    list_display = (
        "title",
        "scope",
        "reviewer",
        "due_on",
        "status",
        "account_count",
        "pending_count",
    )
    search_fields = ("title",)
    tag_fields = {
        "status": TagStyle(
            colors={"draft": GREY, "in_progress": BLUE, "completed": GREEN}
        )
    }
    fieldsets = (
        (None, {"fields": ("title", ("scope", "group"))}),
        (None, {"fields": (("reviewer", "due_on"), "status", "conclusion")}),
    )
    detail_stats = ("account_count", "pending_count", "revoked_count")
    related_tables = (RelatedTable("items", icon="person_search"),)
    actions = ("collect", "complete")

    def get_list_queryset(self, request: Any) -> Any:
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                items_count=Count("items", distinct=True),
                pending_items=Count(
                    "items", filter=Q(items__decision="pending"), distinct=True
                ),
            )
        )

    @display(description=_("Accounts"), ordering="items_count")
    def account_count(self, review: AccessReview) -> int:
        count = getattr(review, "items_count", None)
        return review.items.count() if count is None else count

    @display(description=_("To decide"), ordering="pending_items")
    def pending_count(self, review: AccessReview) -> int:
        count = getattr(review, "pending_items", None)
        if count is None:
            count = review.items.filter(decision="pending").count()
        return count

    @display(description=_("Revoked"))
    def revoked_count(self, review: AccessReview) -> int:
        return review.items.filter(decision="revoke").count()

    def has_record_action(self, request: Any, obj: Any, name: str) -> bool:
        return obj.status != AccessReview.Status.COMPLETED

    @action(
        description=_("Collect the accounts"),
        icon="group_add",
        permissions=("change",),
        help=_(
            "Lists every account in the review's scope as it is now - "
            "groups, permissions, last sign-in - to decide one by one."
        ),
    )
    def collect(self, request: Any, queryset: Any) -> str:
        added = 0
        for review in queryset.exclude(status=AccessReview.Status.COMPLETED):
            added += review.collect()
        return ngettext(
            "%(count)s account collected.",
            "%(count)s accounts collected.",
            added,
        ) % {"count": added}

    @action(
        description=_("Complete"),
        icon="task_alt",
        permissions=("change",),
        confirm=_("Complete the selected reviews?"),
        help=_("Closes the campaign once every account is decided."),
    )
    def complete(self, request: Any, queryset: Any) -> dict:
        done = 0
        left = 0
        for review in queryset.exclude(status=AccessReview.Status.COMPLETED):
            if review.items.filter(decision="pending").exists():
                left += 1
                continue
            review.status = AccessReview.Status.COMPLETED
            review.completed_on = timezone.localdate()
            review.save(update_fields=["status", "completed_on"])
            done += 1
        message = ngettext(
            "%(count)s review completed.", "%(count)s reviews completed.", done
        ) % {"count": done}
        if left:
            message += " " + gettext(
                "A review with accounts still to decide stays open."
            )
            return {"message": message, "level": "warning"}
        return {"message": message, "level": "success"}


@register(AccessReviewItem)
class AccessReviewItemResource(ModelResource):
    icon = "person_search"
    group = GROUP_STAFF
    show_in_navigation = False
    list_display = (
        "account_label",
        "review",
        "privileged",
        "groups",
        "permission_count",
        "last_login",
        "decision",
        "comment",
        "decided_by",
        "applied_at",
    )
    search_fields = ("account_label", "groups", "comment")
    tag_fields = {"decision": TagStyle(colors=DECISION_COLORS)}
    editable_fields = ("decision", "comment")
    list_editable = "toggle"
    presets = {
        _("To decide"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "decision",
                        "operator": "any_of",
                        "value": ["pending"],
                    }
                ],
            },
        },
    }
    fields = ("decision", "comment")
    charts = (
        Chart(
            "decisions",
            title=_("Decisions"),
            type="donut",
            group_by="decision",
            colors=DECISION_COLORS,
        ),
    )
    actions = ("keep", "revoke", "apply")
    undo = False

    def has_add_permission(self, request: Any) -> bool:
        # Items come from *Collect the accounts*, as the accounts were.
        return False

    def get_queryset(self, request: Any) -> Any:
        return super().get_queryset(request).select_related("review")

    @display(description=_("Privileged"), boolean=True)
    def privileged(self, item: AccessReviewItem) -> bool:
        return item.privileged

    def can_edit_column(
        self, request: Any, column: str, obj: Any = None
    ) -> bool:
        return obj is None or self.may_decide(request, obj)

    def may_decide(self, request: Any, item: AccessReviewItem) -> bool:
        return (
            item.account_id != request.user.pk
            and item.applied_at is None
            and item.review.status != AccessReview.Status.COMPLETED
        )

    def stamp(self, request: Any, item: AccessReviewItem) -> None:
        item.decided_by = request.user
        item.decided_at = timezone.now()

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        item = serializer.instance
        if item is not None and not self.may_decide(request, item):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                gettext("This account cannot be decided by you, or any more.")
            )
        return serializer.save(
            decided_by=request.user, decided_at=timezone.now()
        )

    def save_editable(self, request: Any, obj: Any, changes: Any) -> None:
        super().save_editable(request, obj, changes)
        obj.refresh_from_db()
        self.stamp(request, obj)
        obj.save(update_fields=["decided_by", "decided_at"])

    def decide(self, request: Any, queryset: Any, decision: str) -> dict:
        count = 0
        skipped = 0
        for item in queryset.select_related("review"):
            if not self.may_decide(request, item):
                skipped += 1
                continue
            item.decision = decision
            self.stamp(request, item)
            item.save(update_fields=["decision", "decided_by", "decided_at"])
            count += 1
        message = ngettext(
            "%(count)s account decided.", "%(count)s accounts decided.", count
        ) % {"count": count}
        if skipped:
            message += " " + gettext(
                "Your own account, and accounts already applied, are left "
                "to someone else."
            )
            return {"message": message, "level": "warning"}
        return {"message": message, "level": "success"}

    @action(
        description=_("Keep"),
        icon="check_circle",
        permissions=("change",),
        help=_("The account keeps its access."),
    )
    def keep(self, request: Any, queryset: Any) -> dict:
        return self.decide(request, queryset, AccessReviewItem.Decision.KEEP)

    @action(
        description=_("Revoke"),
        icon="block",
        permissions=("change",),
        help=_("The account is to lose its access when decisions apply."),
    )
    def revoke(self, request: Any, queryset: Any) -> dict:
        return self.decide(request, queryset, AccessReviewItem.Decision.REVOKE)

    @action(
        description=_("Apply the decisions"),
        icon="gavel",
        permissions=("change", "auth.change_user"),
        variant="danger",
        confirm=_("Deactivate the accounts decided as revoked?"),
        help=_(
            "Deactivates every account decided as revoked. Their history "
            "stays; they can no longer sign in."
        ),
    )
    def apply(self, request: Any, queryset: Any) -> dict:
        count = 0
        refused = 0
        now = timezone.now()
        items = queryset.filter(
            decision=AccessReviewItem.Decision.REVOKE, applied_at=None
        ).select_related("account")
        for item in items:
            account = item.account
            protected = account is not None and (
                account.pk == request.user.pk
                or (account.is_superuser and not request.user.is_superuser)
            )
            if protected:
                refused += 1
                continue
            if account is not None and account.is_active:
                account.is_active = False
                account.save(update_fields=["is_active"])
            item.applied_at = now
            item.save(update_fields=["applied_at"])
            count += 1
        message = ngettext(
            "%(count)s account deactivated.",
            "%(count)s accounts deactivated.",
            count,
        ) % {"count": count}
        if refused:
            message += " " + gettext(
                "Your own account and superusers (unless you are one) are "
                "left as they are."
            )
            return {"message": message, "level": "warning"}
        return {"message": message, "level": "success"}

"""The Mailings screens: a user's own, or everyone's for whoever may.

Created from a list page - its saved-views menu opens the add form
with the table and its layout filled in - and managed here: the
schedule, the recipients, paused or not, sent now.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from generic.conf import generic_settings
from generic.mailings.models import ScheduledMailing
from generic.sites import ModelResource, action, display, site

ADD = "generic.add_scheduledmailing"
VIEW_ALL = "generic.view_scheduledmailing"
CHANGE_ALL = "generic.change_scheduledmailing"
DELETE_ALL = "generic.delete_scheduledmailing"


class ScheduledMailingResource(ModelResource):
    icon = "forward_to_inbox"
    group = _("Tasks")
    order = 5
    description = _(
        "Lists sent by e-mail on a schedule, each reader receiving the "
        "rows they may see."
    )

    list_display = (
        "name",
        "list_name",
        "frequency",
        "next_run_at",
        "last_sent_at",
        "owner",
        "is_active",
    )
    search_fields = ("name", "table")
    ordering = ("name",)
    fieldsets = (
        (None, {"fields": ("name", ("format", "is_active"))}),
        (
            _("When"),
            {
                "fields": (
                    ("frequency", "time"),
                    ("weekday", "day_of_month"),
                )
            },
        ),
        (
            _("To whom"),
            {
                "fields": (
                    "include_owner",
                    "users",
                    "groups",
                    "send_when_empty",
                ),
            },
        ),
        (
            _("What"),
            {
                "fields": ("table", "state"),
                "description": _(
                    "The list and its layout, as they were when the "
                    "mailing was made."
                ),
                "classes": ("collapse",),
            },
        ),
    )
    detail_fieldsets = (
        (
            None,
            {
                "fields": (
                    "list_name",
                    "frequency",
                    "format",
                    "owner",
                    "is_active",
                )
            },
        ),
        (
            _("Sending"),
            {"fields": ("next_run_at", "last_sent_at", "last_error")},
        ),
    )
    detail_stats = ("next_run_at", "last_sent_at")
    form_overrides = {"state": {"widget": "json", "rows": 6}}
    tag_fields: dict[str, Any] = {}
    actions = ("send_now", "pause", "resume", "delete_selected")
    # A schedule's own bookkeeping is nobody's news or history.
    watchable = False
    history_exclude = ("next_run_at", "last_sent_at", "last_error")
    mailing = False

    # -- who sees what ------------------------------------------------------

    def get_queryset(self, request: Any) -> QuerySet:
        queryset = super().get_queryset(request).select_related("owner")

        if request.user.has_perm(VIEW_ALL):
            return queryset

        return queryset.filter(owner=request.user)

    def has_view_permission(self, request: Any, obj: Any = None) -> bool:
        user = request.user

        if user.has_perm(VIEW_ALL) or user.has_perm(CHANGE_ALL):
            return True

        return user.has_perm(ADD) and (obj is None or obj.owner_id == user.pk)

    def has_module_permission(self, request: Any) -> bool:
        return self.has_view_permission(request)

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        user = request.user

        if user.has_perm(CHANGE_ALL):
            return True

        return user.has_perm(ADD) and (obj is None or obj.owner_id == user.pk)

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        user = request.user

        if user.has_perm(DELETE_ALL):
            return True

        return user.has_perm(ADD) and (obj is None or obj.owner_id == user.pk)

    # -- columns ------------------------------------------------------------

    @display(description=_("List"))
    def list_name(self, mailing: ScheduledMailing) -> str:
        from generic.mailings.sending import resource_for

        resource = resource_for(mailing.table)

        return str(resource.get_label_plural()) if resource else mailing.table

    # -- writing ------------------------------------------------------------

    def save_model(self, request: Any, serializer: Any, change: bool) -> Any:
        from generic.mailings.schedule import next_run
        from generic.mailings.sending import MailingProblem, check

        data = serializer.validated_data
        owner = serializer.instance.owner if change else request.user
        probe = ScheduledMailing(
            table=data.get("table", getattr(serializer.instance, "table", "")),
            state=data.get("state", getattr(serializer.instance, "state", {})),
        )

        # Checked as the owner: a mailing sends what its owner may see
        # at least to them, and a list they cannot read is refused here.
        try:
            check(probe, owner)
        except MailingProblem as problem:
            raise ValidationError({"table": [str(problem)]})

        day = data.get("day_of_month")

        if day is not None and not 1 <= int(day) <= 28:
            raise ValidationError(
                {"day_of_month": [gettext("Choose a day from 1 to 28.")]}
            )

        mailing = serializer.save(**({} if change else {"owner": owner}))
        mailing.next_run_at = next_run(mailing)
        mailing.save(update_fields=["next_run_at"])

        return mailing

    # -- actions ------------------------------------------------------------

    @action(description=_("Send now"), icon="send", permissions=("add",))
    def send_now(self, request: Any, queryset: QuerySet) -> str:
        from generic.mailings.sending import send

        outcomes = [send(mailing) for mailing in queryset]

        return gettext("%(count)s sent.") % {
            "count": sum(outcome.sent for outcome in outcomes)
        }

    @action(description=_("Pause"), icon="pause", permissions=("add",))
    def pause(self, request: Any, queryset: QuerySet) -> str:
        count = 0

        for mailing in queryset:
            if self.has_change_permission(request, mailing):
                mailing.is_active = False
                mailing.save(update_fields=["is_active"])
                count += 1

        return gettext("%(count)s paused.") % {"count": count}

    @action(description=_("Resume"), icon="play_arrow", permissions=("add",))
    def resume(self, request: Any, queryset: QuerySet) -> str:
        from generic.mailings.schedule import next_run

        count = 0

        for mailing in queryset:
            if self.has_change_permission(request, mailing):
                mailing.is_active = True
                mailing.last_error = ""
                mailing.next_run_at = next_run(mailing)
                mailing.save(
                    update_fields=["is_active", "last_error", "next_run_at"]
                )
                count += 1

        return gettext("%(count)s resumed.") % {"count": count}


def mailings_offered() -> bool:
    return bool(generic_settings.SHOW_MAILINGS)


def register_screens() -> None:
    """The Mailings screen, unless the project said ``SHOW_MAILINGS``
    False or registered the model itself."""
    if not mailings_offered():
        return

    if not site.is_registered(ScheduledMailing):
        site.register(ScheduledMailing, ScheduledMailingResource)

"""Courses, training records and personnel files.

The training records' list says who is up to date and whose training
has expired; a course's page lists who followed it. A personnel file
shows what is still missing - a screening, a signature, on departure
the access removal and the assets' return - and, with ``iso.assets``
installed, the assets the person still holds.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.utils import timezone
from django.utils.translation import gettext
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
    GROUP_STAFF,
    PURPLE,
    RED,
    is_installed,
)
from iso.people.models import Course, PersonnelFile, TrainingRecord


@register(Course)
class CourseResource(ModelResource):
    icon = "school"
    group = GROUP_STAFF
    order = 0
    description = _("Awareness and training courses (7.2, 7.3, A.6.3).")
    list_display = (
        "title",
        "topic",
        "mandatory",
        "validity_months",
        "audience",
    )
    search_fields = ("title", "description")
    related_tables = (RelatedTable("records", icon="workspace_premium"),)


@register(TrainingRecord)
class TrainingRecordResource(ModelResource):
    icon = "workspace_premium"
    group = GROUP_STAFF
    order = 1
    description = _("Who followed which course, until when (7.2, A.6.3).")
    list_display = (
        "person",
        "course",
        "completed_on",
        "expires_on",
        "state",
        "score",
    )
    search_fields = ("person__username", "course__title")
    presets = {
        _("Expired"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "expires_on",
                        "operator": "older_than_days",
                        "value": 1,
                    }
                ],
            },
        },
        _("Expiring within 30 days"): {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "expires_on",
                        "operator": "next_days",
                        "value": 30,
                    }
                ],
            },
        },
    }
    charts = (
        Chart(
            "by_month",
            title=_("Completed"),
            type="bar",
            group_by="completed_on",
            split_by="course",
            stacked=True,
            period="month",
            periods=("month", "quarter", "year"),
        ),
    )
    list_charts = ("by_month",)

    @display(description=_("State"), tags=True)
    def state(self, record: TrainingRecord) -> list[dict[str, Any]]:
        if record.expires_on is None:
            return [{"label": gettext("Valid"), "color": GREEN}]
        days = (record.expires_on - timezone.localdate()).days
        if days < 0:
            return [{"label": gettext("Expired"), "color": RED}]
        if days <= 30:
            return [{"label": gettext("Expiring"), "color": AMBER}]
        return [{"label": gettext("Valid"), "color": GREEN}]


@register(PersonnelFile)
class PersonnelFileResource(ModelResource):
    icon = "badge"
    group = GROUP_STAFF
    order = 2
    custom_fields = True
    description = _(
        "Screening, signatures and departure of each person "
        "(A.6.1, A.6.2, A.6.5, A.6.6)."
    )
    list_display = (
        "full_name",
        "user",
        "job_title",
        "employment",
        "status",
        "starts_on",
        "ends_on",
        "to_do",
    )
    search_fields = ("full_name", "job_title", "department")
    tag_fields = {
        "status": TagStyle(
            colors={
                "joining": PURPLE,
                "active": BLUE,
                "leaving": AMBER,
                "left": GREY,
            }
        )
    }
    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("full_name", "user"),
                    ("job_title", "department"),
                    ("employment", "status"),
                    ("starts_on", "ends_on"),
                )
            },
        ),
        (
            _("Joining"),
            {"fields": ("screened_on", "terms_signed_on", "nda_signed_on")},
        ),
        (
            _("Leaving"),
            {
                "fields": (
                    "access_revoked_on",
                    "assets_returned_on",
                    "exit_reminder_on",
                )
            },
        ),
        (None, {"fields": ("notes",)}),
    )
    detail_stats = ("to_do",)
    # The person's training and, where the inventory is installed, the
    # assets they were given: both reached through their account.
    related_tables = (
        RelatedTable(
            "training",
            model=TrainingRecord,
            lookup="person__personnel_file",
            title=_("Training"),
            icon="workspace_premium",
        ),
    ) + (
        (
            RelatedTable(
                "assets_held",
                model=apps.get_model("assets", "Assignment"),
                lookup="holder__personnel_file",
                title=_("Assets"),
                icon="inventory_2",
            ),
        )
        if is_installed("iso.assets")
        else ()
    )

    @display(description=_("Still to do"))
    def to_do(self, person: PersonnelFile) -> str:
        return ", ".join(person.missing_steps)

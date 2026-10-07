"""Product management, declared by hand: a list of products, each with
its milestones - the dated steps it goes through - and its documents.

``library/resources.py`` lets ``auto`` work a model's screens out; here
a ``ModelResource`` says them, for the few columns ``auto`` cannot
guess: each product's next step, its progress, whether it is late.
"""

from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.utils import formats, timezone

from generic.sites import (
    Chart,
    ModelResource,
    RelatedTable,
    TabularInline,
    TagStyle,
    display,
    register,
    site,
)
from products.models import Document, Milestone, Product

STATUS_COLORS = {
    "planned": "#64748b",
    "development": "#2563eb",
    "launched": "#16a34a",
    "retired": "#991b1b",
}
STATES = {
    "done": ("Done", "#16a34a"),
    "late": ("Late", "#dc2626"),
    "upcoming": ("Upcoming", "#2563eb"),
}


def late_milestones():
    """The steps not done whose date has passed, today's date."""
    return Milestone.objects.filter(
        done_on__isnull=True, due_on__lt=timezone.localdate()
    )


class MilestoneInline(TabularInline):
    """The steps, edited with the product, on a tab of its form."""

    model = Milestone
    fields = ("step", "due_on", "done_on", "notes")
    extra = 1
    classes = ("tab",)


@register(Product)
class ProductResource(ModelResource):
    icon = "inventory_2"
    group = "Products"
    order = 0
    description = "Every product, the steps it goes through, its files."

    list_display = (
        "reference",
        "name",
        "status",
        "owner",
        "next_step",
        "next_due_on",
        "progress",
        "late",
        "document_count",
    )
    search_fields = ("reference", "name", "owner", "description")
    tag_fields = {"status": TagStyle(colors=STATUS_COLORS)}
    presets = {
        "Late": {
            "filters": {
                "match": "all",
                "conditions": [{"column": "late", "operator": "is_true"}],
            },
            "order": [["next_due_on", "asc"]],
        },
        "In development": {
            "filters": {
                "match": "all",
                "conditions": [
                    {
                        "column": "status",
                        "operator": "any_of",
                        "value": ["development"],
                    }
                ],
            },
            "order": [["next_due_on", "asc"]],
        },
    }

    fieldsets = (
        (None, {"fields": (("reference", "name"), ("owner", "status"))}),
        (None, {"fields": ("description",)}),
    )
    inlines = (MilestoneInline,)

    detail_stats = ("progress", "next_step", "next_due_on")
    detail_fieldsets = (
        (None, {"fields": ("reference", "name", "owner", "status")}),
        (None, {"fields": ("description",)}),
    )
    # Documents are a table, not a tab of the form: a file is sent from
    # its own form, with the product filled in by the table's *Add*.
    related_tables = (
        RelatedTable("milestones", icon="flag"),
        RelatedTable("documents", icon="description"),
    )
    # The milestones' timeline, between the figures and the tabs: a
    # chart of the related resource, narrowed to this product.
    detail_charts = ("milestones.timeline",)

    def get_list_queryset(self, request):
        upcoming = Milestone.objects.filter(
            product=OuterRef("pk"), done_on__isnull=True
        ).order_by("due_on", "pk")

        return (
            super()
            .get_list_queryset(request)
            .annotate(
                next_step_name=Subquery(upcoming.values("step")[:1]),
                next_due=Subquery(upcoming.values("due_on")[:1]),
                steps=Count("milestones", distinct=True),
                steps_done=Count(
                    "milestones",
                    distinct=True,
                    filter=Q(milestones__done_on__isnull=False),
                ),
                is_late=Exists(
                    late_milestones().filter(product=OuterRef("pk"))
                ),
                documents_count=Count("documents", distinct=True),
            )
        )

    def next_milestone(self, product):
        return product.milestones.filter(done_on__isnull=True).first()

    @display(description="Next step", ordering="next_step_name")
    def next_step(self, product):
        if hasattr(product, "next_step_name"):
            return product.next_step_name or "-"
        milestone = self.next_milestone(product)
        return milestone.step if milestone else "-"

    @display(
        description="Next date",
        ordering="next_due",
        filter_field="next_due",
        filter_type="date",
    )
    def next_due_on(self, product):
        if hasattr(product, "next_due"):
            return product.next_due
        milestone = self.next_milestone(product)
        return milestone.due_on if milestone else None

    @display(description="Progress", ordering="steps_done")
    def progress(self, product):
        if hasattr(product, "steps"):
            done, total = product.steps_done, product.steps
        else:
            total = product.milestones.count()
            done = product.milestones.filter(done_on__isnull=False).count()
        return f"{done} / {total}"

    @display(
        description="Late",
        boolean=True,
        ordering="is_late",
        filter_field="is_late",
        filter_type="boolean",
    )
    def late(self, product):
        return bool(getattr(product, "is_late", False))

    @display(
        description="Documents",
        ordering="documents_count",
        filter_field="documents_count",
        filter_type="integer",
    )
    def document_count(self, product):
        return getattr(product, "documents_count", 0)


def milestone_timeline(chart, request, queryset, period):
    """The steps over time: how many were due, and how many done, by
    each milestone's date - and a dashed line where today falls.

    Computed (``Chart(data=...)``): the categories are the milestones'
    own dates and today, in order, rather than buckets of a period.
    """
    today = timezone.localdate()
    milestones = list(queryset.order_by("due_on", "pk"))
    days = sorted(
        {m.due_on for m in milestones}
        | {m.done_on for m in milestones if m.done_on}
        | {today}
    )

    def steps_by(day, field):
        return sum(
            1
            for m in milestones
            if getattr(m, field) and getattr(m, field) <= day
        )

    def label(day):
        return formats.date_format(day, "SHORT_DATE_FORMAT")

    categories = [label(day) for day in days]
    planned = [steps_by(day, "due_on") for day in days]
    # Nothing is known after today: the line stops there.
    done = [steps_by(day, "done_on") if day <= today else None for day in days]

    def line(name, color, data):
        return {
            "name": name,
            "type": "line",
            "data": data,
            "symbol": "circle",
            "symbolSize": 7,
            "itemStyle": {"color": color},
            "lineStyle": {"width": 2, "color": color},
        }

    # ``options`` is merged over what the series make; a list replaces
    # the series whole, so the lines are spelled out with the marker
    # ECharts draws for today - a vertical dashed line.
    marked = line("Planned", "#2563eb", planned)
    marked["markLine"] = {
        "silent": True,
        "symbol": "none",
        "data": [{"xAxis": label(today)}],
        "lineStyle": {"color": "#dc2626", "type": "dashed", "width": 2},
        "label": {"formatter": "Today", "color": "#dc2626"},
    }

    return {
        "categories": categories,
        "series": [
            {"name": "Planned", "color": "#2563eb", "data": planned},
            {"name": "Done", "color": "#16a34a", "data": done},
        ],
        "value": {"label": "Steps", "format": "integer"},
        "options": {
            "series": [marked, line("Done", "#16a34a", done)],
        },
    }


@register(Milestone)
class MilestoneResource(ModelResource):
    """Every product's steps in one list: what is due, what is late."""

    icon = "flag"
    group = "Products"
    order = 1
    description = "The dated steps of every product."

    list_display = ("due_on", "product", "step", "done_on", "state", "late")
    charts = (
        Chart(
            "timeline",
            title="Timeline",
            description="Steps due and done, by date; the dashed line is "
            "today.",
            icon="timeline",
            type="line",
            data=milestone_timeline,
        ),
    )
    list_display_hidden = ("late",)
    search_fields = ("step", "notes", "product__reference", "product__name")
    # The furthest first: what is coming, then what is late, then done.
    ordering = ("-due_on", "-pk")
    fields = ("product", ("step", "due_on"), ("done_on", "notes"))
    presets = {
        "Late": {
            "columns": ["due_on", "product", "step", "state"],
            "filters": {
                "match": "all",
                "conditions": [{"column": "late", "operator": "is_true"}],
            },
            "order": [["due_on", "asc"]],
        },
        "Next 30 days": {
            "columns": ["due_on", "product", "step", "state"],
            "filters": {
                "match": "all",
                "conditions": [
                    {"column": "due_on", "operator": "next_days", "value": 30},
                    {"column": "done_on", "operator": "empty"},
                ],
            },
            "order": [["due_on", "asc"]],
        },
    }

    def get_list_queryset(self, request):
        return (
            super()
            .get_list_queryset(request)
            .annotate(
                is_late=Exists(late_milestones().filter(pk=OuterRef("pk")))
            )
        )

    @display(description="State", tags=True, ordering="done_on")
    def state(self, milestone):
        label, color = STATES[milestone.state]
        return [{"label": label, "color": color}]

    @display(
        description="Late",
        boolean=True,
        ordering="is_late",
        filter_field="is_late",
        filter_type="boolean",
    )
    def late(self, milestone):
        return bool(getattr(milestone, "is_late", milestone.state == "late"))


@register(Document)
class DocumentResource(ModelResource):
    icon = "description"
    group = "Products"
    order = 2
    description = "The files attached to the products."

    list_display = ("title", "kind", "product", "file", "added_at")
    search_fields = ("title", "product__reference", "product__name")
    tag_fields = {"kind": TagStyle()}
    fields = ("product", ("title", "kind"), "file")
    readonly_fields = ("added_at",)
    detail_fieldsets = (
        (None, {"fields": ("product", "title", "kind", "file", "added_at")}),
    )


def late_milestone_count(request):
    return late_milestones().count()


# The dashboard's cards: what to look at first.
site.add_shortcut(
    "Late milestones",
    url=(
        "/products/milestone/?filters="
        '{"match":"all","conditions":[{"column":"late",'
        '"operator":"is_true"}]}'
    ),
    icon="running_with_errors",
    description="Steps whose date has passed, not done yet.",
    count=late_milestone_count,
    permission="products.view_milestone",
    order=0,
)
site.add_shortcut(
    "Due in 30 days",
    url=(
        "/products/milestone/?filters="
        '{"match":"all","conditions":[{"column":"due_on",'
        '"operator":"next_days","value":30},'
        '{"column":"done_on","operator":"empty"}]}'
    ),
    icon="event_upcoming",
    description="The steps coming up next.",
    permission="products.view_milestone",
    order=1,
)

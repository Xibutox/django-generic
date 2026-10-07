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
    """The product's milestones on one horizontal line, each at its date
    and coloured by its state, and a dashed line where today falls.

    Computed (``Chart(data=...)``). The figures - what the card's table
    button shows - are each step's days from today; ``options``, merged
    over what they make, draws them on a time axis with no y axis.
    """
    today = timezone.localdate()
    milestones = list(queryset.order_by("due_on", "pk"))

    def point(index, milestone):
        label, color = STATES[milestone.state]
        day = formats.date_format(milestone.due_on, "SHORT_DATE_FORMAT")
        return {
            "name": f"{milestone.step} - {day} ({label.lower()})",
            "value": [milestone.due_on.isoformat(), 0],
            "itemStyle": {"color": color},
            # Above and below in turn, so close steps keep their names.
            "label": {
                "formatter": milestone.step,
                "position": "top" if index % 2 == 0 else "bottom",
            },
        }

    dates = [m.due_on for m in milestones] + [today]
    line = [[min(dates).isoformat(), 0], [max(dates).isoformat(), 0]]

    return {
        "categories": [m.step for m in milestones],
        "series": [
            {
                "name": "Days from today",
                "data": [(m.due_on - today).days for m in milestones],
            }
        ],
        "value": {"label": "Days from today", "format": "integer"},
        "options": {
            "grid": {"left": 40, "right": 40, "top": 28, "bottom": 4},
            "xAxis": {"type": "time", "data": None, "boundaryGap": False},
            "yAxis": {"show": False, "min": -1, "max": 1},
            "tooltip": {"trigger": "item", "formatter": "{b}"},
            "series": [
                {
                    "name": "Timeline",
                    "type": "line",
                    "data": line,
                    "symbol": "none",
                    "silent": True,
                    "lineStyle": {"width": 6, "color": "#cbd5e1"},
                    "markLine": {
                        "silent": True,
                        "symbol": "none",
                        "data": [{"xAxis": today.isoformat()}],
                        "lineStyle": {
                            "color": "#dc2626",
                            "type": "dashed",
                            "width": 2,
                        },
                        "label": {"formatter": "Today", "color": "#dc2626"},
                    },
                },
                {
                    "name": "Milestones",
                    "type": "scatter",
                    "symbolSize": 14,
                    "label": {"show": True, "fontSize": 11},
                    "data": [point(i, m) for i, m in enumerate(milestones)],
                },
            ],
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
            description="Each step at its date: green done, red late, "
            "blue upcoming. The dashed line is today.",
            icon="timeline",
            type="line",
            height="9rem",
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

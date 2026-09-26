"""The Django admin, kept alongside the generic views.

Not a fallback: the admin stays useful for staff and DBA work, while
the generic views serve the people using the application, with the
wording, permissions and workflow the project controls.
"""

from django.contrib import admin

from example.models import Agent, Tag, Team, Ticket, TicketComment


class TicketCommentInline(admin.TabularInline):
    model = TicketComment
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "team", "assignee", "status")
    list_filter = ("status", "priority", "team")
    search_fields = ("reference", "title")
    inlines = (TicketCommentInline,)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "team", "is_active")
    list_filter = ("team", "is_active")


admin.site.register(Tag)

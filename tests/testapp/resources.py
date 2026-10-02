"""The test app's own screens: a state machine, files and teams."""

from rest_framework import serializers

from generic.sites import ModelResource, TabularInline, register
from tests.testapp.models import (
    Binder,
    BinderSheet,
    Document,
    DocumentNote,
    Manuscript,
    SharedNote,
)


@register(Manuscript)
class ManuscriptResource(ModelResource):
    list_display = ("title", "state")
    search_fields = ("title",)
    fields = ("title", "summary", "verdict", "state")
    transitions = ("state",)


class DocumentNoteInline(TabularInline):
    model = DocumentNote
    fields = ("text",)


@register(Document)
class DocumentResource(ModelResource):
    """``file`` and ``scan`` are shown; ``archive`` is not."""

    list_display = ("title", "file")
    search_fields = ("title",)
    fields = ("title", "file", "scan", "authors", "details")
    detail_fieldsets = ((None, {"fields": ("title", "file", "scan")}),)
    inlines = (DocumentNoteInline,)

    def get_queryset(self, request):
        # A row restriction: "Restricted" documents are for superusers.
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        return queryset.exclude(title__startswith="Restricted")


@register(Binder)
class BinderResource(ModelResource):
    """Scoped to its team; asks a question the model does not keep."""

    list_display = ("title", "team", "attachment")
    search_fields = ("title",)
    team_field = "team"
    fields = ("title", "team", "attachment", "reason")
    form_extra_fields = {
        "reason": serializers.CharField(required=False, allow_blank=True)
    }

    def save_model(self, request, serializer, change):
        upload = serializer.validated_data.get("attachment")
        extra = {"note": serializer.extra_values.get("reason", "")}

        if upload:
            extra["attachment_name"] = upload.name

        return serializer.save(**extra)

    def get_download_name(self, request, obj, field):
        return obj.attachment_name


@register(BinderSheet)
class BinderSheetResource(ModelResource):
    list_display = ("title", "binder")
    search_fields = ("title",)
    team_field = "binder__team"


@register(SharedNote)
class SharedNoteResource(ModelResource):
    list_display = ("title", "teams")
    search_fields = ("title",)
    team_field = "teams"

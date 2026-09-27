"""The test app's own screens: a state machine, and files."""

from generic.sites import ModelResource, TabularInline, register
from tests.testapp.models import Document, DocumentNote, Manuscript


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

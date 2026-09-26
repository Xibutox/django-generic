"""The test app's own screens: a state machine."""

from generic.sites import ModelResource, register
from tests.testapp.models import Manuscript


@register(Manuscript)
class ManuscriptResource(ModelResource):
    list_display = ("title", "state")
    search_fields = ("title",)
    fields = ("title", "summary", "verdict", "state")
    transitions = ("state",)

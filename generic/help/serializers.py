"""The help settings as a form."""

from __future__ import annotations

from generic.api.forms import FormModelSerializer
from generic.help.models import HelpSettings


class HelpSettingsSerializer(FormModelSerializer):
    """What an administrator changes from the help page."""

    class Meta:
        model = HelpSettings
        fields = ("bug_report_url",)

    # One field under the card's own title: no section heading of its
    # own above it.
    form_sections = (
        {"name": "general", "title": "", "description": "", "position": 0},
    )
    form_overrides = {
        "bug_report_url": {
            "position": 0,
            "width": 12,
            # Replaced by the project's default when it has one, which is
            # what an empty field means (HelpSettingsFormSchemaView).
            "placeholder": "https://tickets.example.com/new",
        },
    }

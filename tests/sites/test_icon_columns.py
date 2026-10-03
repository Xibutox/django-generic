"""A computed column drawn as icons one clicks: ``@display(icons=True)``."""

from __future__ import annotations

import pytest
from django.utils.translation import gettext_lazy as _

from example.models import Tag
from generic.sites import display, site
from generic.sites.serializers import TableSerializerBuilder

pytestmark = pytest.mark.django_db


@display(description=_("Shortcuts"), icons=True)
def shortcuts(tag: Tag) -> list:
    return [
        {
            "icon": "visibility",
            "label": _("Preview"),
            "url": f"/tags/{tag.pk}/preview/",
        },
        {"label": "Other tab", "url": "/elsewhere/", "target": "_blank"},
        # Nowhere to go: left out.
        {"icon": "download", "label": "Download", "url": ""},
        None,
    ]


def table() -> type:
    return TableSerializerBuilder(
        site.get_resource(Tag), list_display=("name", shortcuts)
    ).build()


class TestIconColumns:
    def test_the_column_is_drawn_as_icons(self):
        columns = {
            column["data"]: column
            for column in table().get_datatable_columns()
        }

        assert columns["shortcuts"]["type"] == "icons"
        assert columns["shortcuts"]["title"] == "Shortcuts"
        assert columns["shortcuts"]["orderable"] is False
        assert columns["shortcuts"]["searchable"] is False

    def test_an_export_leaves_it_out(self):
        exported = [column["data"] for column in table().get_export_columns()]

        assert "shortcuts" not in exported
        assert "name" in exported

    def test_a_row_carries_the_icons_with_an_address(self, support_desk):
        billing = support_desk["billing"]

        assert table()(billing).data["shortcuts"] == [
            {
                "icon": "visibility",
                "url": f"/tags/{billing.pk}/preview/",
                "label": "Preview",
            },
            {
                "icon": "link",
                "url": "/elsewhere/",
                "label": "Other tab",
                "target": "_blank",
            },
        ]

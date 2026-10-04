"""Columns a table starts without: ``list_display_hidden``."""

from __future__ import annotations

import pytest

from example.models import Tag
from generic.sites import ModelResource, site
from generic.sites.serializers import TableSerializerBuilder

pytestmark = pytest.mark.django_db


class TagResource(ModelResource):
    list_display = ("name", "color", "background")
    list_display_hidden = ("background", "nowhere")


def columns() -> dict:
    serializer = TableSerializerBuilder(TagResource(Tag, site)).build()

    return {
        column["data"]: column for column in serializer.get_datatable_columns()
    }


class TestHiddenColumns:
    def test_a_hidden_column_is_sent_hidden(self):
        assert columns()["background"]["visible"] is False

    def test_the_others_stay_shown(self):
        assert "visible" not in columns()["name"]
        assert "visible" not in columns()["color"]

    def test_the_first_column_still_links_to_its_row(self):
        assert columns()["name"]["type"] == "link"

    def test_a_name_the_table_has_not_is_left_alone(self):
        assert "nowhere" not in columns()

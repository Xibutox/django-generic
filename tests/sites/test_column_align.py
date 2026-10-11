"""Where a column places its content: ``align``."""

from __future__ import annotations

import pytest
from django.utils.translation import gettext_lazy as _

from example.models import Tag
from generic.api.columns import CharColumn, ColumnOptions
from generic.api.serializers import DataTableSerializer
from generic.sites import ModelResource, display, site
from generic.sites.serializers import TableSerializerBuilder

pytestmark = pytest.mark.django_db


class TagResource(ModelResource):
    list_display = ("name", "color", "background", "logo")
    list_display_align = {"color": "center", "nowhere": "right"}

    @display(description=_("Logo"), icons=True, align="center")
    def logo(self, tag: Tag) -> list:
        return [{"icon": "sell", "label": tag.name, "url": "/tags/"}]


def columns(resource: ModelResource | None = None) -> dict:
    serializer = TableSerializerBuilder(
        resource or TagResource(Tag, site)
    ).build()

    return {
        column["data"]: column for column in serializer.get_datatable_columns()
    }


class TestColumnAlign:
    def test_a_column_left_alone_says_nothing(self):
        assert "align" not in columns()["background"]

    def test_a_field_column_is_placed_by_the_resource(self):
        assert columns()["color"]["align"] == "center"

    def test_a_method_column_is_placed_by_its_display(self):
        logo = columns()["logo"]

        assert logo["type"] == "icons"
        assert logo["align"] == "center"

    def test_a_name_the_table_has_not_is_left_alone(self):
        assert "nowhere" not in columns()

    def test_the_first_column_still_links_when_placed(self):
        class Placed(TagResource):
            list_display_align = {"name": "right"}

        name = columns(Placed(Tag, site))["name"]

        assert name["type"] == "link"
        assert name["align"] == "right"

    def test_any_column_class_takes_it(self):
        class Serializer(DataTableSerializer):
            code = CharColumn(align="right")

        assert Serializer.get_datatable_columns()[0]["align"] == "right"

    def test_an_unknown_alignment_raises(self):
        with pytest.raises(ValueError, match="left, center, right"):
            ColumnOptions(align="middle")

    def test_an_unknown_alignment_in_the_resource_raises(self):
        class Misplaced(TagResource):
            list_display_align = {"color": "middle"}

        with pytest.raises(ValueError, match="middle"):
            columns(Misplaced(Tag, site))

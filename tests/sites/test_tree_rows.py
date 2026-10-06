"""A tree laid flat: everything an article holds, at every depth, as a
table - the example's exploded bill of materials."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Article, ArticleFamily, BomLine
from generic.sites import Tree, site
from generic.sites.trees import bind_tree

pytestmark = pytest.mark.django_db

FLAT = "/api/example/article/trees/bom/flat/"


def table(client, root, **params) -> dict:
    response = client.get(
        FLAT, {"draw": 1, "length": 100, "root": root.pk, **params}
    )

    assert response.status_code == 200, response.content

    return response.json()


def rows(client, root, **params) -> list[dict]:
    return table(client, root, **params)["data"]


def column(data: list[dict], key: str) -> list:
    return [row[key] for row in data]


class TestOneRowPerPlace:
    def test_every_level_depth_first_in_the_lines_order(
        self, admin_client, bom
    ):
        data = rows(admin_client, bom["BK-1"])

        assert column(data, "label") == [
            "WH-1 Wheel",
            "HB-1 Hub",
            "SC-1 Screw",
            "SP-1 Spoke",
            "SC-1 Screw",
        ]
        assert column(data, "level") == [1, 2, 3, 2, 1]
        assert column(data, "parent") == [
            "BK-1 City bicycle",
            "WH-1 Wheel",
            "HB-1 Hub",
            "WH-1 Wheel",
            "BK-1 City bicycle",
        ]
        assert data[2]["path"] == ("BK-1 City bicycle › WH-1 Wheel › HB-1 Hub")

    def test_quantities_multiply_down_each_path(self, admin_client, bom):
        data = rows(admin_client, bom["BK-1"])

        # Two wheels, one hub each, four screws per hub: eight screws.
        assert column(data, "total_quantity") == [
            "2.000",
            "2.000",
            "8.000",
            "64.000",
            "12.000",
        ]
        assert column(data, "link_quantity") == [
            "2.000",
            "1.000",
            "4.000",
            "32.000",
            "12.000",
        ]

    def test_each_row_carries_the_records_own_values(self, admin_client, bom):
        data = rows(admin_client, bom["WH-1"])

        assert column(data, "kind") == ["assembly", "part", "part"]
        assert data[0]["record"] == str(bom["HB-1"].pk)
        assert (
            len({row["_pk"] for row in rows(admin_client, bom["BK-1"])}) == 5
        )

    def test_filtered_searched_and_sorted_as_any_table(
        self, admin_client, bom
    ):
        filters = json.dumps(
            {
                "match": "all",
                "conditions": [
                    {"column": "level", "operator": "gte", "value": "2"}
                ],
            }
        )

        assert column(
            rows(admin_client, bom["BK-1"], filters=filters), "label"
        ) == ["HB-1 Hub", "SC-1 Screw", "SP-1 Spoke"]
        assert column(
            rows(admin_client, bom["BK-1"], search="screw"), "level"
        ) == [3, 1]
        assert (
            column(
                rows(admin_client, bom["BK-1"], ordering="-total_quantity"),
                "label",
            )[0]
            == "SP-1 Spoke"
        )

    def test_exported(self, admin_client, bom):
        response = admin_client.get(
            f"{FLAT}export-csv/", {"root": bom["BK-1"].pk}
        )
        lines = b"".join(response.streaming_content).decode("utf-8-sig")

        assert response.status_code == 200
        assert len(lines.splitlines()) == 6
        assert (
            admin_client.get(
                f"{FLAT}export/", {"root": bom["BK-1"].pk}
            ).status_code
            == 200
        )

    def test_a_record_inside_itself_is_listed_once(self, admin_client, bom):
        # Written past the forms, which would refuse it.
        BomLine.objects.create(parent=bom["HB-1"], child=bom["WH-1"])

        data = rows(admin_client, bom["WH-1"])

        assert column(data, "label") == [
            "HB-1 Hub",
            "SC-1 Screw",
            "WH-1 Wheel",
            "SP-1 Spoke",
        ]

    def test_the_rows_are_capped(self, admin_client, bom, monkeypatch):
        monkeypatch.setattr("generic.sites.tree_rows.MAX_ROWS", 2)

        assert len(rows(admin_client, bom["BK-1"])) == 2


class TestOneRowPerRecord:
    def test_quantities_add_up(self, admin_client, bom):
        data = rows(admin_client, bom["BK-1"], grouped=1)

        assert column(data, "label") == [
            "WH-1 Wheel",
            "HB-1 Hub",
            "SC-1 Screw",
            "SP-1 Spoke",
        ]
        # Eight in the hubs, twelve on the frame.
        assert column(data, "total_quantity") == [
            "2.000",
            "2.000",
            "20.000",
            "64.000",
        ]
        assert column(data, "places") == [1, 1, 2, 1]
        assert column(data, "level") == [1, 2, 1, 2]
        assert "path" not in data[0]


class TestRefusals:
    def test_the_record_is_required(self, admin_client, bom):
        response = admin_client.get(FLAT, {"draw": 1})

        assert response.status_code == 400

    def test_an_unknown_record_is_not_found(self, admin_client, bom):
        response = admin_client.get(FLAT, {"draw": 1, "root": 999999})

        assert response.status_code == 404

    def test_a_reader_without_the_view_permission_is_refused(
        self, client, django_user_model, bom
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))

        response = client.get(FLAT, {"draw": 1, "root": bom["BK-1"].pk})

        assert response.status_code == 403

    def test_the_links_values_need_the_links_view_permission(
        self, client, django_user_model, bom
    ):
        user = django_user_model.objects.create_user(username="reader")
        user.user_permissions.set(
            Permission.objects.filter(codename="view_article")
        )
        client.force_login(user)

        data = rows(client, bom["BK-1"])

        assert len(data) == 5
        assert "total_quantity" not in data[0]
        assert "link_quantity" not in data[0]


class TestThePage:
    def test_a_page_per_record(self, admin_client, bom):
        response = admin_client.get(
            f"/example/article/{bom['BK-1'].pk}/bom-flat/"
        )
        config = response.context["table"]

        assert response.status_code == 200
        assert config["url"] == FLAT
        assert config["options"]["extraParams"] == {
            "root": str(bom["BK-1"].pk)
        }
        assert [entry["data"] for entry in config["columns"]][:4] == [
            "level",
            "label",
            "parent",
            "path",
        ]
        assert "Exploded BOM" in response.content.decode()

    def test_grouped(self, admin_client, bom):
        response = admin_client.get(
            f"/example/article/{bom['BK-1'].pk}/bom-flat/", {"grouped": 1}
        )
        config = response.context["table"]

        assert config["options"]["extraParams"]["grouped"] == "1"
        assert "places" in [entry["data"] for entry in config["columns"]]

    def test_the_tab_offers_it(self, admin_client, bom):
        response = admin_client.get(
            f"/api/example/article/{bom['BK-1'].pk}/summary/"
        )
        tabs = {tab["name"]: tab for tab in response.json()["related"]}

        assert tabs["tree-bom"]["flatUrl"] == (
            f"/example/article/{bom['BK-1'].pk}/bom-flat/"
        )
        assert tabs["tree-bom"]["flatTitle"] == "Exploded BOM"
        assert tabs["tree-bom-up"]["flatUrl"] == ""


class TestDeclaring:
    def resource(self):
        return site.get_resource(Article)

    @pytest.mark.parametrize(
        "tree",
        [
            # A quantity is a link's.
            Tree("x", quantity="quantity"),
            Tree(
                "x",
                through=BomLine,
                child="child",
                quantity="nothing",
            ),
            # The flat table's own columns keep their names.
            Tree("x", through=BomLine, child="child", columns=("level",)),
        ],
    )
    def test_a_declaration_that_could_not_work_is_refused(self, tree):
        flat = Tree(**{**tree.__dict__, "flat": True})

        with pytest.raises(ImproperlyConfigured):
            bind_tree(flat, self.resource())

    def test_only_a_tree_declared_flat_has_a_flat_table(self, client):
        families = site.get_resource(ArticleFamily).get_tree("families")

        assert self.resource().get_tree("bom").get_flat() is not None
        assert families.get_flat() is None

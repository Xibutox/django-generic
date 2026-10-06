"""Trees: records holding records, unfolded a level at a time.

The example declares both shapes: articles holding articles through
bill of materials lines (a link model, with a quantity), and article
families pointing at their parent. The browser names a tree and a
record; everything else is the declaration's and the resources'.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from example.models import Article, ArticleFamily, BomLine
from generic.sites import ModelResource, Tree, site
from generic.sites.trees import bind_tree

pytestmark = pytest.mark.django_db

BOM = "/api/example/article/trees/bom/"
FAMILIES = "/api/example/articlefamily/trees/families/"
LINES = "/api/example/bomline/"


def labels(answer: dict) -> list[str]:
    return [item["label"] for item in answer["items"]]


def get(client, url: str, **params) -> dict:
    response = client.get(url, params)

    assert response.status_code == 200, response.content

    return response.json()


@pytest.fixture
def reader_client(client, django_user_model):
    """Reads the articles, not the lines between them."""
    user = django_user_model.objects.create_user(username="reader")
    user.user_permissions.set(
        Permission.objects.filter(codename__in=("view_article",))
    )
    client.force_login(user)

    return client


class TestLevels:
    def test_the_roots_are_the_articles_nothing_holds(self, admin_client, bom):
        answer = get(admin_client, BOM)

        assert labels(answer) == ["BK-1 City bicycle", "LO-1 Loose part"]
        assert [item["children"] for item in answer["items"]] == [2, 0]
        assert answer["node"] is None

    def test_a_level_lists_the_components_in_the_lines_order(
        self, admin_client, bom
    ):
        answer = get(admin_client, BOM, node=bom["WH-1"].pk)

        assert labels(answer) == ["HB-1 Hub", "SP-1 Spoke"]
        assert answer["total"] == 2
        hub = answer["items"][0]
        assert hub["children"] == 1
        assert hub["key"] == str(bom["lines"][("WH-1", "HB-1")].pk)
        assert hub["id"] == str(bom["HB-1"].pk)
        assert hub["url"] == f"/example/article/{bom['HB-1'].pk}/"

    def test_each_record_carries_its_link_and_its_own_values(
        self, admin_client, bom
    ):
        answer = get(admin_client, BOM, node=bom["WH-1"].pk)
        keys = [column["key"] for column in answer["columns"]]
        spoke = answer["items"][1]

        assert keys == [
            "link.position",
            "link.quantity",
            "node.kind",
            "node.unit",
            "node.unit_cost",
        ]
        assert spoke["cells"][1] == {"type": "number", "display": "32.000"}
        assert spoke["cells"][2]["type"] == "tags"
        assert spoke["cells"][2]["items"][0]["label"] == "Part"
        line = bom["lines"][("WH-1", "SP-1")]
        assert spoke["linkUrl"] == f"/example/bomline/{line.pk}/change/"

    def test_a_level_is_served_a_page_at_a_time(self, admin_client, bom):
        hub = bom["HB-1"]
        BomLine.objects.bulk_create(
            BomLine(
                parent=hub,
                child=Article.objects.create(
                    reference=f"BR-{index:03}", name="Bearing"
                ),
                position=100 + index,
            )
            for index in range(120)
        )

        first = get(admin_client, BOM, node=hub.pk, limit=50)
        third = get(admin_client, BOM, node=hub.pk, limit=50, offset=100)

        assert first["total"] == 121
        assert len(first["items"]) == 50
        assert len(third["items"]) == 21
        assert labels(third)[-1] == "BR-119 Bearing"

    def test_no_page_is_larger_than_the_cap(self, admin_client, bom):
        answer = get(admin_client, BOM, node=bom["WH-1"].pk, limit=10_000)

        assert answer["limit"] == 500

    def test_a_level_is_searched_on_its_own(self, admin_client, bom):
        answer = get(admin_client, BOM, node=bom["WH-1"].pk, q="spoke")

        assert labels(answer) == ["SP-1 Spoke"]
        assert answer["total"] == 1

    def test_upwards_lists_what_holds_a_record(self, admin_client, bom):
        answer = get(admin_client, BOM, node=bom["SC-1"].pk, direction="up")

        assert labels(answer) == ["BK-1 City bicycle", "HB-1 Hub"]
        # The hub is held by the wheel, which unfolds further up.
        assert [item["children"] for item in answer["items"]] == [0, 1]
        assert answer["items"][1]["cells"][1]["display"] == "4.000"

    def test_one_record_alone_tops_a_tree_shown_from_it(
        self, admin_client, bom
    ):
        answer = get(admin_client, BOM, root=bom["WH-1"].pk)

        assert labels(answer) == ["WH-1 Wheel"]
        assert answer["items"][0]["children"] == 2

    def test_a_record_met_again_below_itself_is_not_unfolded(
        self, admin_client, bom
    ):
        # Written past the forms, which would refuse it.
        BomLine.objects.create(parent=bom["HB-1"], child=bom["WH-1"])
        path = f"{bom['BK-1'].pk},{bom['WH-1'].pk}"

        answer = get(admin_client, BOM, node=bom["HB-1"].pk, path=path)
        wheel = next(item for item in answer["items"] if item["cycle"])

        assert wheel["label"] == "WH-1 Wheel"
        assert wheel["children"] == 0


class TestModelPointingAtItsParent:
    def test_the_roots_are_the_families_without_a_parent(
        self, admin_client, bom
    ):
        answer = get(admin_client, FAMILIES)

        assert labels(answer) == ["Bicycles"]
        assert answer["items"][0]["children"] == 1
        assert answer["columns"] == [
            {"key": "node.article_count", "label": "Articles"}
        ]

    def test_a_level_lists_the_children(self, admin_client, bom):
        answer = get(admin_client, FAMILIES, node=bom["wheels"].pk)

        assert labels(answer) == ["Hubs"]
        assert answer["items"][0]["key"] == str(bom["hubs"].pk)
        assert answer["items"][0]["linkUrl"] == ""

    def test_upwards_is_the_parent(self, admin_client, bom):
        answer = get(
            admin_client, FAMILIES, node=bom["hubs"].pk, direction="up"
        )

        assert labels(answer) == ["Wheels"]
        assert answer["items"][0]["children"] == 1


def shape(items: list[dict]) -> list:
    """The labels of a search's answer, nested as its branches are."""
    return [
        (
            item["label"],
            item["match"],
            shape(item["items"]) if "items" in item else None,
        )
        for item in items
    ]


class TestFind:
    def test_the_branches_leading_to_a_match_are_unfolded(
        self, admin_client, bom
    ):
        answer = get(admin_client, BOM, find="screw")

        assert shape(answer["items"]) == [
            (
                "BK-1 City bicycle",
                False,
                [
                    (
                        "WH-1 Wheel",
                        False,
                        [("HB-1 Hub", False, [("SC-1 Screw", True, None)])],
                    ),
                    ("SC-1 Screw", True, None),
                ],
            ),
        ]
        # Found in two places, it is one record.
        assert answer["matches"] == 1
        assert answer["truncated"] is False

    def test_each_item_is_described_as_a_levels_are(self, admin_client, bom):
        answer = get(admin_client, BOM, find="screw")
        bicycle = answer["items"][0]
        wheel = bicycle["items"][0]

        # Its count is the whole level's, not the part shown.
        assert wheel["children"] == 2
        assert wheel["key"] == str(bom["lines"][("BK-1", "WH-1")].pk)
        assert bicycle["key"] == str(bom["BK-1"].pk)
        assert wheel["cells"][1]["display"] == "2.000"
        assert answer["columns"] == get(admin_client, BOM)["columns"]

    def test_from_a_record_its_own_level_comes_first(self, admin_client, bom):
        answer = get(admin_client, BOM, node=bom["WH-1"].pk, find="SC-")

        assert shape(answer["items"]) == [
            ("HB-1 Hub", False, [("SC-1 Screw", True, None)])
        ]
        assert answer["node"] == str(bom["WH-1"].pk)

    def test_from_one_record_alone(self, admin_client, bom):
        answer = get(admin_client, BOM, root=bom["HB-1"].pk, find="screw")

        assert shape(answer["items"]) == [
            ("HB-1 Hub", False, [("SC-1 Screw", True, None)])
        ]

    def test_upwards(self, admin_client, bom):
        answer = get(
            admin_client,
            BOM,
            node=bom["SC-1"].pk,
            direction="up",
            find="bicycle",
        )

        assert shape(answer["items"]) == [
            ("BK-1 City bicycle", True, None),
            (
                "HB-1 Hub",
                False,
                [("WH-1 Wheel", False, [("BK-1 City bicycle", True, None)])],
            ),
        ]

    def test_a_match_holding_no_match_stays_folded(self, admin_client, bom):
        answer = get(admin_client, BOM, find="wheel")
        wheel = answer["items"][0]["items"][0]

        assert wheel["match"] is True
        assert "items" not in wheel
        assert wheel["children"] == 2

    def test_nothing_matches(self, admin_client, bom):
        answer = get(admin_client, BOM, find="nothing like it")

        assert answer["items"] == []
        assert answer["matches"] == 0

    def test_a_record_inside_itself_ends_the_branch(self, admin_client, bom):
        # Written past the forms, which would refuse it.
        BomLine.objects.create(parent=bom["HB-1"], child=bom["WH-1"])

        answer = get(admin_client, BOM, node=bom["WH-1"].pk, find="spoke")

        assert shape(answer["items"]) == [
            (
                "HB-1 Hub",
                False,
                [("WH-1 Wheel", False, None)],
            ),
            ("SP-1 Spoke", True, None),
        ]
        assert answer["items"][0]["items"][0]["cycle"] is True

    def test_a_model_pointing_at_its_parent(self, admin_client, bom):
        answer = get(admin_client, FAMILIES, find="hubs")

        assert shape(answer["items"]) == [
            (
                "Bicycles",
                False,
                [("Wheels", False, [("Hubs", True, None)])],
            )
        ]

    def test_and_upwards(self, admin_client, bom):
        answer = get(
            admin_client,
            FAMILIES,
            node=bom["hubs"].pk,
            direction="up",
            find="bicycles",
        )

        assert shape(answer["items"]) == [
            ("Wheels", False, [("Bicycles", True, None)])
        ]

    def test_a_long_answer_is_cut_and_says_so(
        self, admin_client, bom, monkeypatch
    ):
        monkeypatch.setattr("generic.sites.trees.MAX_FIND_ITEMS", 2)

        answer = get(admin_client, BOM, find="screw")

        assert answer["truncated"] is True
        assert shape(answer["items"]) == [
            ("BK-1 City bicycle", False, [("WH-1 Wheel", False, [])])
        ]

    def test_a_long_walk_is_cut_and_says_so(
        self, admin_client, bom, monkeypatch
    ):
        monkeypatch.setattr("generic.sites.trees.MAX_FIND_WALK", 2)

        answer = get(admin_client, BOM, find="screw")

        assert answer["truncated"] is True


class TestTheTablesFilters:
    """The resource's own table, above the tree: its filters and search
    box find records at every level."""

    def filters(self, *conditions) -> str:
        return json.dumps({"match": "all", "conditions": list(conditions)})

    def test_a_filter_on_a_column(self, admin_client, bom):
        answer = get(
            admin_client,
            BOM,
            filters=self.filters(
                {"column": "kind", "operator": "any_of", "value": ["assembly"]}
            ),
        )

        assert shape(answer["items"]) == [
            (
                "BK-1 City bicycle",
                False,
                [("WH-1 Wheel", True, [("HB-1 Hub", True, None)])],
            )
        ]
        assert answer["matches"] == 2
        assert answer["filtered"] is True

    def test_the_search_box(self, admin_client, bom):
        answer = get(admin_client, BOM, node=bom["WH-1"].pk, search="spoke")

        assert shape(answer["items"]) == [("SP-1 Spoke", True, None)]

    def test_with_find_too(self, admin_client, bom):
        answer = get(
            admin_client,
            BOM,
            find="screw",
            filters=self.filters(
                {"column": "kind", "operator": "any_of", "value": ["part"]}
            ),
        )

        assert answer["matches"] == 1
        assert answer["filtered"] is True

    def test_nothing_selected(self, admin_client, bom):
        answer = get(
            admin_client,
            BOM,
            filters=self.filters(
                {"column": "kind", "operator": "any_of", "value": ["material"]}
            ),
        )

        assert answer["items"] == []

    def test_an_unknown_column_is_refused(self, admin_client, bom):
        response = admin_client.get(
            BOM,
            {
                "filters": self.filters(
                    {"column": "secret", "operator": "equals", "value": "x"}
                )
            },
        )

        assert response.status_code == 400

    def test_the_page_and_the_tabs_carry_the_table(self, admin_client, bom):
        page = admin_client.get("/example/article/bom/")
        detail = admin_client.get(f"/example/article/{bom['WH-1'].pk}/")

        assert page.context["tree_config"]["filterTable"] == (
            "tree-filter-table"
        )
        assert page.context["filter_table"]["url"] == "/api/example/article/"
        assert [panel["filter_id"] for panel in detail.context["trees"]] == [
            "related-tree-bom-filters",
            "related-tree-bom-up-filters",
        ]


class TestRefusals:
    def test_an_unknown_tree_is_not_found(self, admin_client, bom):
        response = admin_client.get("/api/example/article/trees/nope/")

        assert response.status_code == 404

    def test_an_unknown_record_is_not_found(self, admin_client, bom):
        assert admin_client.get(BOM, {"node": 999999}).status_code == 404
        assert admin_client.get(BOM, {"node": "x"}).status_code == 404

    def test_a_direction_not_offered_is_refused(self, admin_client, bom):
        response = admin_client.get(BOM, {"direction": "sideways"})

        assert response.status_code == 400

    def test_a_bad_offset_is_refused(self, admin_client, bom):
        assert admin_client.get(BOM, {"offset": "-1"}).status_code == 400
        assert admin_client.get(BOM, {"limit": "many"}).status_code == 400

    def test_a_reader_without_the_view_permission_is_refused(
        self, client, django_user_model, bom
    ):
        client.force_login(django_user_model.objects.create_user("nobody"))

        assert client.get(BOM).status_code == 403

    def test_the_links_values_need_the_links_view_permission(
        self, reader_client, bom
    ):
        answer = get(reader_client, BOM, node=bom["WH-1"].pk)

        assert [column["key"] for column in answer["columns"]] == [
            "node.kind",
            "node.unit",
            "node.unit_cost",
        ]
        assert labels(answer) == ["HB-1 Hub", "SP-1 Spoke"]
        assert answer["items"][0]["linkUrl"] == ""


class TestNoRecordInsideItself:
    def line(self, client, parent, child, quantity="1"):
        return client.post(
            LINES,
            {
                "parent": parent.pk,
                "child": child.pk,
                "position": 10,
                "quantity": quantity,
            },
            content_type="application/json",
        )

    def test_a_line_into_a_new_branch_is_saved(self, admin_client, bom):
        response = self.line(admin_client, bom["LO-1"], bom["SC-1"])

        assert response.status_code == 201, response.content

    def test_an_article_cannot_contain_itself(self, admin_client, bom):
        response = self.line(admin_client, bom["HB-1"], bom["HB-1"])

        assert response.status_code == 400
        assert "child" in response.json()

    def test_an_article_cannot_contain_what_contains_it(
        self, admin_client, bom
    ):
        # The spoke is inside the bicycle, three levels down.
        response = self.line(admin_client, bom["SP-1"], bom["BK-1"])

        assert response.status_code == 400
        assert "already contains" in str(response.json()["child"])
        assert not BomLine.objects.filter(parent=bom["SP-1"]).exists()

    def test_changing_a_line_is_checked_too(self, admin_client, bom):
        line = bom["lines"][("HB-1", "SC-1")]

        response = admin_client.patch(
            f"{LINES}{line.pk}/",
            {"child": bom["BK-1"].pk},
            content_type="application/json",
        )

        assert response.status_code == 400
        line.refresh_from_db()
        assert line.child == bom["SC-1"]

    def test_a_line_keeps_its_own_place_when_changed(self, admin_client, bom):
        line = bom["lines"][("WH-1", "HB-1")]

        response = admin_client.patch(
            f"{LINES}{line.pk}/",
            {"quantity": "3"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        line.refresh_from_db()
        assert line.quantity == Decimal("3")

    def test_a_family_cannot_move_under_its_own_child(self, admin_client, bom):
        response = admin_client.patch(
            f"/api/example/articlefamily/{bom['bikes'].pk}/",
            {"parent": bom["hubs"].pk},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "parent" in response.json()

    def test_a_family_may_move_elsewhere(self, admin_client, bom):
        other = ArticleFamily.objects.create(name="Spares")

        response = admin_client.patch(
            f"/api/example/articlefamily/{bom['hubs'].pk}/",
            {"parent": other.pk},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content


class TestPages:
    def test_the_summary_has_a_tab_each_way(self, admin_client, bom):
        response = admin_client.get(f"/example/article/{bom['WH-1'].pk}/")
        related = response.context["summary"]["related"]
        tabs = {entry["name"]: entry for entry in related}

        assert tabs["tree-bom"]["count"] == 2
        assert tabs["tree-bom"]["kind"] == "tree"
        assert tabs["tree-bom-up"]["count"] == 1
        assert tabs["tree-bom"]["addUrl"].startswith(
            f"/example/bomline/add/?parent={bom['WH-1'].pk}"
        )
        assert tabs["tree-bom"]["pageUrl"] == (
            f"/example/article/bom/?root={bom['WH-1'].pk}"
        )
        panels = response.context["trees"]
        assert [panel["name"] for panel in panels] == [
            "tree-bom",
            "tree-bom-up",
        ]
        assert panels[0]["config"]["node"] == str(bom["WH-1"].pk)
        assert panels[1]["config"]["direction"] == "up"

    def test_the_tree_comes_first_then_the_grid_editing_it(
        self, admin_client, bom
    ):
        response = admin_client.get(f"/example/article/{bom['WH-1'].pk}/")
        names = [
            entry["name"] for entry in response.context["summary"]["related"]
        ]

        # ArticleResource.tab_order; Where used was not named: it follows.
        assert names == ["tree-bom", "bom_lines", "tree-bom-up"]

    def test_a_reader_who_may_not_add_lines_gets_no_add(
        self, reader_client, bom
    ):
        response = reader_client.get(f"/example/article/{bom['WH-1'].pk}/")
        tabs = {
            entry["name"]: entry
            for entry in response.context["summary"]["related"]
        }

        assert tabs["tree-bom"]["addUrl"] == ""

    def test_the_page_of_the_whole_tree(self, admin_client, bom):
        response = admin_client.get("/example/article/bom/")

        assert response.status_code == 200
        config = response.context["tree_config"]
        assert config["url"] == BOM
        assert config["root"] is None
        assert config["topics"]

    def test_the_page_from_one_record(self, admin_client, bom):
        response = admin_client.get(
            "/example/article/bom/", {"root": bom["WH-1"].pk}
        )

        assert response.status_code == 200
        assert response.context["tree_config"]["root"] == str(bom["WH-1"].pk)
        assert response.context["root_label"] == "WH-1 Wheel"

    def test_the_page_from_an_unknown_record_is_not_found(
        self, admin_client, bom
    ):
        response = admin_client.get("/example/article/bom/", {"root": 0})

        assert response.status_code == 404

    def test_the_list_offers_the_page(self, admin_client, bom):
        response = admin_client.get("/example/article/")
        urls = [item.url for item in response.context["toolbar_items"]]

        assert "/example/article/bom/" in urls


class TestDeclaring:
    def resource(self, model=Article, **attributes):
        klass = type("Declared", (ModelResource,), attributes)

        return klass(model, site)

    @pytest.mark.parametrize(
        "tree, message",
        [
            (Tree("Bad Name"), "lower case"),
            (Tree("bom", through=BomLine), "needs 'child'"),
            (
                Tree("bom", through=BomLine, parent="note", child="child"),
                "foreign key",
            ),
            (
                Tree("bom", through=BomLine, parent="nope", child="child"),
                "not a field",
            ),
            (Tree("bom", parent="family"), "foreign key to Article"),
            (Tree("bom", parent="parent", child="child"), "'through'"),
            (Tree("families", page_size=0), "page_size"),
            (Tree("families", columns=("nope",)), "neither a field"),
            (Tree("families", roots="nope"), "not a method"),
        ],
    )
    def test_a_declaration_that_could_not_work_is_refused(self, tree, message):
        model = ArticleFamily if tree.through is None else Article

        if tree.parent == "family":
            model = Article

        with pytest.raises(ImproperlyConfigured, match=message):
            bind_tree(tree, self.resource(model))

    def test_a_link_column_must_be_a_field_of_the_link(self):
        tree = Tree(
            "bom",
            through=BomLine,
            parent="parent",
            child="child",
            link_columns=("nope",),
        )

        with pytest.raises(ImproperlyConfigured, match="BomLine"):
            bind_tree(tree, self.resource())

    def test_two_trees_of_one_name_are_refused(self):
        resource = self.resource(
            ArticleFamily, trees=(Tree("families"), Tree("families"))
        )

        with pytest.raises(ImproperlyConfigured, match="twice"):
            resource.get_trees()

    def test_roots_may_be_chosen_by_the_resource(self, rf, admin_user, bom):
        resource = self.resource(
            Article,
            trees=(
                Tree(
                    "bom",
                    through=BomLine,
                    parent="parent",
                    child="child",
                    roots="assemblies",
                ),
            ),
            assemblies=lambda self, request, queryset: queryset.filter(
                kind="assembly"
            ),
        )
        request = rf.get("/")
        request.user = admin_user
        tree = resource.get_tree("bom")

        assert labels(tree.answer(request, {})) == ["HB-1 Hub", "WH-1 Wheel"]


class TestEditingTheFirstLevel:
    """The article's "Edit the BOM" tab: its own lines as a grid."""

    ROWS = f"{LINES}rows/"

    @staticmethod
    def related(article) -> str:
        return f"_related=example.article.bom_lines:{article.pk}"

    def send(self, client, method: str, url: str, data: dict):
        return getattr(client, method)(
            url, json.dumps(data), content_type="application/json"
        )

    def test_the_tab_is_a_grid_of_the_direct_components(
        self, admin_client, bom
    ):
        bike = bom["BK-1"]
        bound = site.get_related_table("example.article.bom_lines")
        config = bound.get_table_config(
            admin_client.get("/").wsgi_request, bike
        )
        options = config["options"]

        assert set(options["editable"]) == {
            "position",
            "child",
            "quantity",
            "note",
        }
        assert set(options["gridAdd"]["columns"]) == {
            "position",
            "child",
            "quantity",
            "note",
        }

        response = admin_client.get(
            f"{LINES}?draw=1&length=100&{self.related(bike)}"
        )
        children = {row["child"] for row in response.json()["data"]}

        # The wheel and the screw; never the wheel's own hub and spokes.
        assert len(children) == 2

    def test_a_quantity_is_corrected_in_its_cell(self, admin_client, bom):
        line = bom["lines"][("BK-1", "SC-1")]
        response = self.send(
            admin_client,
            "patch",
            f"{LINES}{line.pk}/cells/?{self.related(bom['BK-1'])}",
            {"quantity": "16"},
        )

        assert response.status_code == 200, response.content
        line.refresh_from_db()
        assert line.quantity == Decimal("16")

    def test_a_new_line_belongs_to_the_article(self, admin_client, bom):
        response = self.send(
            admin_client,
            "post",
            f"{self.ROWS}?{self.related(bom['BK-1'])}",
            {"child": bom["LO-1"].pk, "quantity": "3", "position": 30},
        )

        assert response.status_code == 201, response.content
        assert BomLine.objects.get(
            parent=bom["BK-1"], child=bom["LO-1"]
        ).quantity == Decimal("3")

    def test_a_component_holding_the_article_is_refused(
        self, admin_client, bom
    ):
        # The bicycle under the hub, which the bicycle already holds.
        response = self.send(
            admin_client,
            "post",
            f"{self.ROWS}?{self.related(bom['HB-1'])}",
            {"child": bom["BK-1"].pk, "quantity": "1"},
        )

        assert response.status_code == 400
        assert "child" in response.json()

        line = bom["lines"][("HB-1", "SC-1")]
        response = self.send(
            admin_client,
            "patch",
            f"{LINES}{line.pk}/cells/?{self.related(bom['HB-1'])}",
            {"child": bom["WH-1"].pk},
        )

        assert response.status_code == 400
        assert "child" in response.json()
        line.refresh_from_db()
        assert line.child == bom["SC-1"]

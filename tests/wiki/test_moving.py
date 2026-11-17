"""A page dragged elsewhere in the menu, or moved to another wiki."""

from __future__ import annotations

import pytest

from generic.wiki.models import Wiki, WikiMember, WikiPage, WikiRevision
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PAGES = "/wiki/api/pages/"


def send(client, method: str, url: str, data=None):
    return getattr(client, method)(url, data, content_type="application/json")


@pytest.fixture
def main():
    return Wiki.objects.get(slug="main")


@pytest.fixture
def pages(main):
    return {
        name: WikiPage.objects.create(
            wiki=main, title=name.title(), slug=name, position=index
        )
        for index, name in enumerate(("one", "two", "three"))
    }


def order(main, parent=None):
    return list(
        WikiPage.objects.filter(wiki=main, parent=parent)
        .order_by("position")
        .values_list("slug", flat=True)
    )


class TestPlace:
    def test_before_a_sibling(self, admin_client, main, pages):
        response = send(
            admin_client,
            "post",
            f"{PAGES}{pages['three'].pk}/place/",
            {"parent": None, "before": pages["one"].pk},
        )

        assert response.status_code == 200
        assert order(main) == ["three", "one", "two"]
        assert [row["position"] for row in response.json()] == [0, 1, 2]

    def test_last_without_a_sibling_named(self, admin_client, main, pages):
        send(admin_client, "post", f"{PAGES}{pages['one'].pk}/place/", {})

        assert order(main) == ["two", "three", "one"]

    def test_under_another_page(self, admin_client, main, pages):
        send(
            admin_client,
            "post",
            f"{PAGES}{pages['two'].pk}/place/",
            {"parent": pages["one"].pk},
        )

        assert order(main) == ["one", "three"]
        assert order(main, pages["one"]) == ["two"]

    def test_never_under_itself(self, admin_client, main, pages):
        pages["two"].parent = pages["one"]
        pages["two"].save()

        response = send(
            admin_client,
            "post",
            f"{PAGES}{pages['one'].pk}/place/",
            {"parent": pages["two"].pk},
        )

        assert response.status_code == 400
        assert WikiPage.objects.get(pk=pages["one"].pk).parent_id is None

    def test_a_parent_of_another_wiki_is_not_found(self, admin_client, pages):
        other = Wiki.objects.create(name="Other", slug="other")
        elsewhere = WikiPage.objects.create(wiki=other, title="X", slug="x")

        response = send(
            admin_client,
            "post",
            f"{PAGES}{pages['one'].pk}/place/",
            {"parent": elsewhere.pk},
        )

        assert response.status_code == 404

    def test_no_version_is_kept(self, admin_client, pages):
        send(admin_client, "post", f"{PAGES}{pages['one'].pk}/place/", {})

        assert not WikiRevision.objects.exists()

    def test_a_reader_may_not(self, client, main, pages):
        main.access = "private"
        main.save()
        reader = UserFactory()
        WikiMember.objects.create(wiki=main, user=reader, role="reader")
        client.force_login(reader)

        response = send(client, "post", f"{PAGES}{pages['one'].pk}/place/", {})

        assert response.status_code == 403

    def test_the_menu_is_draggable_for_an_editor(self, admin_client, pages):
        html = admin_client.get("/wiki/main/one/").content.decode()

        assert f'data-page="{pages["two"].pk}" draggable="true"' in html


class TestMoveToWiki:
    @pytest.fixture
    def other(self):
        return Wiki.objects.create(name="Other", slug="other")

    def test_with_its_subpages_and_history(
        self, admin_client, main, pages, other
    ):
        pages["two"].parent = pages["one"]
        pages["two"].save()
        WikiRevision.keep(pages["one"])

        response = send(
            admin_client,
            "post",
            f"{PAGES}{pages['one'].pk}/move/",
            {"wiki": other.pk},
        )

        assert response.status_code == 200
        assert response.json()["url"] == "/wiki/other/one/"
        assert order(main) == ["three"]
        assert order(other) == ["one"]
        assert order(other, pages["one"]) == ["two"]
        assert pages["one"].revisions.count() == 1

    def test_to_the_bottom_of_the_other_menu(self, admin_client, pages, other):
        WikiPage.objects.create(wiki=other, title="Z", slug="z", position=4)

        send(
            admin_client,
            "post",
            f"{PAGES}{pages['one'].pk}/move/",
            {"wiki": other.pk},
        )

        assert order(other) == ["z", "one"]

    def test_a_taken_address_gets_a_number(self, admin_client, pages, other):
        WikiPage.objects.create(wiki=other, title="One", slug="one")

        response = send(
            admin_client,
            "post",
            f"{PAGES}{pages['one'].pk}/move/",
            {"wiki": other.pk},
        )

        assert response.json()["url"] == "/wiki/other/one-2/"

    def test_the_old_addresses_lead_to_it(self, admin_client, pages, other):
        pages["two"].parent = pages["one"]
        pages["two"].save()

        send(
            admin_client,
            "post",
            f"{PAGES}{pages['one'].pk}/move/",
            {"wiki": other.pk},
        )

        assert (
            admin_client.get("/wiki/main/one/")["Location"]
            == "/wiki/other/one/"
        )
        assert (
            admin_client.get("/wiki/main/two/")["Location"]
            == "/wiki/other/two/"
        )

    def test_not_into_its_own_wiki(self, admin_client, main, pages):
        response = send(
            admin_client,
            "post",
            f"{PAGES}{pages['one'].pk}/move/",
            {"wiki": main.pk},
        )

        assert response.status_code == 400

    def test_only_into_a_wiki_one_writes_in(self, client, main, pages, other):
        main.access = "private"
        main.save()
        other.access = "private"
        other.save()
        editor = UserFactory()
        WikiMember.objects.create(wiki=main, user=editor, role="editor")
        WikiMember.objects.create(wiki=other, user=editor, role="reader")
        client.force_login(editor)

        response = send(
            client,
            "post",
            f"{PAGES}{pages['one'].pk}/move/",
            {"wiki": other.pk},
        )

        assert response.status_code == 403
        assert WikiPage.objects.get(pk=pages["one"].pk).wiki_id == main.pk

    def test_a_wiki_one_cannot_read_is_not_found(
        self, client, main, pages, other
    ):
        main.access = "private"
        main.save()
        other.access = "private"
        other.save()
        editor = UserFactory()
        WikiMember.objects.create(wiki=main, user=editor, role="editor")
        client.force_login(editor)

        response = send(
            client,
            "post",
            f"{PAGES}{pages['one'].pk}/move/",
            {"wiki": other.pk},
        )

        assert response.status_code == 404

    def test_the_page_offers_the_wikis_it_may_go_to(
        self, admin_client, pages, other
    ):
        response = admin_client.get("/wiki/main/one/")

        assert response.context["wiki_config"]["moveTargets"] == [
            {"id": other.pk, "name": "Other"}
        ]

    def test_a_trashed_subpage_restored_comes_to_the_top(
        self, admin_client, main, pages, other
    ):
        pages["two"].parent = pages["one"]
        pages["two"].save()
        send(admin_client, "delete", f"{PAGES}{pages['two'].pk}/")
        send(
            admin_client,
            "post",
            f"{PAGES}{pages['one'].pk}/move/",
            {"wiki": other.pk},
        )

        send(admin_client, "post", f"{PAGES}{pages['two'].pk}/undelete/")

        restored = WikiPage.objects.get(pk=pages["two"].pk)
        assert (restored.wiki_id, restored.parent_id) == (main.pk, None)

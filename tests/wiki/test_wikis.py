"""Several wikis: each its own menu, the API that manages them, who
sees which, and the addresses from before there were several."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from generic.wiki.models import Wiki, WikiPage
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

WIKIS = "/wiki/api/wikis/"
PAGES = "/wiki/api/pages/"


def post(client, url: str, data: dict):
    return client.post(url, data, content_type="application/json")


def patch(client, url: str, data: dict):
    return client.patch(url, data, content_type="application/json")


def writer(*codenames: str):
    user = UserFactory()
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="generic_wiki", codename__in=codenames
        )
    )

    return user


def only_open_wikis(user, wikis):
    """A ``WIKI_ACCESS`` hook: the wiki called "Secret" is hidden."""
    return wikis.exclude(slug="secret")


@pytest.fixture
def two_wikis() -> dict:
    main = Wiki.objects.get(slug="main")
    quality = Wiki.objects.create(name="Quality", slug="quality", position=1)

    return {
        "main": main,
        "quality": quality,
        "welcome": WikiPage.objects.create(
            wiki=main, title="Welcome", slug="welcome"
        ),
        "rules": WikiPage.objects.create(
            wiki=quality, title="Rules", slug="rules"
        ),
    }


class TestModel:
    def test_the_migration_made_a_first_wiki(self):
        assert Wiki.objects.filter(slug="main", name="Wiki").exists()

    def test_a_page_saved_without_a_wiki_goes_to_the_first(self):
        page = WikiPage.objects.create(title="Old code", slug="old-code")

        assert page.wiki.slug == "main"

    def test_a_subpage_lives_in_its_parent_wiki(self, two_wikis):
        child = WikiPage.objects.create(
            title="Child", slug="child", parent=two_wikis["rules"]
        )

        assert child.wiki == two_wikis["quality"]

    def test_the_first_wiki_comes_back_when_none_is_left(self):
        Wiki.objects.all().delete()

        page = WikiPage.objects.create(title="Again", slug="again")

        assert page.wiki.slug == "main"

    def test_two_wikis_may_use_the_same_address(self, two_wikis):
        twin = WikiPage.objects.create(
            wiki=two_wikis["quality"], title="Welcome", slug="welcome"
        )

        assert twin.get_absolute_url() == "/wiki/quality/welcome/"


class TestWikiApi:
    def test_the_list_counts_the_pages(self, auth_client, two_wikis):
        data = auth_client.get(WIKIS).json()

        assert [(wiki["slug"], wiki["page_count"]) for wiki in data] == [
            ("main", 1),
            ("quality", 1),
        ]
        assert data[1]["url"] == "/wiki/quality/"
        assert data[1]["pdf_url"] == "/wiki/quality/export.pdf"

    def test_a_reader_cannot_add_a_wiki(self, auth_client, db):
        assert post(auth_client, WIKIS, {"name": "Mine"}).status_code == 403

    def test_a_new_wiki_gets_a_free_address(self, client, db):
        client.force_login(writer("add_wiki"))

        first = post(client, WIKIS, {"name": "Files"})
        second = post(client, WIKIS, {"name": "Files"})

        assert first.status_code == 201, first.content
        # "files" is the wiki's own route.
        assert first.json()["slug"] == "files-wiki"
        assert second.json()["slug"] == "files-wiki-2"

    def test_a_reserved_address_is_refused(self, client, db):
        client.force_login(writer("add_wiki"))

        response = post(client, WIKIS, {"name": "X", "slug": "api"})

        assert response.status_code == 400
        assert "slug" in response.json()

    def test_renaming_needs_the_change_permission(self, client, two_wikis):
        url = f"{WIKIS}{two_wikis['quality'].pk}/"
        client.force_login(writer("add_wiki"))

        assert patch(client, url, {"name": "QA"}).status_code == 403

        client.force_login(writer("change_wiki"))
        response = patch(client, url, {"name": "QA", "description": "Ours"})

        assert response.status_code == 200, response.content
        two_wikis["quality"].refresh_from_db()
        assert two_wikis["quality"].name == "QA"
        # The address stays: links to its pages keep working.
        assert two_wikis["quality"].slug == "quality"

    def test_deleting_a_wiki_deletes_its_pages(self, client, two_wikis):
        client.force_login(writer("delete_wiki"))

        response = client.delete(f"{WIKIS}{two_wikis['quality'].pk}/")

        assert response.status_code == 204
        assert not WikiPage.objects.filter(slug="rules").exists()
        assert WikiPage.objects.filter(slug="welcome").exists()


class TestPagesApi:
    def test_a_page_is_created_in_the_wiki_named(
        self, admin_client, two_wikis
    ):
        response = post(
            admin_client,
            PAGES,
            {"title": "Welcome", "wiki": two_wikis["quality"].pk},
        )

        assert response.status_code == 201, response.content
        # Free in this wiki, though the first one has a "welcome".
        assert response.json()["url"] == "/wiki/quality/welcome/"

    def test_without_a_wiki_it_follows_its_parent(
        self, admin_client, two_wikis
    ):
        response = post(
            admin_client,
            PAGES,
            {"title": "Detail", "parent": two_wikis["rules"].pk},
        )

        assert response.json()["wiki"] == two_wikis["quality"].pk

    def test_a_parent_from_another_wiki_is_refused(
        self, admin_client, two_wikis
    ):
        response = post(
            admin_client,
            PAGES,
            {
                "title": "Lost",
                "wiki": two_wikis["main"].pk,
                "parent": two_wikis["rules"].pk,
            },
        )

        assert response.status_code == 400
        assert "parent" in response.json()

    def test_a_page_does_not_move_to_another_wiki(
        self, admin_client, two_wikis
    ):
        response = patch(
            admin_client,
            f"{PAGES}{two_wikis['welcome'].pk}/",
            {"wiki": two_wikis["quality"].pk},
        )

        assert response.status_code == 400
        assert "wiki" in response.json()

    def test_an_address_taken_in_the_wiki_is_refused(
        self, admin_client, two_wikis
    ):
        response = post(
            admin_client,
            PAGES,
            {
                "title": "Rules again",
                "slug": "rules",
                "wiki": two_wikis["quality"].pk,
            },
        )

        assert response.status_code == 400
        assert "slug" in response.json()

    def test_the_menu_of_one_wiki(self, auth_client, two_wikis):
        data = auth_client.get(PAGES, {"wiki": two_wikis["quality"].pk}).json()

        assert [page["title"] for page in data] == ["Rules"]


class TestPages:
    def test_the_list_of_wikis(self, admin_client, two_wikis):
        response = admin_client.get("/wiki/")

        assert response.status_code == 200
        assert [wiki.slug for wiki in response.context["wikis"]] == [
            "main",
            "quality",
        ]

    def test_a_reader_of_several_wikis_sees_the_list(
        self, auth_client, two_wikis
    ):
        assert auth_client.get("/wiki/").status_code == 200

    def test_the_menu_holds_this_wiki_only(self, auth_client, two_wikis):
        response = auth_client.get("/wiki/quality/rules/")

        assert [entry["title"] for entry in response.context["menu"]] == [
            "Rules"
        ]
        assert [wiki.slug for wiki in response.context["other_wikis"]] == [
            "main"
        ]
        assert response.context["wiki_config"]["wiki"] == (
            two_wikis["quality"].pk
        )

    def test_an_address_from_before_leads_to_the_page(
        self, auth_client, two_wikis
    ):
        response = auth_client.get("/wiki/welcome/")

        assert response.status_code == 301
        assert response.url == "/wiki/main/welcome/"

    def test_a_page_of_another_wiki_is_not_found(self, auth_client, two_wikis):
        assert auth_client.get("/wiki/main/rules/").status_code == 404


class TestAccess:
    @pytest.fixture(autouse=True)
    def hook(self, settings):
        settings.GENERIC = {
            **getattr(settings, "GENERIC", {}),
            "WIKI_ACCESS": "tests.wiki.test_wikis.only_open_wikis",
        }

    @pytest.fixture
    def secret(self, db) -> WikiPage:
        wiki = Wiki.objects.create(name="Secret", slug="secret")

        return WikiPage.objects.create(
            wiki=wiki, title="Hidden plans", slug="plans", content="<p>x</p>"
        )

    def test_a_hidden_wiki_is_not_found(self, auth_client, secret):
        assert auth_client.get("/wiki/secret/").status_code == 404
        assert auth_client.get("/wiki/secret/plans/").status_code == 404
        assert auth_client.get("/wiki/secret/export.pdf").status_code == 404

    def test_nor_listed_by_the_api(self, auth_client, secret):
        assert "secret" not in [
            wiki["slug"] for wiki in auth_client.get(WIKIS).json()
        ]
        assert auth_client.get(f"{PAGES}{secret.pk}/").status_code == 404

    def test_nor_found_by_the_palette(self, auth_client, secret):
        groups = auth_client.get("/api/search/", {"q": "Hidden"}).json()[
            "groups"
        ]

        assert not any(group["label"] == "Wiki" for group in groups)

    def test_nor_written_into(self, admin_client, secret):
        response = post(
            admin_client, PAGES, {"title": "In", "wiki": secret.wiki_id}
        )

        assert response.status_code == 400

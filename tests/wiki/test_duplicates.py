"""Pages and wikis copied into new ones (generic.wiki.duplicates)."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from generic.wiki.duplicates import wiki_duplicated
from generic.wiki.models import Wiki, WikiPage
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

WIKIS = "/wiki/api/wikis/"
PAGES = "/wiki/api/pages/"


def post(client, url: str, data: dict):
    return client.post(url, data, content_type="application/json")


def writer(*codenames: str):
    user = UserFactory()
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="generic_wiki", codename__in=codenames
        )
    )

    return user


@pytest.fixture
def handbook() -> dict:
    """A wiki of four pages: a chapter, two sections under it, one of
    them with a subsection."""
    wiki = Wiki.objects.create(name="Handbook", slug="handbook", position=3)
    chapter = WikiPage.objects.create(
        wiki=wiki,
        title="Onboarding",
        slug="onboarding",
        content="<p>Welcome aboard.</p>",
        show_on_dashboard=True,
        position=1,
    )
    tools = WikiPage.objects.create(
        wiki=wiki, title="Tools", slug="tools", parent=chapter, position=1
    )
    laptop = WikiPage.objects.create(
        wiki=wiki, title="Laptop", slug="laptop", parent=tools, position=1
    )
    people = WikiPage.objects.create(
        wiki=wiki, title="People", slug="people", parent=chapter, position=2
    )

    return {
        "wiki": wiki,
        "chapter": chapter,
        "tools": tools,
        "laptop": laptop,
        "people": people,
    }


class TestAPage:
    def test_is_copied_beside_itself_under_a_new_title(
        self, admin_client, handbook
    ):
        tools = handbook["tools"]
        response = post(
            admin_client,
            f"{PAGES}{tools.pk}/duplicate/",
            {"title": "Tools for interns"},
        )

        assert response.status_code == 201, response.content
        copy = WikiPage.objects.get(pk=response.json()["id"])
        assert copy.title == "Tools for interns"
        assert copy.slug == "tools-for-interns"
        assert copy.parent == handbook["chapter"]
        assert copy.wiki == handbook["wiki"]
        assert copy.children.count() == 0
        assert response.json()["url"] == copy.get_absolute_url()

    def test_its_subpages_come_along_when_asked(self, admin_client, handbook):
        chapter = handbook["chapter"]
        response = post(
            admin_client,
            f"{PAGES}{chapter.pk}/duplicate/",
            {"title": "Onboarding 2027", "subpages": True},
        )

        copy = WikiPage.objects.get(pk=response.json()["id"])
        assert sorted(copy.children.values_list("title", flat=True)) == [
            "People",
            "Tools",
        ]
        tools = copy.children.get(title="Tools")
        assert list(tools.children.values_list("title", flat=True)) == [
            "Laptop"
        ]
        # New addresses: the originals keep theirs.
        assert tools.slug == "tools-2"
        assert WikiPage.objects.filter(wiki=handbook["wiki"]).count() == 8

    def test_the_text_is_copied_not_the_history_nor_the_pin(
        self, admin_client, handbook
    ):
        chapter = handbook["chapter"]
        chapter.revisions.create(title="Old", content="<p>Old.</p>")
        response = post(
            admin_client,
            f"{PAGES}{chapter.pk}/duplicate/",
            {"title": "Onboarding, again"},
        )

        copy = WikiPage.objects.get(pk=response.json()["id"])
        assert copy.content == "<p>Welcome aboard.</p>"
        assert copy.revisions.count() == 0
        assert copy.show_on_dashboard is False

    def test_a_title_is_required(self, admin_client, handbook):
        response = post(
            admin_client, f"{PAGES}{handbook['tools'].pk}/duplicate/", {}
        )

        assert response.status_code == 400
        assert "title" in response.json()

    def test_needs_the_add_permission(self, client, handbook):
        client.force_login(writer("change_wikipage"))
        response = post(
            client,
            f"{PAGES}{handbook['tools'].pk}/duplicate/",
            {"title": "Copy"},
        )

        assert response.status_code == 403
        assert not WikiPage.objects.filter(title="Copy").exists()

    def test_needs_a_wiki_the_user_writes_in(self, client, handbook, settings):
        settings.GENERIC = {
            **settings.GENERIC,
            "WIKI_EDIT_ACCESS": lambda user, wikis: wikis.exclude(
                slug="handbook"
            ),
        }
        client.force_login(writer("add_wikipage"))
        response = post(
            client,
            f"{PAGES}{handbook['tools'].pk}/duplicate/",
            {"title": "Copy"},
        )

        assert response.status_code == 403

    def test_the_page_offers_it(self, admin_client, handbook):
        response = admin_client.get(handbook["chapter"].get_absolute_url())

        assert response.context["wiki_config"]["subpages"] == 3
        assert b"duplicate()" in response.content


class TestAWiki:
    def test_is_copied_with_its_pages_and_their_tree(
        self, admin_client, handbook
    ):
        source = handbook["wiki"]
        response = post(
            admin_client,
            f"{WIKIS}{source.pk}/duplicate/",
            {"name": "Handbook 2027", "description": "Next year's."},
        )

        assert response.status_code == 201, response.content
        copy = Wiki.objects.get(pk=response.json()["id"])
        assert copy.name == "Handbook 2027"
        assert copy.slug == "handbook-2027"
        assert copy.description == "Next year's."
        assert copy.position == source.position
        pages = {page.title: page for page in copy.pages.all()}
        assert set(pages) == {"Onboarding", "Tools", "Laptop", "People"}
        assert pages["Onboarding"].parent is None
        assert pages["Tools"].parent == pages["Onboarding"]
        assert pages["Laptop"].parent == pages["Tools"]
        # Within its own wiki, a page keeps its address.
        assert pages["Laptop"].slug == "laptop"
        assert source.pages.count() == 4

    def test_without_its_pages_when_asked(self, admin_client, handbook):
        response = post(
            admin_client,
            f"{WIKIS}{handbook['wiki'].pk}/duplicate/",
            {"name": "Empty handbook", "pages": False},
        )

        assert response.status_code == 201
        assert not Wiki.objects.get(name="Empty handbook").pages.exists()

    def test_needs_the_wiki_add_permission(self, client, handbook):
        client.force_login(writer("add_wikipage"))
        response = post(
            client,
            f"{WIKIS}{handbook['wiki'].pk}/duplicate/",
            {"name": "Copy"},
        )

        assert response.status_code == 403

    def test_its_pages_need_the_page_add_permission(self, client, handbook):
        client.force_login(writer("add_wiki"))
        refused = post(
            client, f"{WIKIS}{handbook['wiki'].pk}/duplicate/", {"name": "A"}
        )
        empty = post(
            client,
            f"{WIKIS}{handbook['wiki'].pk}/duplicate/",
            {"name": "B", "pages": False},
        )

        assert refused.status_code == 403
        assert empty.status_code == 201
        assert not Wiki.objects.filter(name="A").exists()

    def test_tells_the_project_in_the_copy_s_transaction(
        self, admin_client, handbook
    ):
        heard = []

        def listener(sender, source, copy, user, **kwargs):
            heard.append((source.slug, copy.slug, user.username))

        wiki_duplicated.connect(listener)

        try:
            post(
                admin_client,
                f"{WIKIS}{handbook['wiki'].pk}/duplicate/",
                {"name": "Heard"},
            )
        finally:
            wiki_duplicated.disconnect(listener)

        assert heard == [("handbook", "heard", "admin")]

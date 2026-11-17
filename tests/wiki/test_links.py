"""A renamed page keeps its old address; a page says who links to it."""

from __future__ import annotations

import pytest

from generic.wiki.models import Wiki, WikiPage, WikiRedirect
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PAGES = "/wiki/api/pages/"


def send(client, method: str, url: str, data=None):
    return getattr(client, method)(url, data, content_type="application/json")


@pytest.fixture
def main():
    return Wiki.objects.get(slug="main")


class TestRedirects:
    def test_a_renamed_page_keeps_its_old_address(self, admin_client, main):
        page = WikiPage.objects.create(wiki=main, title="Old", slug="old")

        send(admin_client, "patch", f"{PAGES}{page.pk}/", {"slug": "new"})
        response = admin_client.get("/wiki/main/old/")

        assert response.status_code == 301
        assert response["Location"] == "/wiki/main/new/"

    def test_renamed_twice_both_lead_to_it(self, admin_client, main):
        page = WikiPage.objects.create(wiki=main, title="A", slug="a")

        send(admin_client, "patch", f"{PAGES}{page.pk}/", {"slug": "b"})
        send(admin_client, "patch", f"{PAGES}{page.pk}/", {"slug": "c"})

        assert admin_client.get("/wiki/main/a/")["Location"] == "/wiki/main/c/"
        assert admin_client.get("/wiki/main/b/")["Location"] == "/wiki/main/c/"

    def test_back_to_an_old_address_drops_its_redirect(
        self, admin_client, main
    ):
        page = WikiPage.objects.create(wiki=main, title="A", slug="a")

        send(admin_client, "patch", f"{PAGES}{page.pk}/", {"slug": "b"})
        send(admin_client, "patch", f"{PAGES}{page.pk}/", {"slug": "a"})

        assert admin_client.get("/wiki/main/a/").status_code == 200
        assert list(WikiRedirect.objects.values_list("slug", flat=True)) == [
            "b"
        ]

    def test_a_page_at_the_old_address_wins(self, admin_client, main):
        page = WikiPage.objects.create(wiki=main, title="A", slug="a")
        send(admin_client, "patch", f"{PAGES}{page.pk}/", {"slug": "b"})

        WikiPage.objects.create(wiki=main, title="Another A", slug="a")

        assert admin_client.get("/wiki/main/a/").status_code == 200

    def test_a_page_in_the_trash_is_not_reached(self, admin_client, main):
        page = WikiPage.objects.create(wiki=main, title="A", slug="a")
        send(admin_client, "patch", f"{PAGES}{page.pk}/", {"slug": "b"})
        send(admin_client, "delete", f"{PAGES}{page.pk}/")

        assert admin_client.get("/wiki/main/a/").status_code == 404

    def test_another_wiki_s_old_address_is_not_followed(
        self, admin_client, main
    ):
        other = Wiki.objects.create(name="Other", slug="other")
        page = WikiPage.objects.create(wiki=other, title="A", slug="a")
        send(admin_client, "patch", f"{PAGES}{page.pk}/", {"slug": "b"})

        assert admin_client.get("/wiki/main/a/").status_code == 404


class TestBacklinks:
    def test_a_page_lists_who_links_to_it(self, admin_client, main):
        target = WikiPage.objects.create(wiki=main, title="Target", slug="t")
        WikiPage.objects.create(
            wiki=main,
            title="Linking",
            slug="l",
            content='<p><a href="/wiki/main/t/#h-steps">see</a></p>',
        )
        WikiPage.objects.create(
            wiki=main,
            title="Prefix only",
            slug="p",
            content='<p><a href="/wiki/main/tea/">no</a></p>',
        )

        response = admin_client.get("/wiki/main/t/")

        assert [page.title for page in response.context["backlinks"]] == [
            "Linking"
        ]
        assert target not in response.context["backlinks"]

    def test_a_wiki_not_read_is_not_named(self, client, main):
        WikiPage.objects.create(wiki=main, title="Target", slug="t")
        secret = Wiki.objects.create(name="S", slug="s", access="private")
        WikiPage.objects.create(
            wiki=secret,
            title="Hidden",
            slug="h",
            content='<p><a href="/wiki/main/t/">x</a></p>',
        )
        client.force_login(UserFactory())

        assert client.get("/wiki/main/t/").context["backlinks"] == []

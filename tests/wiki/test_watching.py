"""Watching a page or a wiki, and the pages written lately."""

from __future__ import annotations

import pytest

from generic.events.models import Notification
from generic.wiki.models import Wiki, WikiMember, WikiPage
from generic.wiki.watching import is_watching
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

WIKIS = "/wiki/api/wikis/"
PAGES = "/wiki/api/pages/"


def send(client, method: str, url: str, data=None):
    return getattr(client, method)(url, data, content_type="application/json")


@pytest.fixture
def page():
    return WikiPage.objects.create(
        wiki=Wiki.objects.get(slug="main"),
        title="Rules",
        slug="rules",
        content="<p>One</p>",
    )


def told(user) -> list[str]:
    return list(
        Notification.objects.filter(user=user).values_list("title", flat=True)
    )


class TestTheButton:
    def test_a_reader_watches_a_page_and_stops(self, client, page):
        reader = UserFactory()
        client.force_login(reader)
        url = f"{PAGES}{page.pk}/watch/"

        assert send(client, "get", url).json() == {"watching": False}
        assert send(client, "post", url).json() == {"watching": True}
        assert is_watching(reader, page)
        assert send(client, "post", url).json() == {"watching": False}
        assert not is_watching(reader, page)

    def test_a_reader_watches_a_wiki(self, client, page):
        reader = UserFactory()
        client.force_login(reader)

        response = send(client, "post", f"{WIKIS}{page.wiki_id}/watch/")

        assert response.json() == {"watching": True}
        assert is_watching(reader, page.wiki)

    def test_a_wiki_not_read_is_not_found(self, client):
        secret = Wiki.objects.create(name="S", slug="s", access="private")
        client.force_login(UserFactory())

        assert (
            send(client, "post", f"{WIKIS}{secret.pk}/watch/").status_code
            == 404
        )

    def test_the_page_draws_it(self, client, page):
        reader = UserFactory()
        client.force_login(reader)
        send(client, "post", f"{PAGES}{page.pk}/watch/")

        config = client.get("/wiki/main/rules/").context["wiki_config"]

        assert config["watching"] == {"page": True, "wiki": False}

    def test_the_watching_page_links_to_it(self, client, page):
        reader = UserFactory()
        client.force_login(reader)
        send(client, "post", f"{PAGES}{page.pk}/watch/")

        rows = client.get("/api/generic/watches/").json()

        assert rows[0]["url"] == "/wiki/main/rules/"
        assert rows[0]["label"] == "Rules"


class TestTelling:
    def change(self, client, page, text="<p>Two</p>"):
        return send(client, "patch", f"{PAGES}{page.pk}/", {"content": text})

    def test_a_watcher_of_the_page_is_told_of_a_change(
        self, admin_client, page, django_capture_on_commit_callbacks
    ):
        reader = UserFactory()
        send_as(reader, "post", f"{PAGES}{page.pk}/watch/")

        with django_capture_on_commit_callbacks(execute=True):
            self.change(admin_client, page)

        assert told(reader) == ["admin changed “Rules” in Wiki."]

    def test_a_watcher_of_the_wiki_hears_of_a_new_page(
        self, admin_client, page, django_capture_on_commit_callbacks
    ):
        reader = UserFactory()
        send_as(reader, "post", f"{WIKIS}{page.wiki_id}/watch/")

        with django_capture_on_commit_callbacks(execute=True):
            send(
                admin_client,
                "post",
                PAGES,
                {"title": "New", "wiki": page.wiki_id},
            )
            send(admin_client, "delete", f"{PAGES}{page.pk}/")

        assert told(reader) == [
            "admin deleted “Rules” from Wiki.",
            "admin wrote “New” in Wiki.",
        ]

    def test_nobody_hears_of_their_own_change(
        self,
        admin_client,
        admin_user,
        page,
        django_capture_on_commit_callbacks,
    ):
        send(admin_client, "post", f"{PAGES}{page.pk}/watch/")

        with django_capture_on_commit_callbacks(execute=True):
            self.change(admin_client, page)

        assert told(admin_user) == []

    def test_moving_a_page_is_not_news(
        self, admin_client, page, django_capture_on_commit_callbacks
    ):
        reader = UserFactory()
        send_as(reader, "post", f"{PAGES}{page.pk}/watch/")

        with django_capture_on_commit_callbacks(execute=True):
            send(admin_client, "patch", f"{PAGES}{page.pk}/", {"position": 4})

        assert told(reader) == []

    def test_whoever_no_longer_reads_the_wiki_is_not_told(
        self, admin_client, page, django_capture_on_commit_callbacks
    ):
        reader = UserFactory()
        send_as(reader, "post", f"{PAGES}{page.pk}/watch/")
        Wiki.objects.filter(pk=page.wiki_id).update(access="private")

        with django_capture_on_commit_callbacks(execute=True):
            self.change(admin_client, page)

        assert told(reader) == []

        WikiMember.objects.create(wiki=page.wiki, user=reader)

        with django_capture_on_commit_callbacks(execute=True):
            self.change(admin_client, page, "<p>Three</p>")

        assert len(told(reader)) == 1


def send_as(user, method: str, url: str):
    from django.test import Client

    client = Client()
    client.force_login(user)

    return send(client, method, url)


class TestRecent:
    def test_the_last_written_come_first(self, admin_client, page):
        other = WikiPage.objects.create(
            wiki=page.wiki, title="Later", slug="later"
        )

        rows = send(
            admin_client, "get", f"{PAGES}recent/?wiki={page.wiki_id}"
        ).json()

        assert [row["title"] for row in rows][:2] == [other.title, "Rules"]
        assert rows[0]["url"] == "/wiki/main/later/"

    def test_a_wiki_not_read_is_left_out(self, client, page):
        secret = Wiki.objects.create(name="S", slug="s", access="private")
        WikiPage.objects.create(wiki=secret, title="Hidden", slug="h")
        client.force_login(UserFactory())

        rows = send(client, "get", f"{PAGES}recent/").json()

        assert "Hidden" not in [row["title"] for row in rows]
        assert (
            send(client, "get", f"{PAGES}recent/?wiki={secret.pk}").status_code
            == 404
        )

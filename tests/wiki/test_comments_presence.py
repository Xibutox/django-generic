"""Comments on a page; who else is editing it."""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.cache import cache

from generic.wiki import presence
from generic.wiki.models import Wiki, WikiComment, WikiMember, WikiPage
from generic.wiki.watching import toggle
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PAGES = "/wiki/api/pages/"


def send(client, method: str, url: str, data=None):
    return getattr(client, method)(url, data, content_type="application/json")


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def wiki():
    return Wiki.objects.create(name="Team", slug="team", access="protected")


@pytest.fixture
def page(wiki):
    return WikiPage.objects.create(wiki=wiki, title="Plan", slug="plan")


@pytest.fixture
def reader(wiki):
    return UserFactory()


class TestComments:
    def test_a_reader_comments(self, client, page, reader):
        client.force_login(reader)

        response = send(
            client, "post", f"{PAGES}{page.pk}/comments/", {"body": " Hi "}
        )

        assert response.status_code == 201
        assert response.json()["body"] == "Hi"
        assert response.json()["mine"] is True
        assert WikiComment.objects.get().author == reader

    def test_listed_oldest_first(self, client, page, reader):
        client.force_login(reader)
        for body in ("one", "two"):
            send(client, "post", f"{PAGES}{page.pk}/comments/", {"body": body})

        rows = client.get(f"{PAGES}{page.pk}/comments/").json()

        assert [row["body"] for row in rows] == ["one", "two"]

    def test_empty_is_refused(self, client, page, reader):
        client.force_login(reader)

        response = send(
            client, "post", f"{PAGES}{page.pk}/comments/", {"body": "  "}
        )

        assert response.status_code == 400

    def test_too_long_is_refused(self, client, page, reader):
        client.force_login(reader)

        response = send(
            client,
            "post",
            f"{PAGES}{page.pk}/comments/",
            {"body": "x" * 5001},
        )

        assert response.status_code == 400

    def test_not_on_a_page_one_cannot_read(self, client, page, wiki):
        wiki.access = "private"
        wiki.save()
        client.force_login(UserFactory())

        response = send(
            client, "post", f"{PAGES}{page.pk}/comments/", {"body": "x"}
        )

        assert response.status_code == 404

    def test_its_author_takes_it_away(self, client, page, reader):
        comment = WikiComment.objects.create(
            page=page, author=reader, body="x"
        )
        client.force_login(reader)

        response = send(
            client,
            "post",
            f"{PAGES}{page.pk}/uncomment/",
            {"comment": comment.pk},
        )

        assert response.status_code == 204
        assert not WikiComment.objects.exists()

    def test_not_somebody_else(self, client, page, reader):
        comment = WikiComment.objects.create(
            page=page, author=UserFactory(), body="x"
        )
        client.force_login(reader)

        response = send(
            client,
            "post",
            f"{PAGES}{page.pk}/uncomment/",
            {"comment": comment.pk},
        )

        assert response.status_code == 403
        assert (
            client.get(f"{PAGES}{page.pk}/comments/").json()[0]["can_delete"]
            is False
        )

    def test_the_wiki_s_manager_does(self, client, page, wiki):
        manager = UserFactory()
        WikiMember.objects.create(wiki=wiki, user=manager, role="manager")
        comment = WikiComment.objects.create(
            page=page, author=UserFactory(), body="x"
        )
        client.force_login(manager)

        response = send(
            client,
            "post",
            f"{PAGES}{page.pk}/uncomment/",
            {"comment": comment.pk},
        )

        assert response.status_code == 204

    def test_the_page_s_watchers_are_told(
        self, client, page, reader, django_capture_on_commit_callbacks
    ):
        watcher = UserFactory()
        toggle(watcher, page)
        client.force_login(reader)

        with mock.patch("generic.wiki.watching.delivery.deliver") as deliver:
            with django_capture_on_commit_callbacks(execute=True):
                send(
                    client,
                    "post",
                    f"{PAGES}{page.pk}/comments/",
                    {"body": "x"},
                )

        assert deliver.call_count == 1
        assert deliver.call_args.args[0] == [watcher]
        title = deliver.call_args.kwargs["message"]()[0]
        assert "commented on" in title

    def test_the_wiki_s_watchers_are_not(
        self, client, page, wiki, reader, django_capture_on_commit_callbacks
    ):
        toggle(UserFactory(), wiki)
        client.force_login(reader)

        with mock.patch("generic.wiki.watching.delivery.deliver") as deliver:
            with django_capture_on_commit_callbacks(execute=True):
                send(
                    client,
                    "post",
                    f"{PAGES}{page.pk}/comments/",
                    {"body": "x"},
                )

        assert deliver.call_count == 0


class TestEditing:
    def test_the_others_are_named(self, client, admin_user, page):
        other = UserFactory(first_name="Bea", last_name="Writer")
        presence.beat(page, other)
        client.force_login(admin_user)

        response = send(client, "post", f"{PAGES}{page.pk}/editing/", {})

        assert [row["id"] for row in response.json()["editors"]] == [other.pk]

    def test_not_oneself(self, admin_client, page):
        response = send(admin_client, "post", f"{PAGES}{page.pk}/editing/")

        assert response.json() == {"editors": []}

    def test_closed_the_editor_is_no_longer_named(
        self, admin_client, admin_user, page
    ):
        send(admin_client, "post", f"{PAGES}{page.pk}/editing/", {})
        send(
            admin_client,
            "post",
            f"{PAGES}{page.pk}/editing/",
            {"active": False},
        )

        assert presence.editors(page) == []

    def test_gone_quiet_is_no_longer_named(self, admin_user, page):
        presence.beat(page, admin_user)

        with mock.patch(
            "generic.wiki.presence.time.time",
            return_value=10**10,
        ):
            assert presence.editors(page) == []

    def test_only_who_may_change_the_page(self, client, page, reader):
        client.force_login(reader)

        response = send(client, "post", f"{PAGES}{page.pk}/editing/", {})

        assert response.status_code == 403

    def test_readers_are_told(self, admin_user, page):
        with mock.patch("generic.events.bus.publish_to_topic") as publish:
            presence.beat(page, admin_user)
            presence.beat(page, admin_user)

        assert publish.call_count == 1
        assert publish.call_args.args[:2] == (presence.TOPIC, "wiki.editing")
        assert publish.call_args.kwargs["parameters"] == {
            "page_id": str(page.pk)
        }

    def test_the_page_says_who_edits_it(self, admin_client, page):
        other = UserFactory()
        presence.beat(page, other)

        config = admin_client.get("/wiki/team/plan/").context["wiki_config"]

        assert [row["id"] for row in config["editors"]] == [other.pk]
        assert config["topic"] == f"wiki.page.{page.pk}"

    def test_the_topic_is_for_its_readers(self, page, wiki, reader):
        assert presence.may_follow(
            reader, presence.TOPIC, {"page_id": str(page.pk)}
        )

        wiki.access = "private"
        wiki.save()

        assert not presence.may_follow(
            reader, presence.TOPIC, {"page_id": str(page.pk)}
        )

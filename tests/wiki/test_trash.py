"""Deleted pages and wikis wait in a trash: restored whole, or deleted
for good."""

from __future__ import annotations

import datetime
from io import StringIO

import pytest
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.utils import timezone

from generic.wiki.models import Wiki, WikiImage, WikiPage, WikiRevision
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

WIKIS = "/wiki/api/wikis/"
PAGES = "/wiki/api/pages/"


def writer(*codenames: str):
    user = UserFactory()
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="generic_wiki", codename__in=codenames
        )
    )

    return user


def send(client, method: str, url: str, data=None):
    return getattr(client, method)(url, data, content_type="application/json")


@pytest.fixture
def tree():
    wiki = Wiki.objects.default()
    top = WikiPage.objects.create(wiki=wiki, title="Top", slug="top")
    middle = WikiPage.objects.create(
        wiki=wiki, title="Middle", slug="middle", parent=top
    )
    leaf = WikiPage.objects.create(
        wiki=wiki, title="Leaf", slug="leaf", parent=middle
    )
    WikiRevision.objects.create(
        page=middle, title="Middle", content="<p>1</p>"
    )

    return {"wiki": wiki, "top": top, "middle": middle, "leaf": leaf}


class TestPages:
    def test_a_deleted_page_goes_to_the_trash(self, admin_client, tree):
        response = send(admin_client, "delete", f"{PAGES}{tree['middle'].pk}/")

        assert response.status_code == 204
        assert not WikiPage.objects.filter(slug="middle").exists()
        trashed = WikiPage.all_objects.get(slug="middle")
        assert trashed.deleted_at is not None
        assert trashed.deleted_by.username == "admin"
        # Its history waits with it.
        assert trashed.revisions.count() == 1

    def test_its_subpages_move_up_a_level(self, admin_client, tree):
        send(admin_client, "delete", f"{PAGES}{tree['middle'].pk}/")

        tree["leaf"].refresh_from_db()
        assert tree["leaf"].parent == tree["top"]

    def test_it_is_gone_from_every_screen(self, admin_client, tree):
        send(admin_client, "delete", f"{PAGES}{tree['middle'].pk}/")

        assert admin_client.get("/wiki/main/middle/").status_code == 404
        assert (
            send(
                admin_client, "get", f"{PAGES}{tree['middle'].pk}/"
            ).status_code
            == 404
        )
        assert "middle" not in [
            row["slug"] for row in send(admin_client, "get", PAGES).json()
        ]
        assert admin_client.get("/wiki/").context["wikis"][0].page_count == 2

    def test_the_trash_lists_it(self, admin_client, tree):
        send(admin_client, "delete", f"{PAGES}{tree['middle'].pk}/")

        rows = send(
            admin_client, "get", f"{PAGES}trash/?wiki={tree['wiki'].pk}"
        ).json()

        assert [row["title"] for row in rows] == ["Middle"]
        assert rows[0]["deleted_by_name"] == "admin"

    def test_the_trash_is_for_whoever_may_delete(self, client, tree):
        client.force_login(writer("add_wikipage", "change_wikipage"))
        url = f"{PAGES}trash/?wiki={tree['wiki'].pk}"

        assert send(client, "get", url).status_code == 403
        assert send(client, "get", f"{PAGES}trash/").status_code == 403
        assert send(client, "get", f"{PAGES}trash/?wiki=x").status_code == 403

    def test_it_comes_back_where_it_was(self, admin_client, tree):
        send(admin_client, "delete", f"{PAGES}{tree['middle'].pk}/")

        response = send(
            admin_client, "post", f"{PAGES}{tree['middle'].pk}/undelete/"
        )

        page = WikiPage.objects.get(slug="middle")
        assert response.status_code == 200
        assert response.json()["url"] == "/wiki/main/middle/"
        assert page.parent == tree["top"]
        assert page.deleted_at is None
        assert page.revisions.count() == 1

    def test_it_comes_back_at_the_top_when_its_parent_is_gone(
        self, admin_client, tree
    ):
        send(admin_client, "delete", f"{PAGES}{tree['middle'].pk}/")
        send(admin_client, "delete", f"{PAGES}{tree['top'].pk}/")

        send(admin_client, "post", f"{PAGES}{tree['middle'].pk}/undelete/")

        assert WikiPage.objects.get(slug="middle").parent is None

    def test_purging_deletes_it_for_good(self, admin_client, tree):
        send(admin_client, "delete", f"{PAGES}{tree['middle'].pk}/")

        response = send(
            admin_client, "post", f"{PAGES}{tree['middle'].pk}/purge/"
        )

        assert response.status_code == 204
        assert not WikiPage.all_objects.filter(slug="middle").exists()
        assert not WikiRevision.objects.exists()

    def test_a_live_page_is_neither_restored_nor_purged(
        self, admin_client, tree
    ):
        url = f"{PAGES}{tree['top'].pk}/"

        assert send(admin_client, "post", url + "undelete/").status_code == 404
        assert send(admin_client, "post", url + "purge/").status_code == 404
        assert WikiPage.objects.filter(slug="top").exists()

    def test_restoring_and_purging_need_the_right_to_delete(
        self, admin_client, client, tree
    ):
        send(admin_client, "delete", f"{PAGES}{tree['middle'].pk}/")
        client.force_login(writer("add_wikipage", "change_wikipage"))
        url = f"{PAGES}{tree['middle'].pk}/"

        assert send(client, "post", url + "undelete/").status_code == 403
        assert send(client, "post", url + "purge/").status_code == 403

    def test_its_address_stays_taken(self, admin_client, tree):
        send(admin_client, "delete", f"{PAGES}{tree['middle'].pk}/")

        again = send(
            admin_client,
            "post",
            PAGES,
            {"title": "Middle", "wiki": tree["wiki"].pk},
        )
        taken = send(
            admin_client,
            "post",
            PAGES,
            {"title": "Other", "slug": "middle", "wiki": tree["wiki"].pk},
        )

        assert again.json()["slug"] == "middle-2"
        assert taken.status_code == 400


class TestWikis:
    @pytest.fixture
    def quality(self):
        wiki = Wiki.objects.create(name="Quality", slug="quality", position=1)
        WikiPage.objects.create(wiki=wiki, title="Rules", slug="rules")

        return wiki

    def test_a_deleted_wiki_waits_with_its_pages(self, admin_client, quality):
        response = send(admin_client, "delete", f"{WIKIS}{quality.pk}/")

        assert response.status_code == 204
        assert not Wiki.objects.filter(slug="quality").exists()
        assert admin_client.get("/wiki/quality/rules/").status_code == 404
        assert Wiki.all_objects.get(slug="quality").pages.count() == 1

    def test_the_trash_lists_it_to_whoever_may_delete_it(
        self, admin_client, client, quality
    ):
        send(admin_client, "delete", f"{WIKIS}{quality.pk}/")
        client.force_login(writer("add_wiki", "change_wiki"))

        rows = send(admin_client, "get", f"{WIKIS}trash/").json()

        assert [row["name"] for row in rows] == ["Quality"]
        assert rows[0]["page_count"] == 1
        assert rows[0]["deleted_by_name"] == "admin"
        assert send(client, "get", f"{WIKIS}trash/").json() == []
        assert admin_client.get("/wiki/").context["trash_count"] == 1
        assert client.get("/wiki/").context["trash_count"] == 0

    def test_it_comes_back_whole(self, admin_client, quality):
        send(admin_client, "delete", f"{WIKIS}{quality.pk}/")

        response = send(admin_client, "post", f"{WIKIS}{quality.pk}/undelete/")

        assert response.status_code == 200
        assert admin_client.get("/wiki/quality/rules/").status_code == 200

    def test_purging_deletes_it_with_its_pages(self, admin_client, quality):
        send(admin_client, "delete", f"{WIKIS}{quality.pk}/")

        response = send(admin_client, "post", f"{WIKIS}{quality.pk}/purge/")

        assert response.status_code == 204
        assert not Wiki.all_objects.filter(slug="quality").exists()
        assert not WikiPage.all_objects.filter(slug="rules").exists()

    def test_restoring_and_purging_need_the_right_to_delete(
        self, admin_client, client, quality
    ):
        send(admin_client, "delete", f"{WIKIS}{quality.pk}/")
        client.force_login(writer("add_wiki", "change_wiki"))
        url = f"{WIKIS}{quality.pk}/"

        assert send(client, "post", url + "undelete/").status_code == 403
        assert send(client, "post", url + "purge/").status_code == 403

    def test_its_address_stays_taken(self, admin_client, quality):
        send(admin_client, "delete", f"{WIKIS}{quality.pk}/")

        again = send(admin_client, "post", WIKIS, {"name": "Quality"})
        taken = send(
            admin_client, "post", WIKIS, {"name": "Other", "slug": "quality"}
        )

        assert again.json()["slug"] == "quality-2"
        assert taken.status_code == 400

    def test_the_first_wiki_is_made_again_beside_one_in_the_trash(
        self, admin_client
    ):
        send(admin_client, "delete", f"{WIKIS}{Wiki.objects.default().pk}/")

        assert Wiki.objects.default().slug == "main-2"


class TestCleanup:
    def old(self, record, days: int) -> None:
        type(record).all_objects.filter(pk=record.pk).update(
            deleted_at=timezone.now() - datetime.timedelta(days=days)
        )

    def run(self, *args: str) -> str:
        out = StringIO()
        call_command("wiki_cleanup", *args, stdout=out)

        return out.getvalue()

    def test_the_trash_is_emptied_after_its_days(self, tree, settings):
        settings.GENERIC = {"TRASH_DAYS": 30}
        tree["leaf"].deleted_at = timezone.now()
        tree["leaf"].save()
        tree["middle"].deleted_at = timezone.now()
        tree["middle"].save()
        self.old(tree["middle"], 31)
        self.old(tree["leaf"], 29)

        self.run()

        assert not WikiPage.all_objects.filter(slug="middle").exists()
        assert WikiPage.all_objects.filter(slug="leaf").exists()

    def test_a_wiki_too(self, tree):
        wiki = Wiki.objects.create(name="Old", slug="old")
        wiki.deleted_at = timezone.now()
        wiki.save()
        self.old(wiki, 40)

        self.run("--days", "35")

        assert not Wiki.all_objects.filter(slug="old").exists()

    def test_a_dry_run_deletes_nothing(self, tree):
        tree["leaf"].deleted_at = timezone.now()
        tree["leaf"].save()
        self.old(tree["leaf"], 90)

        output = self.run("--dry-run")

        assert WikiPage.all_objects.filter(slug="leaf").exists()
        assert "1" in output

    def test_uploads_no_page_shows_are_deleted(self, tree, settings, tmp_path):
        from django.core.files.base import ContentFile

        settings.MEDIA_ROOT = str(tmp_path)
        long_ago = timezone.now() - datetime.timedelta(days=60)

        def image(name: str, when=long_ago) -> WikiImage:
            upload = WikiImage(original_name=name, uploaded_at=when)
            upload.file.save(name, ContentFile(b"x"), save=False)
            upload.save()

            return upload

        shown = image("shown.png")
        was_shown = image("was.png")
        orphan = image("orphan.png")
        recent = image("recent.png", timezone.now())
        tree["top"].content = f'<p><img src="{shown.get_absolute_url()}"></p>'
        tree["top"].save()
        WikiRevision.objects.create(
            page=tree["top"],
            title="Top",
            content=f'<p><img src="{was_shown.get_absolute_url()}"></p>',
        )
        stored = orphan.file.path

        self.run("--uploads")

        assert set(WikiImage.objects.values_list("pk", flat=True)) == {
            shown.pk,
            was_shown.pk,
            recent.pk,
        }
        assert not __import__("os").path.exists(stored)

    def test_uploads_are_left_alone_unless_asked(self, tree, tmp_path):
        WikiImage.objects.create(
            original_name="orphan.png",
            uploaded_at=timezone.now() - datetime.timedelta(days=60),
        )

        self.run()

        assert WikiImage.objects.count() == 1

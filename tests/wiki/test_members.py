"""A wiki's access, owner and members: who reads it, who writes its
pages, who manages it - and what its images and files follow."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile

from generic.wiki.access import page_rights, role_in, wiki_rights
from generic.wiki.models import (
    ACCESS_PRIVATE,
    ACCESS_PROTECTED,
    Wiki,
    WikiFile,
    WikiImage,
    WikiMember,
    WikiPage,
)
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

WIKIS = "/wiki/api/wikis/"
PAGES = "/wiki/api/pages/"
IMAGES = "/api/generic/wiki/images/"
FILES = "/api/generic/wiki/files/"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


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
def people():
    """An owner, an editor, a manager, a reader through a group, and
    someone who holds every page permission but is nobody's member."""
    owner = UserFactory()
    editor = UserFactory()
    manager = UserFactory()
    reader = UserFactory()
    readers = Group.objects.create(name="Readers")
    reader.groups.add(readers)

    return {
        "owner": owner,
        "editor": editor,
        "manager": manager,
        "reader": reader,
        "readers": readers,
        "outsider": writer(
            "add_wikipage", "change_wikipage", "delete_wikipage"
        ),
    }


def make(people, access: str) -> Wiki:
    wiki = Wiki.objects.create(
        name=access.title(),
        slug=access,
        access=access,
        owner=people["owner"],
    )
    WikiMember.objects.create(wiki=wiki, user=people["editor"], role="editor")
    WikiMember.objects.create(
        wiki=wiki, user=people["manager"], role="manager"
    )
    WikiMember.objects.create(
        wiki=wiki, group=people["readers"], role="reader"
    )
    WikiPage.objects.create(wiki=wiki, title="Home", slug="home")

    return wiki


@pytest.fixture
def private(people) -> Wiki:
    return make(people, ACCESS_PRIVATE)


@pytest.fixture
def protected(people) -> Wiki:
    return make(people, ACCESS_PROTECTED)


class TestReading:
    def test_a_private_wiki_is_its_members_and_owner_s(self, people, private):
        def reads(name: str) -> bool:
            return private in Wiki.objects.readable_by(people[name])

        assert reads("owner")
        assert reads("editor")
        assert reads("manager")
        # Through a group.
        assert reads("reader")
        assert not reads("outsider")

    def test_a_superuser_reads_every_wiki(self, admin_user, private):
        assert private in Wiki.objects.readable_by(admin_user)

    def test_a_protected_wiki_is_read_by_everyone(self, people, protected):
        assert protected in Wiki.objects.readable_by(people["outsider"])

    def test_a_hidden_wiki_s_page_is_not_found(self, client, people, private):
        client.force_login(people["outsider"])

        assert client.get("/wiki/private/home/").status_code == 404
        assert client.get("/wiki/private/export.pdf").status_code == 404
        assert send(client, "get", WIKIS).json() == [
            row
            for row in send(client, "get", WIKIS).json()
            if row["slug"] != "private"
        ]
        assert not any(
            row["wiki"] == private.pk
            for row in send(client, "get", PAGES).json()
        )

    def test_the_project_s_hook_still_narrows(self, settings, people, private):
        settings.GENERIC = {"WIKI_ACCESS": lambda user, wikis: wikis.none()}

        assert not Wiki.objects.readable_by(people["owner"]).exists()


class TestWriting:
    @pytest.mark.parametrize(
        "name, writes",
        [
            ("owner", True),
            ("editor", True),
            ("manager", True),
            ("reader", False),
            ("outsider", False),
        ],
    )
    def test_a_protected_wiki_is_written_by_its_editors(
        self, people, protected, name, writes
    ):
        rights = page_rights(people[name], protected)

        assert rights == dict.fromkeys(("add", "change", "delete"), writes)

    def test_an_editor_needs_no_page_permission(
        self, client, people, protected
    ):
        client.force_login(people["editor"])

        created = send(
            client, "post", PAGES, {"title": "New", "wiki": protected.pk}
        )

        assert created.status_code == 201
        assert (
            send(
                client,
                "patch",
                f"{PAGES}{created.json()['id']}/",
                {"content": "<p>Hi</p>"},
            ).status_code
            == 200
        )

    def test_the_page_permissions_do_not_write_in_a_protected_wiki(
        self, client, people, protected
    ):
        client.force_login(people["outsider"])
        page = protected.pages.get()

        assert (
            send(
                client, "post", PAGES, {"title": "New", "wiki": protected.pk}
            ).status_code
            == 403
        )
        assert (
            send(
                client, "patch", f"{PAGES}{page.pk}/", {"title": "Mine"}
            ).status_code
            == 403
        )
        assert send(client, "delete", f"{PAGES}{page.pk}/").status_code == 403
        assert not WikiPage.objects.filter(title="New").exists()

    def test_an_open_wiki_is_written_with_the_page_permissions(
        self, client, people
    ):
        wiki = Wiki.objects.get(slug="main")
        client.force_login(people["outsider"])

        assert (
            send(
                client, "post", PAGES, {"title": "New", "wiki": wiki.pk}
            ).status_code
            == 201
        )

    def test_someone_who_writes_nowhere_is_refused_outright(
        self, client, people
    ):
        client.force_login(people["reader"])

        assert send(client, "post", PAGES, {"title": "New"}).status_code == 403

    def test_the_page_draws_what_the_reader_may_do(
        self, client, people, protected
    ):
        client.force_login(people["outsider"])
        refused = client.get("/wiki/protected/home/").context["can"]
        client.force_login(people["editor"])
        allowed = client.get("/wiki/protected/home/").context["can"]

        assert not any(refused.values())
        assert all(allowed.values())

    def test_the_highest_role_wins(self, people, protected):
        # A reader through a group, an editor in their own name.
        WikiMember.objects.create(
            wiki=protected, user=people["reader"], role="editor"
        )

        assert role_in(people["reader"], protected) == "editor"


class TestTheWikiItself:
    def test_whoever_makes_a_wiki_owns_it(self, client):
        maker = writer("add_wiki")
        client.force_login(maker)

        response = send(client, "post", WIKIS, {"name": "Mine"})

        assert response.status_code == 201
        wiki = Wiki.objects.get(name="Mine")
        assert wiki.owner == maker
        assert response.json()["can"] == {
            "change": True,
            "members": True,
            "delete": True,
        }

    def test_a_manager_renames_it_but_only_its_owner_deletes_it(
        self, client, people, protected
    ):
        client.force_login(people["manager"])
        url = f"{WIKIS}{protected.pk}/"

        assert send(client, "patch", url, {"name": "Ours"}).status_code == 200
        assert send(client, "delete", url).status_code == 403

        client.force_login(people["owner"])

        assert send(client, "delete", url).status_code == 204

    def test_an_editor_does_not_change_the_wiki(
        self, client, people, protected
    ):
        client.force_login(people["editor"])

        assert (
            send(
                client, "patch", f"{WIKIS}{protected.pk}/", {"name": "X"}
            ).status_code
            == 403
        )
        assert wiki_rights(people["editor"], protected) == {
            "change": False,
            "members": False,
            "delete": False,
        }

    def test_the_wiki_permissions_still_manage_every_wiki_read(
        self, client, protected
    ):
        client.force_login(writer("change_wiki", "delete_wiki"))
        url = f"{WIKIS}{protected.pk}/"

        assert send(client, "patch", url, {"name": "Ours"}).status_code == 200
        assert send(client, "delete", url).status_code == 204

    def test_a_copy_keeps_its_access_and_members(
        self, admin_client, admin_user, people, private
    ):
        response = send(
            admin_client,
            "post",
            f"{WIKIS}{private.pk}/duplicate/",
            {"name": "Copy"},
        )

        copy = Wiki.objects.get(pk=response.json()["id"])
        assert copy.access == ACCESS_PRIVATE
        assert copy.owner == admin_user
        assert copy.members.count() == 3
        assert copy not in Wiki.objects.readable_by(people["outsider"])


class TestMembersEndpoint:
    def test_a_manager_reads_them(self, client, people, private):
        client.force_login(people["manager"])

        data = send(client, "get", f"{WIKIS}{private.pk}/members/").json()

        assert data["access"] == "private"
        assert data["owner"]["id"] == people["owner"].pk
        assert {(row["kind"], row["role"]) for row in data["members"]} == {
            ("user", "editor"),
            ("user", "manager"),
            ("group", "reader"),
        }
        assert data["can"] == {"owner": False}

    @pytest.mark.parametrize("name", ["editor", "reader"])
    def test_nobody_else_does(self, client, people, private, name):
        client.force_login(people[name])
        url = f"{WIKIS}{private.pk}/members/"

        assert send(client, "get", url).status_code == 403
        assert send(client, "put", url, {"members": []}).status_code == 403
        assert private.members.count() == 3

    def test_they_are_replaced_with_the_access(self, client, people, private):
        client.force_login(people["manager"])
        newcomer = UserFactory()

        response = send(
            client,
            "put",
            f"{WIKIS}{private.pk}/members/",
            {
                "access": "protected",
                "members": [
                    {"user": people["manager"].pk, "role": "manager"},
                    {"user": newcomer.pk, "role": "editor"},
                ],
            },
        )

        private.refresh_from_db()
        assert response.status_code == 200
        assert private.access == "protected"
        assert set(private.members.values_list("user", "role")) == {
            (people["manager"].pk, "manager"),
            (newcomer.pk, "editor"),
        }

    @pytest.mark.parametrize(
        "body",
        [
            {"access": "public"},
            {"members": "everyone"},
            {"members": [{"user": 1, "role": "admin"}]},
            {"members": [{"role": "editor"}]},
            {"members": [{"user": "x", "role": "editor"}]},
            {"members": [{"user": 987654, "role": "editor"}]},
            {"members": [{"group": 987654, "role": "editor"}]},
        ],
    )
    def test_what_is_not_valid_changes_nothing(
        self, client, people, private, body
    ):
        client.force_login(people["owner"])

        response = send(client, "put", f"{WIKIS}{private.pk}/members/", body)

        private.refresh_from_db()
        assert response.status_code == 400
        assert private.access == "private"
        assert private.members.count() == 3

    def test_only_its_owner_hands_it_over(self, client, people, private):
        url = f"{WIKIS}{private.pk}/members/"
        client.force_login(people["manager"])

        refused = send(client, "put", url, {"owner": people["manager"].pk})

        client.force_login(people["owner"])
        accepted = send(client, "put", url, {"owner": people["editor"].pk})

        private.refresh_from_db()
        assert refused.status_code == 403
        assert accepted.status_code == 200
        assert private.owner == people["editor"]

    def test_access_is_not_changed_by_a_plain_rename(
        self, client, people, private
    ):
        # ``change_wiki`` renames; who reads is the members' screen -
        # which that permission opens too, so an editor is the one
        # refused here.
        WikiMember.objects.filter(user=people["editor"]).update(role="editor")
        client.force_login(people["editor"])

        response = send(
            client, "patch", f"{WIKIS}{private.pk}/", {"access": "open"}
        )

        private.refresh_from_db()
        assert response.status_code == 403
        assert private.access == "private"

    def test_candidates_are_found_by_name(self, client, people, private):
        UserFactory(username="zelda", first_name="Zelda", last_name="Moreau")
        client.force_login(people["manager"])
        url = f"{WIKIS}{private.pk}/candidates/"

        found = send(client, "get", url + "?q=zel").json()
        groups = send(client, "get", url + "?q=reade").json()

        assert [row["detail"] for row in found] == ["zelda"]
        assert found[0]["kind"] == "user"
        assert {"kind": "group", "name": "Readers"}.items() <= groups[
            0
        ].items()
        assert send(client, "get", url).json() == []

    def test_candidates_are_the_managers_only(self, client, people, private):
        client.force_login(people["editor"])

        assert (
            send(
                client, "get", f"{WIKIS}{private.pk}/candidates/?q=a"
            ).status_code
            == 403
        )


class TestUploads:
    """An upload is its wiki's: read by that wiki's readers."""

    def upload(self, client, url: str, wiki: Wiki | None, name="a.png"):
        data = {
            "file": SimpleUploadedFile(name, PNG, content_type="image/png")
        }

        if wiki is not None:
            data["wiki"] = wiki.pk

        return client.post(url, data)

    def test_it_is_stored_with_its_wiki(self, client, people, private):
        client.force_login(people["editor"])

        image = self.upload(client, IMAGES, private)
        attachment = self.upload(client, FILES, private, "a.bin")

        assert image.status_code == 201
        assert WikiImage.objects.get().wiki == private
        assert attachment.status_code == 201
        assert WikiFile.objects.get().wiki == private

    @pytest.mark.parametrize("url", [IMAGES, FILES])
    def test_a_reader_of_the_wiki_does_not_upload_into_it(
        self, client, people, private, url
    ):
        client.force_login(people["reader"])

        assert self.upload(client, url, private).status_code == 403
        assert not WikiImage.objects.exists()

    def test_a_wiki_not_read_takes_no_upload(self, client, people, private):
        client.force_login(people["outsider"])

        assert self.upload(client, IMAGES, private).status_code == 403

    def test_without_a_wiki_it_needs_somewhere_to_write(self, client, people):
        client.force_login(people["reader"])
        refused = self.upload(client, IMAGES, None)
        client.force_login(people["outsider"])
        accepted = self.upload(client, IMAGES, None)

        assert refused.status_code == 403
        assert accepted.status_code == 201
        assert WikiImage.objects.get().wiki is None

    def test_another_wiki_s_upload_is_not_found(self, client, people, private):
        # What broke: any signed-in user opened any upload by its
        # number, whichever wiki it was in.
        client.force_login(people["editor"])
        image = self.upload(client, IMAGES, private).json()
        attachment = self.upload(client, FILES, private, "plan.bin").json()

        assert client.get(image["url"]).status_code == 200
        assert client.get(attachment["url"]).status_code == 200

        client.force_login(people["reader"])

        assert client.get(image["url"]).status_code == 200

        client.force_login(people["outsider"])

        assert client.get(image["url"]).status_code == 404
        assert client.get(attachment["url"]).status_code == 404

    def test_a_page_showing_it_opens_it_to_its_readers(
        self, client, people, private
    ):
        # A copy of a wiki shares the uploads of its source.
        client.force_login(people["editor"])
        image = self.upload(client, IMAGES, private).json()
        WikiPage.objects.create(
            wiki=Wiki.objects.get(slug="main"),
            title="Shared",
            slug="shared",
            content=f'<p><img src="{image["url"]}"></p>',
        )
        client.force_login(people["outsider"])

        assert client.get(image["url"]).status_code == 200

    def test_an_upload_without_a_wiki_is_its_uploader_s(self, client, people):
        client.force_login(people["outsider"])
        image = self.upload(client, IMAGES, None).json()

        assert client.get(image["url"]).status_code == 200

        client.force_login(people["reader"])

        assert client.get(image["url"]).status_code == 404

    def test_an_earlier_version_showing_it_opens_it(self, client, people):
        client.force_login(people["outsider"])
        image = self.upload(client, IMAGES, None).json()
        page = WikiPage.objects.create(
            wiki=Wiki.objects.get(slug="main"),
            title="Was",
            slug="was",
            content=f'<p><img src="{image["url"]}"></p>',
        )
        send(client, "patch", f"{PAGES}{page.pk}/", {"content": "<p>Gone</p>"})
        client.force_login(people["reader"])

        assert client.get(image["url"]).status_code == 200

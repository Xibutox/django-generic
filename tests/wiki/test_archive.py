"""A wiki exported as an archive, and imported back - here or on
another site."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError

from generic.wiki.archive import (
    FORMAT,
    MANIFEST,
    ArchiveError,
    import_archive,
    write_archive,
)
from generic.wiki.models import Wiki, WikiFile, WikiImage, WikiPage
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

IMPORT = "/wiki/api/wikis/import/"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.7\n" + b"\x00" * 24


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)

    return tmp_path


def writer(*codenames: str):
    user = UserFactory()
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="generic_wiki", codename__in=codenames
        )
    )

    return user


@pytest.fixture
def handbook():
    """A wiki with a subpage, an image and a file."""
    wiki = Wiki.objects.create(
        name="Handbook", slug="handbook", description="How we work."
    )
    image = WikiImage(original_name="Team photo.png")
    image.file.save("team.png", ContentFile(PNG), save=False)
    image.save()
    attachment = WikiFile(original_name="Plan 2026.pdf", size=len(PDF))
    attachment.file.save("plan.pdf", ContentFile(PDF), save=False)
    attachment.save()
    top = WikiPage.objects.create(
        wiki=wiki,
        title="Welcome",
        slug="welcome",
        position=1,
        show_on_dashboard=True,
        content=(
            f'<p>Hello</p><p><img src="/wiki/images/{image.pk}/"></p>'
            f'<p class="wiki-file"><a href="/wiki/files/{attachment.pk}/">'
            "Plan 2026.pdf</a></p>"
        ),
    )
    WikiPage.objects.create(
        wiki=wiki,
        title="Holidays",
        slug="holidays",
        parent=top,
        content=(
            f'<p><img src="/wiki/images/{image.pk}/"></p>'
            '<p><a href="/wiki/handbook/welcome/#rules">Welcome</a> '
            '<a href="/wiki/main/triage/">Triage</a></p>'
        ),
    )

    return wiki


def exported(wiki) -> bytes:
    output = io.BytesIO()
    write_archive(wiki, output)

    return output.getvalue()


def archive_of(manifest, members=None) -> io.BytesIO:
    output = io.BytesIO()

    with zipfile.ZipFile(output, "w") as archive:
        if manifest is not None:
            archive.writestr(
                MANIFEST,
                (
                    manifest
                    if isinstance(manifest, str)
                    else json.dumps(manifest)
                ),
            )

        for name, data in (members or {}).items():
            archive.writestr(name, data)

    output.seek(0)

    return output


def manifest_of(*pages, **extra):
    return {
        "format": FORMAT,
        "version": 1,
        "wiki": {"name": "Imported", "slug": "imported"},
        "pages": list(pages),
        **extra,
    }


class TestExport:
    def test_the_archive_holds_the_pages_and_their_uploads(self, handbook):
        with zipfile.ZipFile(io.BytesIO(exported(handbook))) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read(MANIFEST))
            image = archive.read("images/1.png")
            attachment = archive.read("files/2-Plan_2026.pdf")

        assert names == {MANIFEST, "images/1.png", "files/2-Plan_2026.pdf"}
        assert image == PNG
        assert attachment == PDF
        assert manifest["format"] == FORMAT
        assert manifest["version"] == 1
        assert manifest["wiki"] == {
            "name": "Handbook",
            "slug": "handbook",
            "description": "How we work.",
        }
        pages = {page["slug"]: page for page in manifest["pages"]}
        welcome, holidays = pages["welcome"], pages["holidays"]
        assert welcome["parent"] is None
        assert holidays["parent"] == welcome["id"]
        assert welcome["show_on_dashboard"] is True
        # The text names places in the archive, not this site's.
        assert 'src="images/1.png"' in welcome["content"]
        assert 'href="files/2-Plan_2026.pdf"' in welcome["content"]
        text = welcome["content"] + holidays["content"]
        assert "/wiki/images/" not in text
        assert "/wiki/files/" not in text
        assert "/wiki/handbook/" not in text
        # Each upload once, however many pages show it.
        assert manifest["images"] == [
            {"path": "images/1.png", "name": "Team photo.png"}
        ]
        assert manifest["files"] == [
            {
                "path": "files/2-Plan_2026.pdf",
                "name": "Plan 2026.pdf",
                "size": len(PDF),
            }
        ]

    def test_links_between_its_pages_follow_the_wiki(self, handbook):
        """Exported as ``pages/<id>/``, imported as the new address;
        a link to another wiki's page stays."""
        with zipfile.ZipFile(io.BytesIO(exported(handbook))) as archive:
            manifest = json.loads(archive.read(MANIFEST))

        pages = {page["slug"]: page for page in manifest["pages"]}
        number = pages["welcome"]["id"]
        assert f'href="pages/{number}/#rules"' in pages["holidays"]["content"]
        assert 'href="/wiki/main/triage/"' in pages["holidays"]["content"]

        result = import_archive(io.BytesIO(exported(handbook)))
        holidays = result.wiki.pages.get(slug="holidays")

        assert 'href="/wiki/handbook-2/welcome/#rules"' in holidays.content
        assert 'href="/wiki/main/triage/"' in holidays.content

    def test_an_upload_no_longer_stored_keeps_its_link(self, handbook, media):
        image = WikiImage.objects.get()
        (media / image.file.name).unlink()

        with zipfile.ZipFile(io.BytesIO(exported(handbook))) as archive:
            manifest = json.loads(archive.read(MANIFEST))

        assert manifest["images"] == []
        assert any(
            f'src="/wiki/images/{image.pk}/"' in page["content"]
            for page in manifest["pages"]
        )

    def test_a_reader_downloads_it(self, client, handbook):
        client.force_login(UserFactory())
        response = client.get("/wiki/handbook/export.zip")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"
        assert 'attachment; filename="handbook.zip"' == (
            response["Content-Disposition"]
        )
        data = b"".join(response.streaming_content)
        assert zipfile.ZipFile(io.BytesIO(data)).read("images/1.png") == PNG

    def test_anonymous_goes_to_the_login(self, client, handbook):
        response = client.get("/wiki/handbook/export.zip")

        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_a_hidden_wiki_is_not_found(self, client, handbook, settings):
        settings.GENERIC = {"WIKI_ACCESS": lambda user, wikis: wikis.none()}
        client.force_login(UserFactory())

        assert client.get("/wiki/handbook/export.zip").status_code == 404

    def test_downloads_given_on_request_cover_it(
        self, client, handbook, settings
    ):
        """The archive holds the wiki's files."""
        settings.GENERIC = {"ACCESS_ON_REQUEST": ("download",)}
        client.force_login(UserFactory())

        assert client.get("/wiki/handbook/export.zip").status_code == 403
        page = client.get("/wiki/handbook/welcome/")
        assert page.context["archive_url"] == ""

    def test_the_page_and_the_list_offer_it(self, client, handbook):
        client.force_login(UserFactory())

        page = client.get("/wiki/handbook/welcome/")
        assert page.context["archive_url"] == "/wiki/handbook/export.zip"
        assert b"/wiki/handbook/export.zip" in page.content

        wikis = client.get("/wiki/api/wikis/").json()
        assert wikis[0]["archive_url"] == "/wiki/handbook/export.zip"

    def test_the_list_offers_it_as_an_icon_beside_the_tools(
        self, client, handbook
    ):
        """An icon in the card's header, not a labelled footer button:
        a reader who may not change the wiki still gets it."""
        client.force_login(UserFactory())

        html = client.get("/wiki/").content.decode()
        tools = html.split('class="wiki-list__tools"', 1)[1]
        tools = tools.split("</div>", 1)[0]
        assert 'class="icon-button icon-button--sm" href="' in tools
        assert "/wiki/handbook/export.zip" in tools
        footer = html.split('class="wiki-list__footer"', 1)[1]
        assert "export.zip" not in footer


class TestImport:
    def test_an_export_comes_back_as_a_new_wiki(self, handbook, media):
        user = UserFactory()
        result = import_archive(io.BytesIO(exported(handbook)), user=user)

        wiki = result.wiki
        assert wiki.pk != handbook.pk
        assert wiki.name == "Handbook"
        # The address was taken: the name gives another.
        assert wiki.slug == "handbook-2"
        assert wiki.description == "How we work."
        assert (result.pages, result.images, result.files) == (2, 1, 1)
        assert result.skipped == []

        welcome = wiki.pages.get(slug="welcome")
        holidays = wiki.pages.get(slug="holidays")
        assert holidays.parent == welcome
        assert welcome.show_on_dashboard is True
        assert welcome.position == 1
        assert welcome.created_by == user

        image = WikiImage.objects.get(uploaded_by=user)
        attachment = WikiFile.objects.get(uploaded_by=user)
        assert image.original_name == "Team photo.png"
        assert (media / image.file.name).read_bytes() == PNG
        assert attachment.original_name == "Plan 2026.pdf"
        assert attachment.size == len(PDF)
        assert f'src="/wiki/images/{image.pk}/"' in welcome.content
        assert f'src="/wiki/images/{image.pk}/"' in holidays.content
        assert f'href="/wiki/files/{attachment.pk}/"' in welcome.content
        # The wiki it came from is untouched.
        assert handbook.pages.count() == 2

    def test_its_pages_read_like_the_originals(self, client, handbook):
        result = import_archive(io.BytesIO(exported(handbook)))
        client.force_login(UserFactory())

        page = client.get(f"/wiki/{result.wiki.slug}/welcome/")

        assert page.status_code == 200
        assert [a["name"] for a in page.context["attachments"]] == [
            "Team photo.png",
            "Plan 2026.pdf",
        ]

    def test_a_name_given_names_the_wiki(self, handbook):
        result = import_archive(
            io.BytesIO(exported(handbook)), name="Handbook (copy)"
        )

        assert result.wiki.name == "Handbook (copy)"
        assert result.wiki.slug == "handbook-copy"

    def test_a_free_address_is_kept(self):
        result = import_archive(
            archive_of(manifest_of({"id": 1, "title": "Home"}))
        )

        assert result.wiki.slug == "imported"
        assert result.wiki.pages.get().slug == "home"

    def test_the_text_is_cleaned(self):
        result = import_archive(
            archive_of(
                manifest_of(
                    {
                        "id": 1,
                        "title": "Home",
                        "content": '<p onclick="x()">Hi</p><script>x()'
                        "</script>",
                    }
                )
            )
        )

        assert result.wiki.pages.get().content == "<p>Hi</p>"

    def test_an_image_that_is_not_one_is_left_out(self):
        result = import_archive(
            archive_of(
                manifest_of(
                    {
                        "id": 1,
                        "title": "Home",
                        "content": '<p><img src="images/1.png"></p>',
                    },
                    images=[{"path": "images/1.png", "name": "x.png"}],
                ),
                {"images/1.png": b"<svg onload='x()'/>"},
            )
        )

        assert result.images == 0
        assert result.skipped == ["images/1.png"]
        assert not WikiImage.objects.exists()

    def test_a_file_too_large_is_left_out(self, settings):
        settings.GENERIC = {"FILE_MAX_SIZE": 10}
        result = import_archive(
            archive_of(
                manifest_of(
                    {"id": 1, "title": "Home"},
                    files=[{"path": "files/1-plan.pdf", "name": "plan.pdf"}],
                ),
                {"files/1-plan.pdf": PDF},
            )
        )

        assert result.skipped == ["files/1-plan.pdf"]
        assert not WikiFile.objects.exists()

    def test_only_members_under_their_folder_are_read(self):
        """A manifest naming ``wiki.json`` or ``../x`` as an upload gets
        nothing."""
        result = import_archive(
            archive_of(
                manifest_of(
                    {"id": 1, "title": "Home"},
                    files=[
                        {"path": MANIFEST},
                        {"path": "files/../wiki.json"},
                        {"path": "/etc/passwd"},
                    ],
                ),
            )
        )

        assert result.files == 0
        assert not WikiFile.objects.exists()

    def test_addresses_are_unique_and_loops_are_broken(self):
        result = import_archive(
            archive_of(
                manifest_of(
                    {"id": 1, "title": "A", "slug": "same", "parent": 2},
                    {"id": 2, "title": "B", "slug": "same", "parent": 1},
                    {"id": 3, "title": "C", "slug": "api", "parent": 1},
                    {"id": 4, "title": "D", "parent": 99},
                )
            )
        )

        pages = {page.title: page for page in result.wiki.pages.all()}
        assert pages["A"].slug == "same"
        assert pages["B"].slug == "same-2"
        assert pages["C"].slug == "api-page"
        assert pages["A"].parent is None
        assert pages["B"].parent is None
        assert pages["C"].parent == pages["A"]
        assert pages["D"].parent is None

    @pytest.mark.parametrize(
        "manifest, message",
        [
            (None, "no wiki.json"),
            ("{not json", "cannot be read"),
            ({"format": "other"}, "not a wiki archive"),
            (
                {"format": FORMAT, "version": 2, "wiki": {}, "pages": []},
                "later version",
            ),
            ({"format": FORMAT, "version": 1, "wiki": {}}, "incomplete"),
            (
                {"format": FORMAT, "version": 1, "wiki": {}, "pages": [1]},
                "invalid",
            ),
        ],
    )
    def test_what_is_not_a_wiki_archive_is_refused(self, manifest, message):
        with pytest.raises(ArchiveError, match=message):
            import_archive(archive_of(manifest))

        assert not Wiki.objects.filter(slug="imported").exists()

    def test_a_file_that_is_not_a_zip_is_refused(self):
        with pytest.raises(ArchiveError, match="not a zip"):
            import_archive(io.BytesIO(b"hello"))

    def test_an_archive_too_large_unpacked_is_refused(self, settings):
        settings.GENERIC = {"WIKI_ARCHIVE_MAX_SIZE": 1000}

        with pytest.raises(ArchiveError, match="too large"):
            import_archive(
                archive_of(
                    manifest_of({"id": 1, "title": "Home"}),
                    {"files/1-big": b"\x00" * 5000},
                )
            )

    def test_a_failure_leaves_nothing_behind(self, media):
        """Images stored before the pages failed are deleted too."""
        with pytest.raises(ArchiveError):
            import_archive(
                archive_of(
                    manifest_of(
                        {"id": 1, "title": "Home"},
                        {"id": 1, "title": "Twice"},
                        images=[{"path": "images/1.png"}],
                    ),
                    {"images/1.png": PNG},
                )
            )

        assert not Wiki.objects.filter(slug="imported").exists()
        assert not WikiImage.objects.exists()
        assert not list((media / "wiki").rglob("*.png"))


class TestImportEndpoint:
    @pytest.fixture
    def organiser(self, client):
        client.force_login(writer("add_wiki", "add_wikipage"))

        return client

    def send(self, client, data: bytes, **extra):
        return client.post(
            IMPORT,
            {
                "file": SimpleUploadedFile(
                    "handbook.zip", data, content_type="application/zip"
                ),
                **extra,
            },
        )

    def test_an_organiser_imports_a_wiki(self, organiser, handbook):
        response = self.send(organiser, exported(handbook), name="Copy")

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Copy"
        assert data["url"] == "/wiki/copy/"
        assert (data["pages"], data["images"], data["files"]) == (2, 1, 1)
        assert data["skipped"] == []
        assert Wiki.objects.get(slug="copy").pages.count() == 2

    @pytest.mark.parametrize(
        "codenames", [("add_wiki",), ("add_wikipage",), ()]
    )
    def test_it_needs_both_permissions(self, client, handbook, codenames):
        client.force_login(writer(*codenames))
        before = Wiki.objects.count()

        response = self.send(client, exported(handbook))

        assert response.status_code == 403
        assert Wiki.objects.count() == before

    def test_anonymous_is_refused(self, client, handbook):
        assert self.send(client, exported(handbook)).status_code == 403

    def test_a_bad_archive_says_why(self, organiser):
        response = self.send(organiser, b"hello")

        assert response.status_code == 400
        assert "not a zip" in response.json()["detail"]

    def test_no_file(self, organiser):
        assert organiser.post(IMPORT, {}).status_code == 400

    def test_an_upload_too_large_is_refused(self, organiser, settings):
        settings.GENERIC = {"WIKI_ARCHIVE_MAX_SIZE": 10}

        response = self.send(organiser, b"\x00" * 100)

        assert response.status_code == 400
        assert "too large" in response.json()["detail"]

    def test_a_wiki_they_could_not_write_in_is_undone(
        self, organiser, handbook, settings, media
    ):
        settings.GENERIC = {
            "WIKI_EDIT_ACCESS": lambda user, wikis: wikis.none()
        }
        before = set(media.rglob("*"))
        wikis = Wiki.objects.count()

        response = self.send(organiser, exported(handbook))

        assert response.status_code == 403
        assert Wiki.objects.count() == wikis
        assert WikiImage.objects.count() == 1
        assert set(media.rglob("*")) == before

    def test_the_list_offers_it(self, organiser, handbook):
        page = organiser.get("/wiki/")

        assert page.context["can"]["import"] is True
        assert b"Import a wiki" in page.content

    def test_the_list_does_not_offer_it_without_the_rights(
        self, client, handbook
    ):
        client.force_login(writer("add_wiki"))

        page = client.get("/wiki/")

        assert page.context["can"]["import"] is False
        assert b"Import a wiki" not in page.content


class TestCommands:
    def test_export_then_import(self, handbook, tmp_path):
        path = tmp_path / "out.zip"

        call_command("wiki_export", "handbook", "--output", str(path))
        call_command("wiki_import", str(path), "--name", "Restored")

        wiki = Wiki.objects.get(name="Restored")
        assert sorted(wiki.pages.values_list("slug", flat=True)) == [
            "holidays",
            "welcome",
        ]

    def test_unknown_wiki(self):
        with pytest.raises(CommandError):
            call_command("wiki_export", "nowhere")

    def test_not_an_archive(self, tmp_path):
        path = tmp_path / "x.zip"
        path.write_bytes(b"hello")

        with pytest.raises(CommandError, match="not a zip"):
            call_command("wiki_import", str(path))

"""Files in wiki pages: attached by writers, downloaded by readers."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile

from generic.wiki.models import WikiFile, WikiImage, WikiPage, attachments_in
from generic.wiki.sanitize import clean_html
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

UPLOAD = "/api/generic/wiki/files/"

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
def author(client):
    client.force_login(writer("change_wikipage"))

    return client


def send(client, name: str, content: bytes, kind: str = "application/pdf"):
    return client.post(
        UPLOAD, {"file": SimpleUploadedFile(name, content, content_type=kind)}
    )


class TestUpload:
    def test_a_writer_attaches_a_file(self, author, media):
        response = send(author, "Plan 2026.pdf", PDF)

        assert response.status_code == 201
        attachment = WikiFile.objects.get()
        assert response.json() == {
            "id": attachment.pk,
            "url": f"/wiki/files/{attachment.pk}/",
            "name": "Plan 2026.pdf",
            "size": len(PDF),
        }
        assert attachment.size == len(PDF)
        assert attachment.file.name.startswith("wiki/files/")
        assert (media / attachment.file.name).read_bytes() == PDF

    @pytest.mark.parametrize(
        "name", ["notes.txt", "sheet.xlsx", "page.html", "drawing.svg"]
    )
    def test_any_kind_of_file_is_taken(self, author, name):
        """It is only ever downloaded, never shown."""
        assert send(author, name, PDF).status_code == 201

    def test_a_path_in_the_name_is_dropped(self, author):
        send(author, "..\\..\\secret.pdf", PDF)

        assert WikiFile.objects.get().original_name == "secret.pdf"

    @pytest.mark.parametrize("codename", ["add_wikipage", "change_wikipage"])
    def test_adding_or_changing_pages_is_enough(self, client, codename):
        client.force_login(writer(codename))

        assert send(client, "a.pdf", PDF).status_code == 201

    def test_a_reader_cannot_upload(self, client):
        client.force_login(writer("view_wikipage", "delete_wikipage"))

        assert send(client, "a.pdf", PDF).status_code == 403
        assert not WikiFile.objects.exists()

    def test_signed_out_nobody_uploads(self, client):
        assert send(client, "a.pdf", PDF).status_code == 403

    def test_a_file_over_the_limit_is_refused(self, author, settings):
        settings.GENERIC = {"FILE_MAX_SIZE": 16}

        response = send(author, "big.pdf", PDF)

        assert response.status_code == 400
        assert "too large" in response.json()["detail"]
        assert not WikiFile.objects.exists()

    def test_an_empty_file_is_refused(self, author):
        response = send(author, "empty.pdf", b"")

        assert response.status_code == 400
        assert not WikiFile.objects.exists()

    def test_without_a_file_it_says_so(self, author):
        assert author.post(UPLOAD, {}).status_code == 400


class TestDownload:
    @pytest.fixture
    def attachment(self, author) -> WikiFile:
        return WikiFile.objects.get(
            pk=send(author, "page.html", b"<script>alert(1)</script>").json()[
                "id"
            ]
        )

    def test_a_reader_downloads_it_under_its_name(self, client, attachment):
        client.force_login(UserFactory())

        response = client.get(attachment.get_absolute_url())

        assert response.status_code == 200
        # Never shown: a page somebody uploaded does not run here.
        assert response["Content-Disposition"].startswith("attachment;")
        assert 'filename="page.html"' in response["Content-Disposition"]
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Content-Security-Policy"] == "sandbox"
        assert response["Cache-Control"] == "private, max-age=86400"
        assert b"".join(response.streaming_content) == (
            b"<script>alert(1)</script>"
        )

    def test_signed_out_it_asks_to_sign_in(self, client, attachment):
        client.logout()

        response = client.get(attachment.get_absolute_url())

        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_an_unknown_file_is_not_found(self, author):
        assert author.get("/wiki/files/999/").status_code == 404

    def test_a_file_the_storage_lost_is_not_found(
        self, author, media, attachment
    ):
        (media / attachment.file.name).unlink()

        assert author.get(attachment.get_absolute_url()).status_code == 404


class TestInAPage:
    BLOCK = '<p class="wiki-file"><a href="/wiki/files/{}/">plan.pdf</a></p>'

    def test_the_file_block_survives_the_cleaning(self):
        html = self.BLOCK.format(3)

        assert clean_html(html) == (
            '<p class="wiki-file"><a href="/wiki/files/3/" '
            'rel="noopener noreferrer">plan.pdf</a></p>'
        )

    def test_no_other_class_does(self):
        assert clean_html('<p class="wiki-file danger">x</p>') == (
            '<p class="wiki-file">x</p>'
        )
        assert "wiki-file" not in clean_html('<h2 class="wiki-file">x</h2>')

    def test_a_page_lists_its_uploads_in_its_order(self, author):
        attachment = WikiFile.objects.get(
            pk=send(author, "plan.pdf", PDF).json()["id"]
        )
        image = WikiImage.objects.create(
            file="wiki/images/a.png", original_name="diagram.png"
        )
        page = WikiPage.objects.create(
            title="Plans",
            slug="plans",
            content=(
                self.BLOCK.format(attachment.pk)
                + f'<p><img src="/wiki/images/{image.pk}/"></p>'
                # Twice, and a file no longer there: listed once, and
                # not at all.
                + self.BLOCK.format(attachment.pk)
                + self.BLOCK.format(999)
                + '<p><a href="https://example.com/wiki/files/1/">x</a></p>'
            ),
        )

        assert page.attachments() == [
            {
                "kind": "file",
                "id": attachment.pk,
                "name": "plan.pdf",
                "size": len(PDF),
                "url": f"/wiki/files/{attachment.pk}/",
            },
            {
                "kind": "image",
                "id": image.pk,
                "name": "diagram.png",
                "size": None,
                "url": f"/wiki/images/{image.pk}/",
            },
        ]

    def test_nothing_in_an_empty_page(self):
        assert attachments_in("") == []
        assert attachments_in("<p>Words.</p>") == []

    def test_the_api_and_the_page_show_them(self, author, admin_user):
        attachment = WikiFile.objects.get(
            pk=send(author, "plan.pdf", PDF).json()["id"]
        )
        page = WikiPage.objects.create(
            title="Plans",
            slug="plans",
            content=self.BLOCK.format(attachment.pk),
        )
        author.force_login(admin_user)

        data = author.get(f"/wiki/api/pages/{page.pk}/").json()
        response = author.get("/wiki/main/plans/")

        assert [item["name"] for item in data["attachments"]] == ["plan.pdf"]
        assert response.context["attachments"] == data["attachments"]
        assert response.context["wiki_config"]["filesUrl"] == UPLOAD
        assert b"wiki-attachments" in response.content

    def test_attachments_cannot_be_written(self, client, admin_user):
        client.force_login(admin_user)
        page = WikiPage.objects.create(title="Plans", slug="plans")

        response = client.patch(
            f"/wiki/api/pages/{page.pk}/",
            {"attachments": [{"kind": "file", "id": 1}]},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["attachments"] == []

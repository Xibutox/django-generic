"""Images in wiki pages: uploaded by writers, shown to readers."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from generic.wiki.api import sniff_image
from generic.wiki.models import WikiImage, WikiPage
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

UPLOAD = "/api/generic/wiki/images/"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 24
GIF = b"GIF89a" + b"\x00" * 24
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 16


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


def send(client, name: str, content: bytes, kind: str = "image/png"):
    return client.post(
        UPLOAD, {"file": SimpleUploadedFile(name, content, content_type=kind)}
    )


class TestUpload:
    def test_a_writer_uploads_an_image(self, author, media):
        response = send(author, "diagram.png", PNG)

        assert response.status_code == 201
        image = WikiImage.objects.get()
        assert response.json() == {
            "id": image.pk,
            "url": f"/wiki/images/{image.pk}/",
        }
        assert image.original_name == "diagram.png"
        assert (media / image.file.name).read_bytes() == PNG
        assert image.file.name.startswith("wiki/images/")

    def test_the_address_follows_the_wiki(self, author):
        image = WikiImage.objects.get(
            pk=send(author, "a.png", PNG).json()["id"]
        )

        assert image.get_absolute_url() == reverse(
            "generic_wiki:image", kwargs={"pk": image.pk}
        )

    @pytest.mark.parametrize("codename", ["add_wikipage", "change_wikipage"])
    def test_adding_or_changing_pages_is_enough(self, client, codename):
        client.force_login(writer(codename))

        assert send(client, "a.png", PNG).status_code == 201

    def test_a_reader_cannot_upload(self, client):
        client.force_login(writer("view_wikipage", "delete_wikipage"))

        assert send(client, "a.png", PNG).status_code == 403
        assert not WikiImage.objects.exists()

    def test_signed_out_nobody_uploads(self, client):
        assert send(client, "a.png", PNG).status_code == 403

    def test_a_page_named_png_is_refused(self, author):
        """The bytes decide, not the name."""
        response = send(author, "photo.png", b"<html><script>x</script>")

        assert response.status_code == 400
        assert "not a PNG" in response.json()["detail"]
        assert not WikiImage.objects.exists()

    @pytest.mark.parametrize(
        "name, content",
        [
            ("drawing.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
            ("notes.txt", PNG),
            ("page.html", PNG),
        ],
    )
    def test_only_the_four_image_types_are_taken(self, author, name, content):
        response = send(author, name, content)

        assert response.status_code == 400
        assert "PNG, JPEG, GIF and WebP" in response.json()["detail"]

    def test_an_image_over_the_limit_is_refused(self, author, settings):
        settings.GENERIC = {"FILE_MAX_SIZE": 16}

        response = send(author, "big.png", PNG)

        assert response.status_code == 400
        assert "too large" in response.json()["detail"]

    def test_without_a_file_it_says_so(self, author):
        assert author.post(UPLOAD, {}).status_code == 400

    def test_it_is_stored_as_what_its_bytes_are(self, author):
        """A JPEG called .png is a JPEG: stored and served as one."""
        image_id = send(author, "photo.png", JPEG).json()["id"]
        image = WikiImage.objects.get(pk=image_id)

        assert image.file.name.endswith(".jpg")
        assert author.get(image.get_absolute_url())["Content-Type"] == (
            "image/jpeg"
        )

    @pytest.mark.parametrize(
        "content, stored",
        [(PNG, "png"), (JPEG, "jpg"), (GIF, "gif"), (WEBP, "webp")],
    )
    def test_the_four_kinds_are_told_apart(self, content, stored):
        assert sniff_image(content) == stored

    def test_nothing_else_is_an_image(self):
        assert sniff_image(b"<svg/>") is None
        assert sniff_image(b"RIFF\x00\x00\x00\x00WAVE") is None
        assert sniff_image(b"") is None


class TestServing:
    @pytest.fixture
    def image(self, author) -> WikiImage:
        return WikiImage.objects.get(
            pk=send(author, "a.png", PNG).json()["id"]
        )

    def test_a_reader_sees_it_in_the_page(self, client, image):
        client.force_login(UserFactory())

        response = client.get(image.get_absolute_url())

        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert response["Content-Disposition"].startswith("inline;")
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Cache-Control"] == "private, max-age=86400"
        assert b"".join(response.streaming_content) == PNG

    def test_signed_out_it_asks_to_sign_in(self, client, image):
        client.logout()

        response = client.get(image.get_absolute_url())

        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_an_unknown_image_is_not_found(self, author):
        assert author.get("/wiki/images/999/").status_code == 404

    def test_an_image_the_storage_lost_is_not_found(
        self, author, media, image
    ):
        (media / image.file.name).unlink()

        assert author.get(image.get_absolute_url()).status_code == 404


class TestInAPage:
    def test_a_saved_page_keeps_its_uploaded_image(self, client, admin_user):
        client.force_login(admin_user)
        page = WikiPage.objects.create(title="Diagrams", slug="diagrams")

        response = client.patch(
            f"/wiki/api/pages/{page.pk}/",
            {"content": '<p>Look:</p><p><img src="/wiki/images/1/"></p>'},
            content_type="application/json",
        )

        assert response.status_code == 200
        page.refresh_from_db()
        assert '<img src="/wiki/images/1/">' in page.content

    def test_the_editor_knows_where_to_upload(self, client, admin_user):
        client.force_login(admin_user)
        WikiPage.objects.create(title="Diagrams", slug="diagrams")

        response = client.get("/wiki/main/diagrams/")
        config = response.context["wiki_config"]

        assert config["imagesUrl"] == UPLOAD
        assert config["imageMaxSize"] == 10 * 1024 * 1024

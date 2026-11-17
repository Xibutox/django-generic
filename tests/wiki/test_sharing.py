"""A wiki's public link: its pages, read-only, for anyone holding it."""

from __future__ import annotations

import pytest
from django.core.files.base import ContentFile
from django.test import override_settings

from generic.wiki.models import Wiki, WikiImage, WikiMember, WikiPage
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

WIKIS = "/wiki/api/wikis/"

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(autouse=True)
def public_links(settings):
    settings.GENERIC = {
        **getattr(settings, "GENERIC", {}),
        "WIKI_PUBLIC_LINKS": True,
    }
    yield


@pytest.fixture
def wiki():
    wiki = Wiki.objects.create(name="Handbook", slug="hb", access="private")
    WikiPage.objects.create(
        wiki=wiki,
        title="Start",
        slug="start",
        content='<p>See <a href="/wiki/hb/more/">more</a>.</p>',
    )
    WikiPage.objects.create(wiki=wiki, title="More", slug="more", position=1)

    return wiki


def share(client, wiki, method="post"):
    return getattr(client, method)(
        f"{WIKIS}{wiki.pk}/share/", content_type="application/json"
    )


def shared_path(client, wiki) -> str:
    url = share(client, wiki).json()["url"]

    return url.split("testserver", 1)[-1]


class TestLink:
    def test_off_until_made(self, admin_client, wiki):
        assert share(admin_client, wiki, "get").json() == {
            "enabled": True,
            "url": "",
        }

    def test_made(self, admin_client, wiki):
        path = shared_path(admin_client, wiki)

        assert path.startswith("/wiki/shared/")
        assert share(admin_client, wiki, "get").json()["url"].endswith(path)

    def test_a_new_one_ends_the_old(self, admin_client, client, wiki):
        old = shared_path(admin_client, wiki)
        shared_path(admin_client, wiki)

        assert client.get(old).status_code == 404

    def test_taken_away(self, admin_client, client, wiki):
        path = shared_path(admin_client, wiki)
        share(admin_client, wiki, "delete")

        assert client.get(path).status_code == 404

    def test_only_who_manages_the_wiki(self, client, wiki):
        editor = UserFactory()
        WikiMember.objects.create(wiki=wiki, user=editor, role="editor")
        client.force_login(editor)

        assert share(client, wiki).status_code == 403
        assert share(client, wiki, "get").status_code == 403

    def test_not_where_the_site_does_not_allow_it(
        self, admin_client, client, wiki, settings
    ):
        path = shared_path(admin_client, wiki)

        with override_settings(
            GENERIC={**settings.GENERIC, "WIKI_PUBLIC_LINKS": False}
        ):
            assert share(admin_client, wiki, "get").json() == {
                "enabled": False,
                "url": "",
            }
            assert share(admin_client, wiki).status_code == 403
            assert client.get(path).status_code == 404


class TestReading:
    def test_its_first_page_for_anyone(self, admin_client, client, wiki):
        response = client.get(shared_path(admin_client, wiki))

        assert response.status_code == 200
        assert "Start" in response.content.decode()
        assert response["X-Robots-Tag"] == "noindex, nofollow"
        assert response["Referrer-Policy"] == "no-referrer"

    def test_links_between_pages_stay_shared(self, admin_client, client, wiki):
        path = shared_path(admin_client, wiki)
        html = client.get(path).content.decode()

        assert f'href="{path}more/"' in html
        assert "/wiki/hb/more/" not in html
        assert client.get(f"{path}more/").status_code == 200

    def test_a_page_in_the_trash_is_not_shown(
        self, admin_client, client, wiki
    ):
        path = shared_path(admin_client, wiki)
        WikiPage.objects.filter(slug="more").update(
            deleted_at="2026-01-01T00:00:00Z"
        )

        assert client.get(f"{path}more/").status_code == 404

    def test_a_wiki_in_the_trash_is_not_shown(
        self, admin_client, client, wiki
    ):
        path = shared_path(admin_client, wiki)
        Wiki.all_objects.filter(pk=wiki.pk).update(
            deleted_at="2026-01-01T00:00:00Z"
        )

        assert client.get(path).status_code == 404

    def test_an_unknown_secret(self, client, wiki):
        assert client.get("/wiki/shared/nothing/").status_code == 404

    def test_another_wiki_s_page_is_not_reached(
        self, admin_client, client, wiki
    ):
        other = Wiki.objects.create(name="Secret", slug="secret")
        WikiPage.objects.create(wiki=other, title="Hidden", slug="hidden")
        path = shared_path(admin_client, wiki)

        assert client.get(f"{path}hidden/").status_code == 404


class TestUploads:
    @pytest.fixture
    def image(self, wiki):
        image = WikiImage(wiki=wiki)
        image.file.save("dot.png", ContentFile(PNG), save=True)

        return image

    def test_an_image_a_page_shows(self, admin_client, client, wiki, image):
        WikiPage.objects.filter(slug="start").update(
            content=f'<p><img src="{image.get_absolute_url()}"></p>'
        )
        path = shared_path(admin_client, wiki)
        html = client.get(path).content.decode()

        assert f'src="{path}images/{image.pk}/"' in html
        assert client.get(f"{path}images/{image.pk}/").status_code == 200

    def test_not_an_image_no_page_shows(
        self, admin_client, client, wiki, image
    ):
        path = shared_path(admin_client, wiki)

        assert client.get(f"{path}images/{image.pk}/").status_code == 404

    def test_the_image_address_is_still_closed(
        self, admin_client, client, wiki, image
    ):
        WikiPage.objects.filter(slug="start").update(
            content=f'<p><img src="{image.get_absolute_url()}"></p>'
        )
        shared_path(admin_client, wiki)

        assert client.get(image.get_absolute_url()).status_code == 302

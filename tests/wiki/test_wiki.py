"""The wiki: clean HTML, the API's rules, the pages, and the site."""

from __future__ import annotations

import pytest

from generic.sites import site
from generic.wiki.models import MAX_REVISIONS, WikiPage, WikiRevision
from generic.wiki.sanitize import clean_html

pytestmark = pytest.mark.django_db

PAGES = "/wiki/api/pages/"


def post(client, url: str, data: dict):
    return client.post(url, data, content_type="application/json")


def patch(client, url: str, data: dict):
    return client.patch(url, data, content_type="application/json")


@pytest.fixture
def handbook(admin_user) -> dict:
    """Two pages at the top of the menu, one under the second."""
    welcome = WikiPage.objects.create(
        title="Welcome",
        slug="welcome",
        position=0,
        content="<p>Hello <strong>desk</strong>.</p>",
        updated_by=admin_user,
    )
    triage = WikiPage.objects.create(
        title="Triage",
        slug="triage",
        position=1,
        content="<p>Sort by urgency.</p>",
    )
    escalation = WikiPage.objects.create(
        title="Escalation",
        slug="escalation",
        parent=triage,
        content="<p>Call the lead.</p>",
    )

    return {"welcome": welcome, "triage": triage, "escalation": escalation}


class TestCleaning:
    def test_scripts_and_handlers_are_removed(self):
        html = clean_html(
            '<p onclick="steal()">Hi<script>alert(1)</script></p>'
        )

        assert html == "<p>Hi</p>"

    def test_a_javascript_link_loses_its_address(self):
        html = clean_html('<a href="javascript:alert(1)">x</a>')

        assert "javascript" not in html

    def test_a_link_keeps_a_safe_target_and_gets_a_rel(self):
        html = clean_html(
            '<a href="https://example.test" target="_blank">x</a>'
        )

        assert 'href="https://example.test"' in html
        assert 'rel="noopener noreferrer"' in html

    def test_a_link_to_another_page_stays(self):
        html = clean_html('<a href="/wiki/triage/">Triage</a>')

        assert 'href="/wiki/triage/"' in html

    def test_only_the_editor_classes_are_kept(self):
        html = clean_html('<p class="ql-align-center button--danger">x</p>')

        assert html == '<p class="ql-align-center">x</p>'

    def test_inline_image_data_is_dropped(self):
        html = clean_html('<img src="data:image/png;base64,AAAA" alt="x">')

        assert "data:" not in html

    def test_styles_are_dropped(self):
        html = clean_html('<p style="position:fixed">x</p><style>p{}</style>')

        assert html == "<p>x</p>"

    def test_a_saved_page_holds_clean_html(self, db):
        page = WikiPage.objects.create(
            title="T",
            slug="t",
            content="<p>a<script>b()</script></p>",
        )
        page.refresh_from_db()

        assert page.content == "<p>a</p>"


class TestApi:
    def test_signed_in_users_read_the_menu(self, auth_client, handbook):
        response = auth_client.get(PAGES)

        assert response.status_code == 200
        assert sorted(page["title"] for page in response.json()) == [
            "Escalation",
            "Triage",
            "Welcome",
        ]
        # The menu carries no text.
        assert "content" not in response.json()[0]

    def test_reading_needs_an_account(self, client, handbook):
        assert client.get(PAGES).status_code in (401, 403)

    def test_writing_needs_the_permissions(self, auth_client, handbook):
        url = f"{PAGES}{handbook['welcome'].pk}/"

        assert post(auth_client, PAGES, {"title": "Mine"}).status_code == 403
        assert patch(auth_client, url, {"title": "Mine"}).status_code == 403
        assert auth_client.delete(url).status_code == 403

    def test_a_new_page_gets_a_free_address(self, admin_client, handbook):
        taken = post(admin_client, PAGES, {"title": "Welcome"})
        reserved = post(admin_client, PAGES, {"title": "API"})

        assert taken.status_code == 201, taken.json()
        assert taken.json()["slug"] == "welcome-2"
        assert taken.json()["url"] == "/wiki/welcome-2/"
        assert reserved.json()["slug"] == "api-page"

    def test_changed_words_keep_the_previous_version(
        self,
        admin_client,
        handbook,
    ):
        welcome = handbook["welcome"]
        url = f"{PAGES}{welcome.pk}/"
        version = admin_client.get(url).json()["version"]

        response = patch(
            admin_client,
            url,
            {"content": "<p>New text.</p>", "version": version},
        )
        [revision] = welcome.revisions.all()

        assert response.status_code == 200, response.json()
        assert revision.content == "<p>Hello <strong>desk</strong>.</p>"

        # Moving a page in the menu keeps no version.
        patch(admin_client, url, {"position": 5})

        assert welcome.revisions.count() == 1

    def test_a_save_against_an_old_version_is_refused(
        self,
        admin_client,
        handbook,
    ):
        welcome = handbook["welcome"]
        response = patch(
            admin_client,
            f"{PAGES}{welcome.pk}/",
            {"content": "<p>Mine</p>", "version": "2000-01-01T00:00:00+00:00"},
        )
        welcome.refresh_from_db()

        assert response.status_code == 409
        assert "Mine" not in welcome.content

    def test_a_page_cannot_go_under_itself(self, admin_client, handbook):
        response = patch(
            admin_client,
            f"{PAGES}{handbook['triage'].pk}/",
            {"parent": handbook["escalation"].pk},
        )

        assert response.status_code == 400
        assert "parent" in response.json()

    def test_an_old_version_comes_back(self, admin_client, handbook):
        welcome = handbook["welcome"]
        url = f"{PAGES}{welcome.pk}/"
        patch(admin_client, url, {"content": "<p>Second.</p>"})
        revision = welcome.revisions.get()

        response = post(
            admin_client, f"{url}restore/", {"revision": revision.pk}
        )
        welcome.refresh_from_db()

        assert response.status_code == 200
        assert welcome.content == "<p>Hello <strong>desk</strong>.</p>"
        # The text it replaced went to the history in turn.
        assert welcome.revisions.filter(content="<p>Second.</p>").exists()

    def test_a_deleted_page_leaves_its_subpages_at_the_top(
        self,
        admin_client,
        handbook,
    ):
        response = admin_client.delete(f"{PAGES}{handbook['triage'].pk}/")
        handbook["escalation"].refresh_from_db()

        assert response.status_code == 204
        assert handbook["escalation"].parent is None

    def test_the_history_is_capped(self, handbook):
        page = handbook["welcome"]

        for _index in range(MAX_REVISIONS + 5):
            WikiRevision.keep(page)

        assert page.revisions.count() == MAX_REVISIONS


class TestPages:
    def test_the_wiki_opens_on_its_first_page(self, auth_client, handbook):
        response = auth_client.get("/wiki/")

        assert response.status_code == 302
        assert response.url == "/wiki/welcome/"

    def test_an_empty_wiki_invites_the_first_page(self, admin_client, db):
        response = admin_client.get("/wiki/")

        assert response.status_code == 200
        assert b"Write the first page" in response.content

    def test_a_page_shows_clean_text_and_the_menu(self, auth_client, handbook):
        # Straight into the table: no save() to clean it on the way in.
        WikiPage.objects.filter(pk=handbook["welcome"].pk).update(
            content="<p>Hi<script>steal()</script></p>"
        )

        response = auth_client.get("/wiki/welcome/")
        menu = response.context["menu"]

        assert response.status_code == 200
        assert b"steal()" not in response.content
        assert [entry["title"] for entry in menu] == ["Welcome", "Triage"]
        assert menu[1]["children"][0]["title"] == "Escalation"
        # The filter keeps a page in sight while a subpage matches.
        assert "escalation" in menu[1]["search"]

    def test_the_editor_is_for_editors(self, auth_client, handbook):
        response = auth_client.get("/wiki/welcome/")

        assert response.context["can"] == {
            "add": False,
            "change": False,
            "delete": False,
        }
        assert b'id="wiki-editor"' not in response.content

    def test_an_unknown_page_is_not_found(self, auth_client, db):
        assert auth_client.get("/wiki/nothing/").status_code == 404

    def test_an_anonymous_visitor_is_sent_to_sign_in(self, client, handbook):
        response = client.get("/wiki/welcome/")

        assert response.status_code == 302
        assert response.url.startswith("/login/")


class TestSite:
    def test_pinned_pages_reach_the_dashboard(self, auth_client, handbook):
        WikiPage.objects.filter(pk=handbook["welcome"].pk).update(
            show_on_dashboard=True
        )

        response = auth_client.get("/")

        assert [page["title"] for page in response.context["wiki_pinned"]] == [
            "Welcome"
        ]
        assert b"Hello <strong>desk</strong>." in response.content

    def test_the_palette_finds_pages(self, auth_client, handbook):
        groups = auth_client.get("/api/search/", {"q": "urgency"}).json()[
            "groups"
        ]
        wiki = next(group for group in groups if group["label"] == "Wiki")

        assert wiki["items"][0]["url"] == "/wiki/triage/"

    def test_the_sidebar_links_to_the_wiki(self, rf, user):
        request = rf.get("/")
        request.user = user

        labels = [
            item["label"]
            for group in site.get_navigation(request)
            for item in group["items"]
        ]

        assert "Wiki" in labels

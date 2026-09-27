"""The site's icon, named by every page with a head of its own.

A page that names none makes the browser ask for ``/favicon.ico``,
which nobody serves: a 404 in the console of every first visit. The
icon is one include, ``generic/includes/favicon.html``, which a project
overrides to change it everywhere.
"""

from __future__ import annotations

import copy

import pytest
from django.template.loader import render_to_string

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

ICON = 'rel="icon"'


@pytest.fixture
def signed_in(client):
    client.force_login(UserFactory(is_superuser=True, is_staff=True))

    return client


class TestEveryPageNamesIt:
    def test_the_sign_in_page(self, client):
        response = client.get("/login/")

        assert response.status_code == 200
        assert response.content.decode().count(ICON) == 1

    def test_a_page_of_the_frame(self, signed_in):
        response = signed_in.get("/")

        assert response.status_code == 200
        assert response.content.decode().count(ICON) == 1

    def test_a_popup_s_last_page(self):
        html = render_to_string(
            "generic/popup_response.html",
            {"popup_response_data": {"action": "add", "value": "1"}},
        )

        assert ICON in html


def test_a_project_changes_it_everywhere_with_one_file(
    tmp_path, settings, client
):
    own = tmp_path / "generic" / "includes" / "favicon.html"
    own.parent.mkdir(parents=True)
    own.write_text('<link rel="icon" href="/static/mine.svg">\n')

    templates = copy.deepcopy(settings.TEMPLATES)
    templates[0]["DIRS"] = [str(tmp_path), *templates[0].get("DIRS", [])]
    settings.TEMPLATES = templates

    sign_in = client.get("/login/").content.decode()
    client.force_login(UserFactory(is_superuser=True, is_staff=True))
    frame = client.get("/").content.decode()

    for page in (sign_in, frame):
        assert 'href="/static/mine.svg"' in page
        assert page.count(ICON) == 1

"""Where to report a bug: set once, drawn for everyone in the top bar."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from generic.help.models import HelpSettings, safe_link, validate_link
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

SETTINGS = "/api/generic/help/settings/"
SCHEMA = "/api/generic/help/settings/form-schema/"
HELP = "/help/"
TICKETS = "https://tickets.example.com/new"


@pytest.fixture
def administrator(db):
    """Someone allowed to change the help settings."""
    user = UserFactory(username="administrator")
    user.user_permissions.add(
        Permission.objects.get(codename="change_helpsettings")
    )

    return user


class TestTheLink:
    @pytest.mark.parametrize(
        "value",
        [
            TICKETS,
            "http://intranet/bugs",
            "mailto:support@example.com",
            "mailto:support@example.com?subject=Bug",
            "",
        ],
    )
    def test_a_web_address_or_a_mailbox_is_accepted(self, value):
        validate_link(value)

        assert safe_link(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "javascript:alert(1)",
            "ftp://files.example.com/",
            "tickets.example.com",
            "mailto:not an address",
            "http://[unclosed/",
        ],
    )
    def test_anything_else_is_refused(self, value):
        with pytest.raises(ValidationError):
            validate_link(value)

        assert safe_link(value) == ""

    def test_without_a_row_or_a_setting_there_is_none(self):
        assert HelpSettings.bug_report_link() == ""

    def test_the_setting_is_the_default(self, settings):
        settings.GENERIC = {"BUG_REPORT_URL": TICKETS}

        assert HelpSettings.bug_report_link() == TICKETS

    def test_the_administrators_link_replaces_the_setting(self, settings):
        settings.GENERIC = {"BUG_REPORT_URL": TICKETS}
        HelpSettings.objects.create(bug_report_url="mailto:bugs@example.com")

        assert HelpSettings.bug_report_link() == "mailto:bugs@example.com"

    def test_an_unsafe_setting_is_not_drawn(self, settings):
        # The setting is the project's text and never went through the
        # form: a javascript: link would run in every page.
        settings.GENERIC = {"BUG_REPORT_URL": "javascript:alert(1)"}

        assert HelpSettings.bug_report_link() == ""


class TestChangingIt:
    def test_anyone_signed_in_reads_it(self, authenticated_client):
        response = authenticated_client.get(SETTINGS)

        assert response.status_code == 200
        assert response.json()["bug_report_url"] == ""

    def test_the_permission_is_needed_to_change_it(
        self,
        authenticated_client,
    ):
        response = authenticated_client.patch(
            SETTINGS,
            {"bug_report_url": TICKETS},
            format="json",
        )

        assert response.status_code == 403
        assert not HelpSettings.objects.exists()

    def test_signed_out_nothing_is_read(self, api_client):
        assert api_client.get(SETTINGS).status_code in (401, 403)

    def test_an_administrator_sets_it_for_everyone(
        self,
        api_client,
        administrator,
    ):
        api_client.force_authenticate(administrator)

        response = api_client.patch(
            SETTINGS,
            {"bug_report_url": TICKETS},
            format="json",
        )

        assert response.status_code == 200
        saved = HelpSettings.objects.get()
        assert saved.bug_report_url == TICKETS
        assert saved.updated_by == administrator

        # One row, however many times it is changed.
        api_client.patch(SETTINGS, {"bug_report_url": ""}, format="json")
        assert HelpSettings.objects.count() == 1
        assert HelpSettings.bug_report_link() == ""

    def test_an_unsafe_link_is_refused(self, api_client, administrator):
        api_client.force_authenticate(administrator)

        response = api_client.patch(
            SETTINGS,
            {"bug_report_url": "javascript:alert(1)"},
            format="json",
        )

        assert response.status_code == 400
        assert "bug_report_url" in response.json()

    def test_the_form_is_described(self, api_client, administrator):
        api_client.force_authenticate(administrator)

        schema = api_client.get(SCHEMA).json()

        assert schema["mode"] == "update"
        assert "bug_report_url" in str(schema)


class TestTheFrame:
    def test_nothing_is_drawn_without_a_link(self, auth_client):
        response = auth_client.get("/account/")

        assert response.context["chrome"]["bug_report_url"] == ""
        assert "Report a bug" not in response.content.decode()

    def test_everyone_signed_in_sees_it(self, auth_client):
        HelpSettings.objects.create(bug_report_url=TICKETS)

        rendered = auth_client.get("/account/").content.decode()

        assert f'href="{TICKETS}"' in rendered
        # In a tab of its own: the page being reported stays open.
        assert 'target="_blank"' in rendered
        assert "Report a bug" in rendered

    def test_the_help_page_offers_it(self, auth_client):
        HelpSettings.objects.create(bug_report_url=TICKETS)

        response = auth_client.get(HELP)

        assert response.context["bug_report_url"] == TICKETS
        # Not the form: that is for whoever may change it.
        assert response.context["settings_config"] is None

    def test_the_administrator_gets_the_form(self, client, administrator):
        client.force_login(administrator)

        config = client.get(HELP).context["settings_config"]

        assert config["objectUrl"] == SETTINGS
        assert config["schemaUrl"] == SCHEMA

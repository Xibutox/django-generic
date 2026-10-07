"""The page hosting an API-backed interactive table."""

from __future__ import annotations

import json

import pytest
from django.core.exceptions import ImproperlyConfigured

from generic.views import DataTableView

pytestmark = pytest.mark.django_db

URL = "/books/table/"


def config_of(response) -> dict:
    return response.context["table_config"]


class TestConfiguration:
    def test_the_page_renders(self, auth_client, library):
        response = auth_client.get(URL)

        assert response.status_code == 200

    def test_the_endpoint_is_resolved(self, auth_client, library):
        assert config_of(auth_client.get(URL))["url"] == "/api/books/"

    def test_columns_come_from_the_serializer(
        self,
        auth_client,
        library,
    ):
        columns = config_of(auth_client.get(URL))["columns"]
        names = [column["data"] for column in columns]

        # The very same declaration the API filters against.
        assert "title" in names
        assert "author" in names

    def test_the_state_key_is_unique_to_the_view(
        self,
        auth_client,
        library,
    ):
        options = config_of(auth_client.get(URL))["options"]

        assert options["stateKey"].endswith("BookTablePage")

    def test_the_page_size_comes_from_the_settings(
        self,
        auth_client,
        library,
    ):
        options = config_of(auth_client.get(URL))["options"]

        # tests.settings sets TABLE_PAGE_SIZE to 10.
        assert options["pageLength"] == 10

    def test_the_filter_row_is_shown_from_the_start(
        self,
        auth_client,
        library,
    ):
        options = config_of(auth_client.get(URL))["options"]

        assert options["filterRow"] == "open"

    def test_the_filter_row_script_is_loaded(self, auth_client, library):
        rendered = auth_client.get(URL).content.decode()

        # After the filter bar, whose editor the row's fields open.
        assert rendered.index("datatables/filterbar.js") < rendered.index(
            "datatables/filterrow.js"
        )

    def test_the_config_is_serialised_as_json_script(
        self,
        auth_client,
        library,
    ):
        rendered = auth_client.get(URL).content.decode()

        # Carried as data, never interpolated into executable code.
        assert 'id="datatable-config"' in rendered
        assert 'type="application/json"' in rendered

    def test_the_config_is_valid_json(self, auth_client, library):
        rendered = auth_client.get(URL).content.decode()
        start = rendered.index('id="datatable-config"')
        body = rendered[start:]
        body = body[body.index(">") + 1 : body.index("</script>")]

        assert json.loads(body)["url"] == "/api/books/"


class TestViews:
    """The Views menu: presets for everyone, each user's own saved."""

    def test_each_user_may_save_views(self, auth_client, library):
        options = config_of(auth_client.get(URL))["options"]

        assert options["savedViewsUrl"] == "/api/generic/saved-views/"
        assert options["presets"] == {}

    def test_the_page_offers_its_presets(self, rf, user):
        view = DataTableView()
        view.request = rf.get("/")
        view.request.user = user
        view.presets = {"Recent": {"order": [["published_on", "desc"]]}}

        presets = view.get_table_options()["presets"]

        assert presets == {"Recent": {"order": [["published_on", "desc"]]}}

    def test_the_state_left_follows_the_preference(self, auth_client, user):
        from generic.accounts.models import UserPreferences

        options = config_of(auth_client.get(URL))["options"]
        assert options["stateSave"] is True

        UserPreferences.objects.update_or_create(
            user=user, defaults={"remember_table_state": False}
        )
        options = config_of(auth_client.get(URL))["options"]
        assert options["stateSave"] is False


class TestMisconfiguration:
    def test_a_missing_viewset_is_reported(self, rf, user):
        view = DataTableView()
        view.request = rf.get("/")
        view.request.user = user

        with pytest.raises(ImproperlyConfigured, match="viewset"):
            view.get_viewset()

    def test_a_missing_endpoint_is_reported(self, rf, user):
        view = DataTableView()
        view.request = rf.get("/")

        with pytest.raises(ImproperlyConfigured, match="api_url_name"):
            view.get_api_url()

    def test_a_page_may_hide_the_filter_row_or_leave_it_out(self):
        view = DataTableView()

        view.filter_row = "toggle"
        assert view.get_table_options()["filterRow"] == "toggle"

        view.filter_row = False
        assert view.get_table_options()["filterRow"] is False

    def test_an_unknown_filter_row_is_reported(self):
        view = DataTableView()
        view.filter_row = "always"

        with pytest.raises(
            ImproperlyConfigured, match="DataTableView.filter_row"
        ):
            view.get_table_options()


class TestToolbar:
    def test_the_add_button_needs_the_permission(
        self,
        auth_client,
        library,
    ):
        response = auth_client.get(URL)

        assert response.context["toolbar_items"] == []

    def test_the_add_button_appears_with_the_permission(
        self,
        auth_client,
        user,
        library,
    ):
        from django.contrib.auth.models import Permission

        user.user_permissions.add(Permission.objects.get(codename="add_book"))
        auth_client.force_login(user)

        response = auth_client.get(URL)

        assert [item.url for item in response.context["toolbar_items"]] == [
            "/books/add/"
        ]

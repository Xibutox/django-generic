"""An edit icon on each row of a list (``ModelResource.list_edit_link``).

The example's tickets declare it; its customers do not.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from example.models import Customer
from generic.sites import site

pytestmark = pytest.mark.django_db


def row_actions(client, url: str) -> list[dict]:
    response = client.get(url)

    assert response.status_code == 200, response.content

    return response.context["table_config"]["options"]["rowActions"]


def inline(actions: list[dict]) -> list[dict]:
    return [action for action in actions if action.get("inline")]


class TestTheIcon:
    def test_the_edit_action_is_drawn_on_each_row(
        self, admin_client, support_desk
    ):
        actions = row_actions(admin_client, "/example/ticket/")

        assert inline(actions) == [
            {
                "name": "change",
                "label": "Edit",
                "icon": "edit",
                "url": "/example/ticket/{_pk}/change/",
                "inline": True,
            }
        ]

    def test_the_row_menu_keeps_its_entries(self, admin_client, support_desk):
        names = [
            action["name"]
            for action in row_actions(admin_client, "/example/ticket/")
        ]

        # "Open" stays first: it is what a double-click opens.
        assert names[:2] == ["open", "change"]
        assert "duplicate" in names

    def test_off_by_default(self, admin_client, support_desk):
        assert site.get_resource(Customer).list_edit_link is False
        assert inline(row_actions(admin_client, "/example/customer/")) == []

    def test_a_resource_opening_on_its_form_draws_it_too(
        self, admin_client, support_desk, monkeypatch
    ):
        resource = site.get_resource(Customer)
        monkeypatch.setattr(resource, "list_edit_link", True)
        monkeypatch.setattr(resource, "object_page", "change")

        actions = row_actions(admin_client, "/example/customer/")

        assert [action["name"] for action in inline(actions)] == ["change"]


class TestPermissions:
    def test_hidden_from_who_may_only_read(
        self, client, django_user_model, support_desk
    ):
        reader = django_user_model.objects.create_user(username="reader")
        reader.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label="example", codename="view_ticket"
            )
        )
        client.force_login(reader)

        actions = row_actions(client, "/example/ticket/")

        assert inline(actions) == []
        assert "change" not in [action["name"] for action in actions]

    def test_shown_to_who_may_change(self, worker_client, support_desk):
        actions = row_actions(worker_client, "/example/ticket/")

        assert [action["name"] for action in inline(actions)] == ["change"]

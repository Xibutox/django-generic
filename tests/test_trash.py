"""A resource's trash: delete moves records there, restore brings them
back, delete for good and ``empty()`` delete them.

``tests.testapp.Contract`` is ``Trashable``; ``ContractResource``
declares ``trash = True``.
"""

from __future__ import annotations

import datetime
import json

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from generic.sites import ModelResource, site
from generic.trash import empty, move_to_trash
from tests.factories import UserFactory
from tests.testapp.models import Author, Contract

pytestmark = pytest.mark.django_db

API = "/api/testapp/contract/"
TRASH = {"_trash": "1"}


def signed_in(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)

    return client


def allowed(*codenames: str):
    user = UserFactory()
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="testapp", codename__in=codenames
        )
    )

    return user


def titles(client, extra: dict | None = None) -> list[str]:
    body = client.get(API, {"draw": 1, "length": 50, **(extra or {})}).json()

    return [row["title"] for row in body["data"]]


@pytest.fixture
def admin(admin_user) -> APIClient:
    return signed_in(admin_user)


@pytest.fixture
def contracts():
    return [
        Contract.objects.create(title=title)
        for title in ("Lease", "Loan", "Supply")
    ]


class TestDelete:
    def test_delete_moves_the_record_to_the_trash(
        self, admin, admin_user, contracts
    ):
        lease = contracts[0]

        response = admin.delete(f"{API}{lease.pk}/")

        assert response.status_code == 204
        lease.refresh_from_db()
        assert lease.deleted_at is not None
        assert lease.deleted_by == admin_user
        assert titles(admin) == ["Loan", "Supply"]
        assert titles(admin, TRASH) == ["Lease"]

    def test_the_record_is_gone_from_every_screen(self, admin, contracts):
        lease = contracts[0]
        move_to_trash(lease)

        assert admin.get(f"{API}{lease.pk}/").status_code == 404
        assert admin.get(f"{API}{lease.pk}/summary/").status_code == 404
        assert admin.get(f"/testapp/contract/{lease.pk}/").status_code == 302

    def test_the_bulk_action_moves_them_and_says_so(self, admin, contracts):
        response = admin.post(
            f"{API}actions/",
            {"action": "delete_selected", "ids": [contracts[0].pk]},
            format="json",
        )

        assert response.status_code == 200
        assert "moved to the trash" in response.json()["message"]
        assert Contract.objects.count() == 3
        assert titles(admin, TRASH) == ["Lease"]

    def test_the_actions_say_trash(self, admin_user):
        resource = site.get_resource(Contract)
        request = type("Request", (), {"user": admin_user, "GET": {}})()

        actions = resource.get_actions(request)

        assert str(actions["delete_selected"].description) == (
            "Move to the trash"
        )
        assert "restore_from_trash" not in actions

    def test_the_preview_says_trash(self, admin, contracts):
        response = admin.get(f"{API}{contracts[0].pk}/deletion-preview/")

        assert response.json()["trash"] is True

    def test_the_delete_page_moves_it_too(self, client, admin_user, contracts):
        client.force_login(admin_user)
        lease = contracts[0]

        page = client.get(f"/testapp/contract/{lease.pk}/delete/")
        response = client.post(f"/testapp/contract/{lease.pk}/delete/")

        assert "to the trash" in page.content.decode()
        assert response.status_code == 302
        lease.refresh_from_db()
        assert lease.deleted_at is not None


class TestTrash:
    def test_restore_puts_it_back(self, admin, contracts):
        lease = contracts[0]
        move_to_trash(lease)

        response = admin.post(
            f"{API}actions/?_trash=1",
            {"action": "restore_from_trash", "ids": [lease.pk]},
            format="json",
        )

        assert response.status_code == 200, response.json()
        lease.refresh_from_db()
        assert lease.deleted_at is None
        assert lease.deleted_by is None
        assert titles(admin) == ["Lease", "Loan", "Supply"]

    def test_delete_for_good_deletes(self, admin, contracts):
        lease = contracts[0]
        move_to_trash(lease)

        response = admin.post(
            f"{API}actions/?_trash=1",
            {"action": "delete_selected", "ids": [lease.pk]},
            format="json",
        )

        assert response.status_code == 200
        assert not Contract.objects.filter(pk=lease.pk).exists()

    def test_restore_only_reaches_the_trash(self, admin, contracts):
        response = admin.post(
            f"{API}actions/",
            {"action": "restore_from_trash", "ids": [contracts[0].pk]},
            format="json",
        )

        assert response.status_code == 400

    def test_whoever_may_not_delete_sees_no_trash(self, contracts):
        reader = signed_in(allowed("view_contract"))
        move_to_trash(contracts[0])

        assert titles(reader, TRASH) == []
        assert reader.get("/testapp/contract/trash/").status_code in (302, 403)

    def test_the_trash_page_lists_the_deleted(
        self, client, admin_user, contracts
    ):
        client.force_login(admin_user)
        move_to_trash(contracts[0], admin_user)

        response = client.get("/testapp/contract/trash/")
        config = json.loads(
            response.content.decode()
            .split('<script id="trash-table" type="application/json">')[1]
            .split("</script>")[0]
        )

        assert response.status_code == 200
        assert config["options"]["extraParams"] == {"_trash": "1"}
        assert config["options"]["bulkActionsUrl"].endswith("?_trash=1")
        assert [
            entry["name"] for entry in config["options"]["bulkActions"]
        ] == [
            "restore_from_trash",
            "delete_selected",
        ]
        assert config["options"]["rowActions"] == []
        names = [column["data"] for column in config["columns"]]
        assert "deleted_at" in names and "deleted_by" in names

    def test_the_trash_page_is_offered_on_the_list(self, client, admin_user):
        client.force_login(admin_user)

        response = client.get("/testapp/contract/")

        assert "/testapp/contract/trash/" in response.content.decode()

    def test_a_relation_no_longer_offers_it(self, admin, contracts):
        author = Author.objects.create(name="Writer", email="w@test")
        contract = contracts[0]
        contract.author = author
        contract.save()
        move_to_trash(contract)

        assert titles(admin) == ["Loan", "Supply"]


class TestEmpty:
    def test_it_deletes_what_is_older_than_the_days(self, contracts):
        old, recent, live = contracts
        move_to_trash(old)
        move_to_trash(recent)
        Contract.objects.filter(pk=old.pk).update(
            deleted_at=timezone.now() - datetime.timedelta(days=40)
        )

        assert empty() == 1
        assert list(
            Contract.objects.order_by("title").values_list("title", flat=True)
        ) == ["Loan", "Supply"]

    def test_none_keeps_everything(self, settings, contracts):
        settings.GENERIC = {**settings.GENERIC, "TRASH_DAYS": None}
        from generic.conf import generic_settings

        generic_settings._cache.clear()
        move_to_trash(contracts[0])
        Contract.objects.update(
            deleted_at=timezone.now() - datetime.timedelta(days=400)
        )

        try:
            assert empty() == 0
        finally:
            generic_settings._cache.clear()

    def test_the_command_empties_it(self, contracts):
        move_to_trash(contracts[0])

        call_command(
            "empty_trash", "--days", "0", stdout=open("/dev/null", "w")
        )

        assert Contract.objects.count() == 2

    def test_the_task_is_declared(self):
        from generic.tasks.registry import registry

        assert registry.get("generic.empty_trash") is not None


def test_a_trash_needs_its_field():
    class Wrong(ModelResource):
        trash = True

    with pytest.raises(ImproperlyConfigured, match="deleted_at"):
        Wrong(Author, site)

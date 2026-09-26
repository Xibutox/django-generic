"""Managing accounts, groups and permissions from the framework.

Most of this is about what the screens refuse. Editing an account is
editing what somebody may do, so the tests that matter are the ones
where a narrow permission tries to widen itself.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import override_settings

from generic.sites import site

pytestmark = pytest.mark.django_db

USERS = "/api/auth/user/"
GROUPS = "/api/auth/group/"
PERMISSIONS = "/api/auth/permission/"


def post(client, url: str, data: dict):
    return client.post(url, data, content_type="application/json")


def patch(client, url: str, data: dict):
    return client.patch(url, data, content_type="application/json")


def permission(codename: str) -> Permission:
    return Permission.objects.get(codename=codename)


def permissions(*codenames: str):
    return Permission.objects.filter(codename__in=codenames)


@pytest.fixture
def manager(db):
    """Somebody who may manage accounts, and little else.

    They hold the four user permissions, the group ones, and exactly
    one permission of the example - which is the one they are allowed
    to hand on.
    """
    user = get_user_model().objects.create_user(
        username="manager",
        email="manager@example.test",
        password="a-long-enough-passphrase",
    )
    user.user_permissions.set(
        permissions(
            "view_user",
            "add_user",
            "change_user",
            "delete_user",
            "view_group",
            "add_group",
            "change_group",
            "view_permission",
            "view_ticket",
        )
    )

    return user


@pytest.fixture
def manager_client(client, manager):
    client.force_login(manager)

    return client


@pytest.fixture
def boss(db):
    return get_user_model().objects.create_superuser(
        username="boss",
        email="boss@example.test",
        password="another-long-passphrase",
    )


@pytest.fixture
def boss_client(client, boss):
    client.force_login(boss)

    return client


class TestPasswords:
    def test_an_account_is_created_with_a_working_password(
        self,
        boss_client,
    ):
        response = post(
            boss_client,
            USERS,
            {"username": "newcomer", "password": "correct-horse-staple"},
        )

        assert response.status_code == 201, response.content[:400]
        assert authenticate(
            username="newcomer",
            password="correct-horse-staple",
        )

    def test_the_hash_is_never_sent_back(self, boss_client, manager):
        """The form may be opened by anyone who may change the account;
        handing them the hash would be handing them the password."""
        created = post(
            boss_client,
            USERS,
            {"username": "quiet", "password": "correct-horse-staple"},
        )
        read = boss_client.get(f"{USERS}{manager.pk}/")

        assert "password" not in created.json()
        assert "password" not in read.json()

    def test_a_weak_password_is_refused_by_name(self, boss_client):
        response = post(
            boss_client,
            USERS,
            {"username": "newcomer", "password": "1234"},
        )

        assert response.status_code == 400
        assert "password" in response.json()
        assert not get_user_model().objects.filter(username="newcomer")

    def test_an_account_can_be_created_for_a_directory(self, boss_client):
        """No password means no password here, not an empty one."""
        post(boss_client, USERS, {"username": "ldap-person"})
        person = get_user_model().objects.get(username="ldap-person")

        assert not person.has_usable_password()
        assert not authenticate(username="ldap-person", password="")

    def test_saving_the_form_again_keeps_the_password(
        self,
        boss_client,
        manager,
    ):
        response = patch(
            boss_client,
            f"{USERS}{manager.pk}/",
            {"first_name": "Renamed"},
        )

        assert response.status_code == 200
        assert authenticate(
            username="manager",
            password="a-long-enough-passphrase",
        )

    def test_a_new_password_replaces_the_old_one(self, boss_client, manager):
        patch(
            boss_client,
            f"{USERS}{manager.pk}/",
            {"password": "a-brand-new-passphrase"},
        )

        assert authenticate(
            username="manager",
            password="a-brand-new-passphrase",
        )
        assert not authenticate(
            username="manager",
            password="a-long-enough-passphrase",
        )

    def test_the_password_is_never_recorded_in_the_history(
        self,
        boss_client,
        manager,
    ):
        from generic.history import history_of

        patch(
            boss_client,
            f"{USERS}{manager.pk}/",
            {"password": "a-brand-new-passphrase", "first_name": "Kept"},
        )

        kept = list(history_of(manager))

        assert kept
        assert not any("password" in (entry.values or {}) for entry in kept)


class TestGrantingWhatYouDoNotHave:
    def test_a_manager_cannot_make_somebody_a_superuser(
        self,
        manager_client,
        manager,
    ):
        response = patch(
            manager_client,
            f"{USERS}{manager.pk}/",
            {"is_superuser": True},
        )
        manager.refresh_from_db()

        assert response.status_code == 400
        assert "is_superuser" in response.json()
        assert manager.is_superuser is False

    def test_a_manager_cannot_grant_a_permission_they_lack(
        self,
        manager_client,
        boss,
    ):
        """Through a group, which is the way nobody notices."""
        powerful = Group.objects.create(name="Powerful")
        powerful.permissions.set(permissions("delete_ticket"))

        response = patch(
            manager_client,
            f"{USERS}{boss.pk}/",
            {"groups": [powerful.pk]},
        )

        assert response.status_code in (400, 403)

    def test_a_manager_cannot_grant_one_directly_either(
        self,
        manager_client,
        manager,
    ):
        response = patch(
            manager_client,
            f"{USERS}{manager.pk}/",
            {"user_permissions": [permission("delete_ticket").pk]},
        )

        assert response.status_code == 400
        assert "user_permissions" in response.json()

    def test_a_manager_may_grant_what_they_hold(
        self,
        manager_client,
        manager,
    ):
        newcomer = get_user_model().objects.create_user(username="newcomer")

        response = patch(
            manager_client,
            f"{USERS}{newcomer.pk}/",
            {"user_permissions": [permission("view_ticket").pk]},
        )

        assert response.status_code == 200, response.content[:400]
        assert newcomer.has_perm("example.view_ticket")

    def test_a_superuser_may_grant_anything(self, boss_client):
        newcomer = get_user_model().objects.create_user(username="newcomer")

        response = patch(
            boss_client,
            f"{USERS}{newcomer.pk}/",
            {"is_superuser": True},
        )

        assert response.status_code == 200, response.content[:400]

    def test_a_group_cannot_be_given_more_than_its_author_has(
        self,
        manager_client,
    ):
        response = post(
            manager_client,
            GROUPS,
            {
                "name": "Sneaky",
                "permissions": [permission("delete_ticket").pk],
            },
        )

        assert response.status_code == 400
        assert "permissions" in response.json()
        assert not Group.objects.filter(name="Sneaky").exists()


class TestReachingASuperuser:
    def test_a_manager_may_not_change_one(self, manager_client, boss):
        response = patch(
            manager_client,
            f"{USERS}{boss.pk}/",
            {"first_name": "Taken over"},
        )
        boss.refresh_from_db()

        assert response.status_code == 403
        assert boss.first_name == ""

    def test_a_manager_may_not_delete_one(self, manager_client, boss):
        response = manager_client.delete(f"{USERS}{boss.pk}/")

        assert response.status_code == 403
        assert get_user_model().objects.filter(pk=boss.pk).exists()

    def test_a_superuser_still_can(self, boss_client, manager):
        response = boss_client.delete(f"{USERS}{manager.pk}/")

        assert response.status_code == 204


class TestYourOwnAccount:
    def test_you_cannot_delete_it(self, boss_client, boss):
        response = boss_client.delete(f"{USERS}{boss.pk}/")

        assert response.status_code == 403
        assert get_user_model().objects.filter(pk=boss.pk).exists()

    def test_you_cannot_deactivate_it(self, boss_client, boss):
        response = patch(
            boss_client,
            f"{USERS}{boss.pk}/",
            {"is_active": False},
        )
        boss.refresh_from_db()

        assert response.status_code == 400
        assert "is_active" in response.json()
        assert boss.is_active is True

    def test_the_bulk_action_leaves_it_alone(
        self,
        boss_client,
        boss,
        manager,
    ):
        """Selecting everybody and pressing Deactivate is how an
        administrator locks themselves out."""
        response = post(
            boss_client,
            f"{USERS}actions/",
            {"action": "deactivate", "ids": [boss.pk, manager.pk]},
        )
        boss.refresh_from_db()
        manager.refresh_from_db()

        assert response.status_code == 200
        assert boss.is_active is True
        assert manager.is_active is False


class TestTheScreens:
    def test_a_group_counts_its_members_and_its_permissions(
        self,
        boss_client,
        manager,
    ):
        desk = Group.objects.create(name="Desk")
        desk.permissions.set(permissions("view_ticket", "add_ticket"))
        manager.groups.add(desk)

        rows = boss_client.get(
            GROUPS,
            {"draw": 1, "start": 0, "length": 10},
        ).json()["data"]
        row = next(entry for entry in rows if entry["name"] == "Desk")

        assert row["member_count"] == 1
        assert row["permission_count"] == 2

    def test_a_permission_cannot_be_invented(self, boss_client):
        response = post(
            boss_client,
            PERMISSIONS,
            {"name": "Can do anything", "codename": "anything"},
        )

        assert response.status_code == 403

    def test_the_screens_are_hidden_from_everyone_else(
        self,
        worker_client,
    ):
        """The example's desk agent has no auth permissions at all."""
        groups = [
            group["label"]
            for group in site.get_navigation(_request(worker_client))
        ]

        assert "People" not in groups
        assert worker_client.get("/auth/user/").status_code == 403

    def test_a_superuser_sees_them(self, boss_client):
        groups = [
            group["label"]
            for group in site.get_navigation(_request(boss_client))
        ]

        assert "People" in groups
        assert boss_client.get("/auth/user/").status_code == 200


@override_settings(GENERIC={"SHOW_PEOPLE": False})
def test_the_setting_is_read_when_the_screens_are_registered():
    """The registration is what the setting turns off, and it happens
    once at start-up - so this checks the decision, not the registry."""
    from generic.accounts.resources import register_screens

    before = len(site.get_resources())
    register_screens()

    assert len(site.get_resources()) == before


def _request(client):
    """A request the navigation can be built for."""
    from django.test import RequestFactory

    request = RequestFactory().get("/")
    request.user = get_user_model().objects.get(
        pk=client.session["_auth_user_id"]
    )

    return request

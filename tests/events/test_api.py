"""Notification history endpoints."""

from __future__ import annotations

import pytest

from generic.events.models import Notification, NotificationLevel
from tests.factories import NotificationFactory, UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/generic/notifications/"


class TestScoping:
    def test_only_the_signed_in_user_s_rows_are_listed(
        self,
        authenticated_client,
        user,
    ):
        NotificationFactory(user=user, title="Mine")
        NotificationFactory(user=UserFactory(), title="Someone else's")

        response = authenticated_client.get(URL)

        assert response.status_code == 200
        assert [row["title"] for row in response.data["data"]] == ["Mine"]

    def test_another_user_s_row_cannot_be_retrieved(
        self,
        authenticated_client,
    ):
        foreign = NotificationFactory(user=UserFactory())

        response = authenticated_client.get(f"{URL}{foreign.pk}/")

        assert response.status_code == 404

    def test_another_user_s_row_cannot_be_marked_read(
        self,
        authenticated_client,
    ):
        foreign = NotificationFactory(user=UserFactory())

        response = authenticated_client.post(f"{URL}{foreign.pk}/read/")

        assert response.status_code == 404

        foreign.refresh_from_db()
        assert foreign.read_at is None

    def test_anonymous_access_is_refused(self, api_client):
        response = api_client.get(URL)

        assert response.status_code in {401, 403}


class TestListing:
    def test_the_list_uses_the_datatables_envelope(
        self,
        authenticated_client,
        user,
    ):
        NotificationFactory(user=user)

        response = authenticated_client.get(URL)

        assert set(response.data) == {
            "draw",
            "recordsTotal",
            "recordsFiltered",
            "data",
        }

    def test_rows_can_be_filtered(self, authenticated_client, user):
        NotificationFactory(user=user, title="Build failed")
        NotificationFactory(user=user, title="Build passed")

        response = authenticated_client.get(
            URL,
            {
                "advanced_filters": (
                    '{"title": {"operator": "contains", ' '"value": "failed"}}'
                )
            },
        )

        assert [row["title"] for row in response.data["data"]] == [
            "Build failed"
        ]

    def test_the_read_flag_is_exposed(
        self,
        authenticated_client,
        user,
    ):
        NotificationFactory(user=user)

        row = authenticated_client.get(URL).data["data"][0]

        assert row["read"] is False

    def test_the_date_travels_as_every_other_table_s(
        self,
        authenticated_client,
        user,
        settings,
    ):
        """ISO in the active time zone, which the browser draws in the
        reader's language - or TABLE_DATETIME_FORMAT, when a project
        fixes one for every language."""
        import datetime

        settings.TIME_ZONE = "Europe/Paris"
        NotificationFactory(
            user=user,
            created_at=datetime.datetime(
                2026, 9, 26, 7, 51, 3, 443390, tzinfo=datetime.timezone.utc
            ),
        )

        row = authenticated_client.get(URL).data["data"][0]

        assert row["created_at"].startswith("2026-09-26T09:51:03")
        assert row["created_at"].endswith("+02:00")

    def test_a_project_may_fix_the_text(self, settings):
        from generic.api.columns import DateTimeColumn

        settings.GENERIC = {
            **getattr(settings, "GENERIC", {}),
            "TABLE_DATETIME_FORMAT": "%d.%m.%Y %H:%M",
        }

        assert DateTimeColumn().format == "%d.%m.%Y %H:%M"


class TestUnreadCount:
    def test_it_counts_only_unread_rows(
        self,
        authenticated_client,
        user,
    ):
        NotificationFactory(user=user)
        read = NotificationFactory(user=user)
        read.mark_read()

        response = authenticated_client.get(f"{URL}unread-count/")

        assert response.data == {"unread": 1}

    def test_it_ignores_other_users(
        self,
        authenticated_client,
        user,
    ):
        NotificationFactory(user=UserFactory())

        response = authenticated_client.get(f"{URL}unread-count/")

        assert response.data == {"unread": 0}


class TestReadTransitions:
    def test_a_row_can_be_marked_read(
        self,
        authenticated_client,
        notification,
    ):
        response = authenticated_client.post(f"{URL}{notification.pk}/read/")

        assert response.status_code == 200
        assert response.data["read"] is True

        notification.refresh_from_db()
        assert notification.read_at is not None

    def test_marking_read_twice_keeps_the_first_timestamp(
        self,
        authenticated_client,
        notification,
    ):
        authenticated_client.post(f"{URL}{notification.pk}/read/")
        notification.refresh_from_db()
        first = notification.read_at

        authenticated_client.post(f"{URL}{notification.pk}/read/")
        notification.refresh_from_db()

        assert notification.read_at == first

    def test_a_row_can_be_marked_unread(
        self,
        authenticated_client,
        notification,
    ):
        notification.mark_read()

        response = authenticated_client.post(f"{URL}{notification.pk}/unread/")

        assert response.data["read"] is False

    def test_everything_can_be_marked_read_at_once(
        self,
        authenticated_client,
        user,
    ):
        for _ in range(3):
            NotificationFactory(user=user)

        response = authenticated_client.post(f"{URL}read-all/")

        assert response.data == {"updated": 3}
        assert Notification.objects.for_user(user).unread().count() == 0

    def test_marking_all_read_leaves_other_users_alone(
        self,
        authenticated_client,
        user,
    ):
        foreign = NotificationFactory(user=UserFactory())

        authenticated_client.post(f"{URL}read-all/")

        foreign.refresh_from_db()
        assert foreign.read_at is None


class TestDeletion:
    def test_a_row_can_be_dismissed(
        self,
        authenticated_client,
        notification,
    ):
        response = authenticated_client.delete(f"{URL}{notification.pk}/")

        assert response.status_code == 204
        assert not Notification.objects.filter(pk=notification.pk).exists()


class TestManager:
    def test_notify_creates_one_row_per_user(self, db):
        users = [UserFactory() for _ in range(3)]

        created = Notification.objects.notify(
            users,
            title="Deployment finished",
            level=NotificationLevel.SUCCESS,
        )

        assert len(created) == 3
        assert Notification.objects.count() == 3

    def test_notify_can_attach_an_object(self, db, user, library):
        Notification.objects.notify(
            [user],
            title="Book updated",
            content_object=library["emma"],
        )

        notification = Notification.objects.get()

        assert notification.content_object == library["emma"]

    def test_mark_read_skips_already_read_rows(self, db, user):
        first = NotificationFactory(user=user)
        first.mark_read()
        NotificationFactory(user=user)

        updated = Notification.objects.for_user(user).mark_read()

        assert updated == 1

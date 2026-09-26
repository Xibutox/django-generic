"""Watching a record, or a whole model, and hearing about it.

The messages leave on commit, so anything that expects one commits
first - which is also the behaviour worth pinning down: a change that
is rolled back was never news.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from example.models import Ticket
from generic.accounts.models import UserPreferences
from generic.events.models import Notification
from generic.sites import site
from generic.watch import is_watching, unwatch, watch
from generic.watch.models import Watch

pytestmark = pytest.mark.django_db

WATCHES = "/api/generic/watches/"
TOGGLE = f"{WATCHES}toggle/"
STATUS = f"{WATCHES}status/"
PAGE = "/watching/"


@pytest.fixture
def reader(django_user_model):
    """A user who may read tickets, and so may be told about them."""
    reader = django_user_model.objects.create_user(
        username="reader",
        email="reader@example.test",
        password="x",
    )
    reader.user_permissions.add(
        Permission.objects.get(
            codename="view_ticket",
            content_type__app_label="example",
        )
    )

    return reader


@pytest.fixture
def reader_client(client, reader):
    client.force_login(reader)

    return client


def titles_for(user):
    return list(
        Notification.objects.filter(user=user).values_list("title", flat=True)
    )


class TestWatchingOneRecord:
    def test_a_change_is_told(
        self,
        reader,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        ticket = support_desk["login"]
        watch(reader, ticket)

        with django_capture_on_commit_callbacks(execute=True):
            ticket.title = "Login fails, still"
            ticket.save()

        assert titles_for(reader) == [
            "Ticket changed: SD-1 - Login fails, still"
        ]

    def test_a_change_that_is_rolled_back_is_not(
        self,
        reader,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        """On commit, like every other announcement."""
        watch(reader, support_desk["login"])

        with django_capture_on_commit_callbacks(execute=False):
            support_desk["login"].save()

        assert Notification.objects.count() == 0

    def test_a_deletion_is_told_and_links_nowhere(
        self,
        reader,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        ticket = support_desk["login"]
        watch(reader, ticket)

        with django_capture_on_commit_callbacks(execute=True):
            ticket.delete()

        notification = Notification.objects.get(user=reader)

        assert notification.title.startswith("Ticket deleted:")
        # The page it would point at is gone with the record.
        assert notification.url == ""

    def test_the_watch_survives_what_it_watched(
        self,
        reader,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        """Its label is what is left to read, so it is kept."""
        ticket = support_desk["login"]
        watch(reader, ticket)

        with django_capture_on_commit_callbacks(execute=True):
            ticket.delete()

        row = Watch.objects.get(user=reader)

        assert row.label == "SD-1 - Login fails after password reset"
        assert str(row) == row.label

    def test_only_the_changes_it_asked_for(
        self,
        reader,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        watch(reader, support_desk["login"], events=["deleted"])

        with django_capture_on_commit_callbacks(execute=True):
            support_desk["login"].save()

        assert Notification.objects.count() == 0

    def test_a_record_cannot_be_watched_for_its_own_creation(
        self,
        reader,
        support_desk,
    ):
        """It existed before the watch did, so there is nothing to hear."""
        row = watch(reader, support_desk["login"], events=["created"])

        assert row.events == []

    def test_nobody_else_is_told(
        self,
        reader,
        user,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        watch(reader, support_desk["login"])

        with django_capture_on_commit_callbacks(execute=True):
            support_desk["login"].save()

        assert Notification.objects.filter(user=user).count() == 0


class TestWatchingAModel:
    def test_every_change_of_every_record(
        self,
        reader,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        watch(reader, Ticket)

        with django_capture_on_commit_callbacks(execute=True):
            created = Ticket.objects.create(
                reference="SD-9",
                title="Printer on fire",
                team=support_desk["front"],
            )

        with django_capture_on_commit_callbacks(execute=True):
            created.title = "Printer, extinguished"
            created.save()

        with django_capture_on_commit_callbacks(execute=True):
            created.delete()

        assert [title.split(":")[0] for title in titles_for(reader)] == [
            "Ticket deleted",
            "Ticket changed",
            "Ticket created",
        ]

    def test_one_message_when_both_are_watched(
        self,
        reader,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        """Two watches, one change, one message: people, not rows."""
        watch(reader, Ticket)
        watch(reader, support_desk["login"])

        with django_capture_on_commit_callbacks(execute=True):
            support_desk["login"].save()

        assert Notification.objects.filter(user=reader).count() == 1


class TestWhoMayBeTold:
    def test_a_watcher_who_may_not_see_it_hears_nothing(
        self,
        user,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        """A watch must never become a way to learn a record exists.

        The permission is checked again when the message is sent, not
        only when the watch was made: permissions are taken away.
        """
        watch(user, support_desk["login"])

        with django_capture_on_commit_callbacks(execute=True):
            support_desk["login"].save()

        assert Notification.objects.count() == 0

    def test_a_resource_can_refuse_a_watcher(
        self,
        reader,
        support_desk,
        monkeypatch,
        django_capture_on_commit_callbacks,
    ):
        """``may_watch`` is where row level rules are said again."""
        resource = site.get_resource(Ticket)
        monkeypatch.setattr(
            type(resource),
            "may_watch",
            lambda self, user, obj=None: False,
        )
        watch(reader, support_desk["login"])

        with django_capture_on_commit_callbacks(execute=True):
            support_desk["login"].save()

        assert Notification.objects.count() == 0

    def test_an_inactive_user_is_left_alone(
        self,
        reader,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        watch(reader, support_desk["login"])
        reader.is_active = False
        reader.save(update_fields=["is_active"])

        with django_capture_on_commit_callbacks(execute=True):
            support_desk["login"].save()

        assert Notification.objects.count() == 0


class TestHowTheyAreTold:
    def test_the_channels_of_the_watch_win(
        self,
        reader,
        support_desk,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        watch(reader, support_desk["login"], channels=["mail"])

        with django_capture_on_commit_callbacks(execute=True):
            support_desk["login"].save()

        assert Notification.objects.count() == 0
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["reader@example.test"]

    def test_without_them_the_account_answers(
        self,
        reader,
        support_desk,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        """An empty choice follows the preference, and keeps following."""
        UserPreferences.objects.create(
            user=reader,
            notification_channel=UserPreferences.NotificationChannel.EMAIL,
        )
        watch(reader, support_desk["login"])

        with django_capture_on_commit_callbacks(execute=True):
            support_desk["login"].save()

        assert Notification.objects.count() == 0
        assert len(mailoutbox) == 1

    def test_a_reader_of_french_is_written_to_in_french(
        self,
        reader,
        support_desk,
        django_capture_on_commit_callbacks,
    ):
        UserPreferences.objects.create(user=reader, language="fr")
        watch(reader, support_desk["login"])

        with django_capture_on_commit_callbacks(execute=True):
            support_desk["login"].save()

        assert Notification.objects.get(user=reader).title.startswith(
            "Ticket modifié"
        )


class TestTheButton:
    def test_watching_and_unwatching_a_record(
        self,
        worker_client,
        worker,
        support_desk,
    ):
        payload = {
            "model": "example.ticket",
            "objectId": support_desk["login"].pk,
        }

        started = worker_client.post(
            TOGGLE, payload, content_type="application/json"
        )
        stopped = worker_client.post(
            TOGGLE, payload, content_type="application/json"
        )

        assert started.status_code == 201
        assert started.json()["watching"] is True
        assert stopped.json() == {"watching": False, "id": None}
        assert not Watch.objects.exists()

    def test_watching_a_whole_model(self, worker_client, worker):
        response = worker_client.post(
            TOGGLE,
            {"model": "example.ticket"},
            content_type="application/json",
        )

        row = Watch.objects.get(user=worker)

        assert response.status_code == 201
        assert row.is_whole_model is True
        assert row.events == ["created", "updated", "deleted"]

    def test_the_status_says_what_covers_this_record(
        self,
        worker_client,
        worker,
        support_desk,
    ):
        watch(worker, Ticket)
        query = {
            "model": "example.ticket",
            "objectId": support_desk["login"].pk,
        }

        body = worker_client.get(STATUS, query).json()

        assert body["watching"] is False
        assert body["wholeModel"] is True

    def test_a_record_the_user_may_not_see_cannot_be_watched(
        self,
        auth_client,
        support_desk,
    ):
        response = auth_client.post(
            TOGGLE,
            {
                "model": "example.ticket",
                "objectId": support_desk["login"].pk,
            },
            content_type="application/json",
        )

        assert response.status_code == 403
        assert not Watch.objects.exists()

    def test_a_model_that_is_not_watchable_is_refused(
        self,
        auth_client,
        user,
    ):
        """``watchable = False`` is a refusal, not a hidden button."""
        from generic.tasks.models import TaskRun

        resource = site.get_resource(TaskRun)
        resource.watchable = False

        try:
            response = auth_client.post(
                TOGGLE,
                {"model": "generic.taskrun"},
                content_type="application/json",
            )
        finally:
            resource.watchable = True

        assert response.status_code == 403


class TestThePage:
    def test_it_lists_what_the_user_watches(
        self,
        reader_client,
        reader,
        support_desk,
    ):
        watch(reader, support_desk["login"])
        watch(reader, Ticket)

        page = reader_client.get(PAGE)
        rows = reader_client.get(WATCHES).json()

        assert page.status_code == 200
        assert len(rows) == 2
        assert {row["wholeModel"] for row in rows} == {True, False}
        assert rows[0]["url"]

    def test_the_format_is_changed_per_row(
        self,
        reader_client,
        reader,
        support_desk,
    ):
        row = watch(reader, support_desk["login"])

        response = reader_client.patch(
            f"{WATCHES}{row.pk}/",
            {"channels": ["mail"], "events": ["deleted"]},
            content_type="application/json",
        )

        row.refresh_from_db()

        assert response.status_code == 200
        assert row.channels == ["mail"]
        assert row.events == ["deleted"]

    def test_nonsense_is_dropped_rather_than_stored(
        self,
        reader_client,
        reader,
        support_desk,
    ):
        row = watch(reader, support_desk["login"])

        reader_client.patch(
            f"{WATCHES}{row.pk}/",
            {"channels": ["carrier-pigeon"], "events": ["exploded"]},
            content_type="application/json",
        )

        row.refresh_from_db()

        assert row.channels == []
        assert row.events == []

    def test_a_watch_saved_with_the_old_page_channel_follows_the_account(
        self,
        reader,
        support_desk,
    ):
        """ "event" was a channel before 1.0.0; a row holding it alone
        now follows the account's preference instead of telling nobody.
        """
        row = watch(reader, support_desk["login"])
        Watch.objects.filter(pk=row.pk).update(channels=["event"])
        row.refresh_from_db()

        assert row.resolve_channels() == ("notification",)

    def test_watches_are_private(self, reader_client, user, support_desk):
        watch(user, support_desk["login"])

        assert reader_client.get(WATCHES).json() == []

    def test_the_account_menu_offers_it(self, reader_client):
        rendered = reader_client.get("/account/").content.decode()

        assert PAGE in rendered


class TestTheHelpers:
    def test_watching_twice_is_watching_once(self, reader, support_desk):
        watch(reader, support_desk["login"])
        watch(reader, support_desk["login"])

        assert Watch.objects.count() == 1

    def test_is_watching_answers_for_both_kinds(self, reader, support_desk):
        watch(reader, Ticket)

        assert is_watching(reader, Ticket) is True
        assert is_watching(reader, support_desk["login"]) is False

    def test_unwatching_removes_it(self, reader, support_desk):
        watch(reader, support_desk["login"])

        assert unwatch(reader, support_desk["login"]) == 1
        assert not Watch.objects.exists()

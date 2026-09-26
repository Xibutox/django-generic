"""Announcing a restart: who hears about it, when, and what happens."""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone

from generic.events import bus
from generic.events.models import Notification, NotificationLevel
from generic.maintenance import scheduler
from generic.maintenance.models import RestartAnnouncement
from generic.maintenance.scheduler import (
    announce_restart,
    arm_pending,
    cancel_restart,
)
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

RESTART = "/api/generic/restart/"
PAGE = "/restart/"


@pytest.fixture
def sent():
    """Capture what reaches the channel layer."""
    with mock.patch.object(bus, "send_to_groups") as send:
        yield send


@pytest.fixture
def armed():
    """Keep the timers out of it: the moments are tested on their own."""
    with mock.patch.object(scheduler, "schedule") as schedule:
        yield schedule


@pytest.fixture
def operator(db):
    """Someone allowed to announce a restart."""
    user = UserFactory(username="operator")
    user.user_permissions.add(
        Permission.objects.get(codename="add_restartannouncement")
    )

    return user


def types_of(send) -> list[str]:
    return [call.args[1].type for call in send.call_args_list]


def in_minutes(minutes: int) -> datetime.datetime:
    return timezone.now() + datetime.timedelta(minutes=minutes)


def announce(**fields):
    fields.setdefault("scheduled_at", in_minutes(30))

    return announce_restart(**fields)


class TestAnnouncing:
    def test_everyone_is_notified(self, sent, armed, user):
        UserFactory(username="other")
        announce()

        assert Notification.objects.count() == 2
        assert Notification.objects.first().level == NotificationLevel.WARNING

    def test_an_inactive_account_is_left_alone(self, sent, armed, user):
        UserFactory(username="gone", is_active=False)
        announce()

        assert Notification.objects.count() == 1

    def test_each_person_is_written_to_in_their_language(
        self,
        sent,
        armed,
        user,
    ):
        from generic.accounts.models import UserPreferences

        french = UserFactory(username="francois")
        UserPreferences.objects.create(user=french, language="fr")

        announce(comment_en="Deploying.", comment_fr="Deploiement.")

        assert Notification.objects.get(user=french).body == "Deploiement."
        assert Notification.objects.get(user=user).body == "Deploying."

    def test_every_open_page_is_told(self, sent, armed, user):
        announce()

        assert "maintenance.announced" in types_of(sent)
        assert bus.broadcast_group() in sent.call_args.args[0]

    def test_the_payload_carries_both_comments(self, sent, armed, user):
        announcement = announce(comment_en="Short.", comment_fr="Court.")
        payload = announcement.as_client()

        assert payload["comment"] == {"en": "Short.", "fr": "Court."}
        assert payload["phase"] == "announced"
        assert payload["secondsUntil"] > 0

    def test_the_comment_follows_the_reader(self, sent, armed, user):
        announcement = announce(comment_en="Short.", comment_fr="Court.")

        assert announcement.comment_for("fr") == "Court."
        assert announcement.comment_for("fr-ca") == "Court."
        assert announcement.comment_for("en") == "Short."
        assert announcement.comment_for("") == "Short."


class TestTheMoments:
    def test_three_warnings_are_armed(self, sent, user, settings):
        announcement = RestartAnnouncement(scheduled_at=in_minutes(30))
        moments = scheduler._delays(announcement)

        assert [phase for _delay, phase in moments] == [
            "reminder",
            "imminent",
            "restarting",
        ]

    def test_a_warning_already_past_is_not_armed(self, sent, user):
        # Announced for twenty seconds' time: the minute-before warning
        # would have had to go out before the announcement itself.
        announcement = RestartAnnouncement(
            scheduled_at=timezone.now() + datetime.timedelta(seconds=20)
        )

        assert [
            phase for _delay, phase in scheduler._delays(announcement)
        ] == [
            "imminent",
            "restarting",
        ]

    def test_the_hour_arriving_tells_everyone(self, sent, armed, user):
        announcement = announce(is_manual=True)
        sent.reset_mock()

        scheduler._fire(announcement.pk, "reminder")

        assert types_of(sent) == ["maintenance.reminder"]

    def test_a_cancelled_restart_stays_quiet(self, sent, armed, user):
        announcement = announce()
        cancel_restart(announcement)
        sent.reset_mock()

        scheduler._fire(announcement.pk, "imminent")

        assert types_of(sent) == []


class TestCarryingItOut:
    def test_a_manual_operation_touches_nothing(self, sent, armed, user):
        announcement = announce(is_manual=True)

        with mock.patch.object(scheduler, "restart_process") as restart:
            scheduler._fire(announcement.pk, "restarting")

        announcement.refresh_from_db()
        assert restart.call_count == 0
        assert announcement.restarted_at is None
        assert "maintenance.restarting" in types_of(sent)

    def test_otherwise_the_server_restarts_itself(self, sent, armed, user):
        announcement = announce(is_manual=False)

        with mock.patch.object(scheduler, "restart_process") as restart:
            scheduler._fire(announcement.pk, "restarting")

        announcement.refresh_from_db()
        assert restart.call_count == 1
        assert announcement.restarted_at is not None

    def test_the_project_may_forbid_it_entirely(self, settings, caplog):
        settings.GENERIC = {"MAINTENANCE_RESTART": False}

        with mock.patch.object(scheduler.os, "kill") as kill:
            scheduler.restart_process()

        assert kill.call_count == 0

    def test_a_configured_command_is_what_runs(self, settings):
        settings.GENERIC = {
            "MAINTENANCE_RESTART_COMMAND": "systemctl restart desk",
        }

        with mock.patch.object(scheduler.subprocess, "Popen") as popen:
            scheduler.restart_process()

        assert popen.call_args.args[0] == ["systemctl", "restart", "desk"]


class TestTheEndpoint:
    def test_announcing_needs_the_permission(self, client, user):
        client.force_login(user)

        response = client.post(
            RESTART,
            {"scheduled_at": in_minutes(20).isoformat()},
            content_type="application/json",
        )

        assert response.status_code == 403
        assert not RestartAnnouncement.objects.exists()

    def test_an_operator_announces_one(self, client, operator, sent, armed):
        client.force_login(operator)

        response = client.post(
            RESTART,
            {
                "scheduled_at": in_minutes(20).isoformat(),
                "duration_minutes": 15,
                "is_manual": False,
                "comment_en": "Upgrading Postgres.",
                "comment_fr": "Mise a jour de Postgres.",
            },
            content_type="application/json",
        )

        assert response.status_code == 201, response.json()
        assert response.json()["durationMinutes"] == 15
        assert response.json()["isManual"] is False

        announcement = RestartAnnouncement.objects.get()
        assert announcement.created_by == operator

    def test_an_hour_already_past_is_refused(self, client, operator):
        client.force_login(operator)

        response = client.post(
            RESTART,
            {"scheduled_at": in_minutes(-5).isoformat()},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "scheduled_at" in response.json()

    def test_the_comments_have_a_default_worth_sending(
        self,
        client,
        operator,
        sent,
        armed,
    ):
        client.force_login(operator)

        client.post(
            RESTART,
            {"scheduled_at": in_minutes(20).isoformat()},
            content_type="application/json",
        )
        announcement = RestartAnnouncement.objects.get()

        assert "unavailable" in announcement.comment_en
        assert "indisponible" in announcement.comment_fr

    def test_anyone_signed_in_may_read_what_is_planned(
        self,
        client,
        user,
        operator,
        sent,
        armed,
    ):
        announce()
        client.force_login(user)

        body = client.get(RESTART).json()

        assert body["announcement"]["durationMinutes"] == 5
        assert body["canAnnounce"] is False

    def test_calling_it_off_needs_the_permission_too(
        self,
        client,
        user,
        sent,
        armed,
    ):
        announce()
        client.force_login(user)

        assert client.delete(RESTART).status_code == 403

    def test_an_operator_calls_it_off(self, client, operator, sent, armed):
        announce()
        client.force_login(operator)

        response = client.delete(RESTART)

        assert response.status_code == 200
        assert RestartAnnouncement.objects.current() is None
        assert "maintenance.cancelled" in types_of(sent)

    def test_the_form_describes_itself(self, client, operator):
        client.force_login(operator)

        schema = client.get(RESTART + "form-schema/").json()
        names = [field["name"] for field in schema["fields"]]

        assert names == [
            "scheduled_at",
            "duration_minutes",
            "is_manual",
            "comment_en",
            "comment_fr",
        ]


class TestThePage:
    def test_it_needs_the_permission(self, client, user):
        client.force_login(user)

        assert client.get(PAGE).status_code in (302, 403)

    def test_an_operator_opens_it(self, client, operator):
        client.force_login(operator)

        response = client.get(PAGE)

        config = response.context["form_config"]

        assert response.status_code == 200
        assert config["schemaUrl"].endswith("form-schema/")
        # A create posts to the collection, which is what the form asks
        # for; naming it "objectUrl" left the form with nowhere to post.
        assert config["collectionUrl"] == RESTART

    def test_a_page_opened_afterwards_still_shows_the_banner(
        self,
        client,
        user,
        sent,
        armed,
    ):
        announce()
        client.force_login(user)

        rendered = client.get("/account/").content.decode()

        assert "restart-banner" in rendered
        assert '"maintenance": {' in rendered.replace("&quot;", '"')


class TestComingBackUp:
    def test_a_fresh_process_arms_what_is_still_ahead(
        self,
        sent,
        armed,
        user,
    ):
        announce()
        past = RestartAnnouncement.objects.create(scheduled_at=in_minutes(-10))
        armed.reset_mock()

        count = arm_pending()

        assert count == 1
        assert armed.call_args.args[0].pk != past.pk


class TestTheTimerThread:
    def test_it_closes_its_own_connections(self):
        with (
            mock.patch.object(scheduler, "_fire") as fire,
            mock.patch.object(scheduler.connections, "close_all") as close,
        ):
            scheduler._fire_in_thread(7, "reminder")

        fire.assert_called_once_with(7, "reminder")
        assert close.call_count == 1

    def test_the_moment_itself_leaves_them_alone(self, sent, armed, user):
        """Run in a thread that is not the timer's - a test's, inside
        its transaction on Postgres - it must not close that thread's
        connection under it."""
        announcement = announce(is_manual=True)

        with mock.patch.object(scheduler.connections, "close_all") as close:
            scheduler._fire(announcement.pk, "reminder")

        assert close.call_count == 0

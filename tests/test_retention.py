"""Retention: the history, access log and notifications kept only as
long as the settings say - and, by default, the history and access log
kept whole."""

from __future__ import annotations

import datetime
import io

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from generic.access.models import AccessEntry
from generic.events.models import Notification
from generic.history import HistoryEntry
from generic.retention import TASK, apply, prune_notifications

pytestmark = pytest.mark.django_db

LONG_AGO = timezone.now() - datetime.timedelta(days=400)


@pytest.fixture
def old_and_new(django_user_model):
    """One old and one recent entry in each store."""
    user = django_user_model.objects.create_user(username="kept")
    kind = ContentType.objects.get_for_model(django_user_model)

    for at in (LONG_AGO, timezone.now()):
        HistoryEntry.objects.create(
            content_type=kind,
            object_id="0",
            label="probe",
            version=1 if at is LONG_AGO else 2,
            action=HistoryEntry.Action.UPDATED,
            at=at,
            values={},
        )
        AccessEntry.objects.create(
            content_type=kind,
            object_id=str(user.pk),
            record_key=f"auth.user:{user.pk}",
            user=user,
            at=at,
        )
        notification = Notification.objects.create(user=user, title="Hi")
        Notification.objects.filter(pk=notification.pk).update(created_at=at)

    return user


def counts() -> tuple[int, int, int]:
    return (
        HistoryEntry.objects.filter(label="probe").count(),
        AccessEntry.objects.count(),
        Notification.objects.count(),
    )


def test_by_default_only_the_notifications_go(old_and_new):
    # History and access log: kept whole, the evidence an audit asks
    # for; notifications: EVENTS_RETENTION_DAYS, 90.
    deleted = apply()

    assert deleted["history"] == 0
    assert deleted["access_log"] == 0
    assert deleted["notifications"] == 1
    assert counts() == (2, 2, 1)


@override_settings(
    GENERIC={
        "HISTORY_RETENTION_DAYS": 365,
        "ACCESS_LOG_RETENTION_DAYS": 365,
        "EVENTS_RETENTION_DAYS": 365,
    }
)
def test_each_store_keeps_its_own_period(old_and_new):
    deleted = apply()

    assert deleted["history"] == 1
    assert deleted["access_log"] == 1
    assert deleted["notifications"] == 1
    assert counts() == (1, 1, 1)


@override_settings(GENERIC={"EVENTS_RETENTION_DAYS": None})
def test_none_keeps_every_notification(old_and_new):
    assert prune_notifications() == 0
    assert Notification.objects.count() == 2


@override_settings(GENERIC={"ACCESS_LOG_RETENTION_DAYS": 30})
def test_the_command_applies_them(old_and_new):
    out = io.StringIO()

    call_command("apply_retention", stdout=out)

    assert AccessEntry.objects.count() == 1
    assert "1 access log" in out.getvalue()


def test_the_task_is_declared():
    from generic.tasks.registry import registry

    assert registry.get(TASK) is not None

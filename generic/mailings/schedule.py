"""When a mailing goes next: the only arithmetic of the feature.

Local time, in the project's ``TIME_ZONE``: *every weekday at 08:00*
means eight in the morning where the application lives, summer and
winter alike, which ``zoneinfo`` works out across the changes.
"""

from __future__ import annotations

import datetime
from typing import Any

from django.utils import timezone

#: Far enough to find the next occurrence of any frequency.
HORIZON_DAYS = 400


def matches(mailing: Any, day: datetime.date) -> bool:
    frequency = mailing.frequency

    if frequency == "daily":
        return True

    if frequency == "weekdays":
        return day.weekday() < 5

    if frequency == "weekly":
        return day.weekday() == int(mailing.weekday)

    if frequency == "monthly":
        return day.day == int(mailing.day_of_month)

    return False


def as_time(value: Any) -> datetime.time:
    if isinstance(value, datetime.time):
        return value

    return datetime.time.fromisoformat(str(value))


def next_run(mailing: Any, after: datetime.datetime | None = None) -> Any:
    """The first sending strictly after ``after`` (default: now)."""
    after = after or timezone.now()
    zone = timezone.get_default_timezone()
    day = timezone.localtime(after, zone).date()
    at = as_time(mailing.time)

    for _offset in range(HORIZON_DAYS):
        moment = datetime.datetime.combine(day, at).replace(tzinfo=zone)

        if moment > after and matches(mailing, day):
            return moment

        day += datetime.timedelta(days=1)

    return None

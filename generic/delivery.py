"""Saying one thing to some people, through the channels they chose.

Everything the application has to tell a person goes through here: a
task reporting how it went (:mod:`generic.tasks`), a record telling the
people watching it that it changed (:mod:`generic.watch`), a message an
administrator writes (:mod:`generic.events.messages`). What they share
is not the message - those are their own - but everything around it:
the names of the channels, writing each group in its own language, and
the rule that telling people must never be what breaks the thing being
reported on.

    deliver(
        users,
        channels=("notification", "mail"),
        message=lambda: (title, body, level),
        url=obj.get_absolute_url(),
    )

``message`` is called once per language, inside that language, so its
strings come out as the reader reads them rather than as the writer
wrote them.

Two channels, and that is all a person ever chooses between: a stored
notification - the bell, the notifications page, and a toast on every
page they have open, since storing one publishes it - and an e-mail.
The events of :mod:`generic.events` are not a third: they keep open
pages up to date and are addressed to no one.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from django.conf import settings
from django.core.mail import EmailMessage, send_mass_mail
from django.utils import translation

from generic.conf import generic_settings
from generic.events.bus import publish_notifications
from generic.events.models import Notification, NotificationLevel

logger = logging.getLogger(__name__)

#: Where a message can go. ``page`` delivers nothing - it names the
#: place that holds it anyway, so a declaration can say "only there".
CHANNELS = ("notification", "mail", "page")

#: Every channel that delivers something.
ALL = ("notification", "mail")

#: What ``UserPreferences.notification_channel`` means in channels, for
#: a subscription that has not said otherwise.
BY_PREFERENCE = {
    "in_app": ("notification",),
    "email": ("mail",),
    "both": ("notification", "mail"),
}


def by_language(users: Iterable[Any]) -> dict[str, list[Any]]:
    """The recipients grouped by the language each of them reads."""
    from generic.i18n import preferred_language

    groups: dict[str, list[Any]] = {}

    for user in users:
        groups.setdefault(preferred_language(user) or "", []).append(user)

    return groups


def preferred_channels(user: Any) -> tuple[str, ...]:
    """The channels this user asked for, on their account."""
    from generic.accounts.models import UserPreferences

    preferences = UserPreferences.for_user(user)

    return BY_PREFERENCE.get(
        preferences.notification_channel, ("notification",)
    )


def by_preference(users: Iterable[Any]) -> dict[tuple[str, ...], list[Any]]:
    """The recipients grouped by the channels each of them asked for.

    Fetch them with ``select_related("generic_preferences")`` and this
    costs no query at all, however many there are.
    """
    groups: dict[tuple[str, ...], list[Any]] = {}

    for user in users:
        groups.setdefault(preferred_channels(user), []).append(user)

    return groups


def absolute(url: str) -> str:
    """A link that still works outside the browser that made it."""
    base = str(generic_settings.SITE_URL or "").rstrip("/")

    return f"{base}{url}" if base and url else url


def notify(
    users: list[Any],
    title: str,
    body: str,
    level: int,
    url: str = "",
    content_object: Any = None,
) -> None:
    """One stored notification each, published as it is written."""
    created = Notification.objects.notify(
        users,
        title=title,
        body=body,
        level=level,
        url=url,
        content_object=content_object,
    )
    publish_notifications(created)


def mail(
    users: list[Any],
    title: str,
    body: str,
    url: str = "",
    context: str = "",
) -> None:
    """An e-mail each, to whoever has an address.

    Each one addressed to its reader alone, over one connection: a
    single mail to all of them would show every address to everybody.
    """
    addresses = [user.email for user in users if getattr(user, "email", "")]

    if not addresses:
        return

    link = absolute(url)
    text = f"{body}\n\n{link}" if link else body
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", None)

    try:
        # Nothing but the messages: the default mailer, errors raised.
        # fail_silently - even False, the default - is deprecated since
        # Django 6.1 and gone in 7.0, where passing it would fail every
        # mail into the handler below without a word.
        send_mass_mail(
            [(title, text, sender, [address]) for address in addresses]
        )
    except Exception:
        # A mail server that is down must not fail whatever was being
        # reported on: the page it points at holds the whole story.
        logger.exception("Could not send the mail for %s", context or title)


def mail_with_attachment(
    user: Any,
    *,
    subject: str,
    body: str,
    filename: str = "",
    content: bytes = b"",
    mimetype: str = "application/octet-stream",
    context: str = "",
) -> bool:
    """One e-mail to one reader, with a file when there is one.

    Through the default mailer, like :func:`mail` - ``MAILERS`` from
    Django 6.1, ``EMAIL_BACKEND`` before. A failure is logged and
    answered with False, never raised: the mailing reports it.
    """
    address = getattr(user, "email", "")

    if not address:
        return False

    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[address],
    )

    if filename:
        message.attach(filename, content, mimetype)

    try:
        message.send()
    except Exception:
        logger.exception("Could not send the mail for %s", context or subject)

        return False

    return True


def deliver(
    users: Iterable[Any],
    *,
    channels: Iterable[str],
    message: Callable[[], tuple[str, str, int]],
    url: str = "",
    content_object: Any = None,
    context: str = "",
) -> list[Any]:
    """Say it, once per channel, in each reader's own language.

    Returns the users it reached, so a caller can record how many.
    """
    chosen = tuple(channels)
    recipients = [user for user in users if user is not None]

    if not recipients or not any(name in ALL for name in chosen):
        return []

    for language, group in by_language(recipients).items():
        with translation.override(language or None):
            title, body, level = message()

            if "notification" in chosen:
                notify(group, title, body, level, url, content_object)

            if "mail" in chosen:
                mail(group, title, body, url, context)

    return recipients


__all__ = [
    "ALL",
    "BY_PREFERENCE",
    "CHANNELS",
    "NotificationLevel",
    "absolute",
    "by_language",
    "by_preference",
    "deliver",
    "mail_with_attachment",
    "mail",
    "notify",
    "preferred_channels",
]

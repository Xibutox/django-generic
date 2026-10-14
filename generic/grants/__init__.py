"""Rights given on request: exporting tables, downloading files.

By default everyone who may read a list exports it, and everyone who
may read a record downloads its files. A project that wants either to
be asked for names it in ``GENERIC["ACCESS_ON_REQUEST"]``::

    GENERIC = {"ACCESS_ON_REQUEST": ("export", "download")}

Each is then a permission - ``generic.export_rows``,
``generic.download_files`` - checked by every export and every file
download, and given like any other: to a person, to a group. Somebody
without it finds *Ask for permission* where the export menu or the
file's link would be; the request reaches every superuser and whoever
holds ``generic.validate_accessrequest``, who grant or refuse it on the
*Access requests* screen. Asking again reminds them, no more than once
an ``ACCESS_REQUEST_INTERVAL``.

From code::

    from generic import grants

    grants.may(request, "export")          # the rule every export obeys
    grants.ask(user, "download", message="For the audit")
    grants.grant(access_request, by=admin)
"""

from __future__ import annotations

import datetime
from typing import Any

#: Each right given on request, and the permission that is it.
PERMISSIONS = {
    "export": "generic.export_rows",
    "download": "generic.download_files",
}

#: Who decides: superusers, and whoever holds this.
VALIDATE = "generic.validate_accessrequest"


class TooSoon(Exception):
    """Asked again before ``ACCESS_REQUEST_INTERVAL`` went by."""

    def __init__(self, retry_at: datetime.datetime) -> None:
        super().__init__(retry_at)
        self.retry_at = retry_at


class AlreadyHeld(Exception):
    """Asked for a right already held."""


def gated() -> tuple[str, ...]:
    """The rights this project gives on request only."""
    from django.core.exceptions import ImproperlyConfigured

    from generic.conf import generic_settings

    kinds = tuple(generic_settings.ACCESS_ON_REQUEST or ())
    unknown = [kind for kind in kinds if kind not in PERMISSIONS]

    if unknown:
        raise ImproperlyConfigured(
            f"GENERIC['ACCESS_ON_REQUEST'] names {unknown!r}; it takes "
            f"{tuple(PERMISSIONS)!r}."
        )

    return kinds


def user_of(subject: Any) -> Any:
    """The user of a request, or the user itself."""
    return getattr(subject, "user", subject)


def may(subject: Any, kind: str) -> bool:
    """Whether ``subject`` - a request or a user - may ``kind``.

    Always, unless the project gives that right on request; then only
    with its permission.
    """
    if kind not in gated():
        return True

    user = user_of(subject)

    if not getattr(user, "is_authenticated", False):
        return False

    return bool(user.has_perm(PERMISSIONS[kind]))


def interval() -> datetime.timedelta:
    from generic.conf import generic_settings

    return datetime.timedelta(
        seconds=int(generic_settings.ACCESS_REQUEST_INTERVAL or 0)
    )


def validators(excluding: Any = None) -> Any:
    """Every active account that may decide on a request."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission
    from django.db.models import Q

    app_label, codename = VALIDATE.split(".")
    permission = Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).first()
    rule = Q(is_superuser=True)

    if permission is not None:
        rule |= Q(user_permissions=permission) | Q(
            groups__permissions=permission
        )

    users = get_user_model().objects.filter(rule, is_active=True)

    if excluding is not None:
        users = users.exclude(pk=excluding.pk)

    return users.distinct().select_related("generic_preferences")


def may_validate(user: Any) -> bool:
    return bool(
        getattr(user, "is_authenticated", False) and user.has_perm(VALIDATE)
    )


def latest(user: Any, kind: str) -> Any:
    """``user``'s last request for ``kind``, whatever became of it."""
    from generic.grants.models import AccessRequest

    return (
        AccessRequest.objects.filter(user=user, kind=kind)
        .order_by("-last_asked_at", "-pk")
        .first()
    )


def ask(
    user: Any,
    kind: str,
    *,
    message: str = "",
    page: str = "",
) -> tuple[Any, bool]:
    """``user`` asks for ``kind``. Returns the request and whether it is
    new - otherwise the open one was asked again, and the people who
    decide reminded.

    Raises :class:`AlreadyHeld` when there is nothing to ask for, and
    :class:`TooSoon` when they asked less than an
    ``ACCESS_REQUEST_INTERVAL`` ago: one reminder an hour is a
    reminder, one a minute is noise in everybody's notifications.
    """
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from django.utils import timezone

    from generic.grants.models import AccessRequest

    if kind not in gated():
        raise ValueError(f"{kind!r} is not given on request here.")

    if may(user, kind):
        raise AlreadyHeld(kind)

    with transaction.atomic():
        # One person's requests, one at a time: two clicks never make
        # two requests, nor two reminders.
        get_user_model().objects.select_for_update().filter(pk=user.pk).first()

        now = timezone.now()
        previous = latest(user, kind)

        if previous is not None:
            retry_at = previous.last_asked_at + interval()

            if now < retry_at:
                raise TooSoon(retry_at)

        if previous is not None and previous.is_pending:
            request = previous
            request.times_asked += 1
            request.last_asked_at = now

            if message:
                request.message = message[:2000]

            if page:
                request.page = page[:500]

            request.save()
            created = False
        else:
            request = AccessRequest.objects.create(
                user=user,
                kind=kind,
                message=message[:2000],
                page=page[:500],
                asked_at=now,
                last_asked_at=now,
            )
            created = True

        transaction.on_commit(lambda: tell_validators(request, created))

    return request, created


def tell_validators(request: Any, created: bool) -> list[Any]:
    """Tell everyone who may decide that ``request`` waits for them."""
    from django.utils import timezone
    from django.utils.translation import gettext

    from generic.conf import generic_settings
    from generic.delivery import deliver
    from generic.events.models import NotificationLevel
    from generic.sites.site import user_display_name

    name = user_display_name(request.user)

    def message() -> tuple[str, str, int]:
        kind = request.get_kind_display()

        if created:
            title = gettext("%(name)s asks: %(right)s") % {
                "name": name,
                "right": kind,
            }
        else:
            title = gettext("%(name)s asks again: %(right)s") % {
                "name": name,
                "right": kind,
            }

        body = request.message or gettext(
            "Grant or refuse it on the Access requests screen."
        )

        return title, body, NotificationLevel.WARNING

    reached = deliver(
        validators(excluding=request.user),
        channels=generic_settings.ACCESS_REQUEST_CHANNELS,
        message=message,
        url=detail_url(request),
        content_object=request,
        context=f"access request {request.pk}",
    )
    type(request).objects.filter(pk=request.pk).update(
        notified_at=timezone.now()
    )

    return reached


def detail_url(request: Any) -> str:
    from generic.sites import site

    resource = site.get_resource(type(request))

    if resource is None:
        return ""

    return resource.get_detail_url(request.pk) or ""


def decide(request: Any, *, by: Any, granted: bool) -> bool:
    """Grant or refuse ``request``. Returns False when it was decided
    already, or is ``by``'s own: nobody gives themselves a right."""
    from django.contrib.auth.models import Permission
    from django.db import transaction
    from django.utils import timezone

    from generic.grants.models import AccessRequest

    if not request.is_pending or request.user_id == by.pk:
        return False

    with transaction.atomic():
        updated = AccessRequest.objects.filter(
            pk=request.pk, status=AccessRequest.Status.PENDING
        ).update(
            status=(
                AccessRequest.Status.GRANTED
                if granted
                else AccessRequest.Status.REFUSED
            ),
            decided_by=by,
            decided_at=timezone.now(),
        )

        if not updated:
            return False

        request.refresh_from_db()

        if granted:
            app_label, codename = PERMISSIONS[request.kind].split(".")
            request.user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label=app_label, codename=codename
                )
            )

        transaction.on_commit(lambda: tell_requester(request))

    return True


def grant(request: Any, *, by: Any) -> bool:
    return decide(request, by=by, granted=True)


def refuse(request: Any, *, by: Any) -> bool:
    return decide(request, by=by, granted=False)


def tell_requester(request: Any) -> list[Any]:
    """Tell the person who asked what was decided."""
    from django.utils.translation import gettext

    from generic.conf import generic_settings
    from generic.delivery import deliver
    from generic.events.models import NotificationLevel

    granted = request.status == request.Status.GRANTED

    def message() -> tuple[str, str, int]:
        kind = request.get_kind_display()

        if granted:
            return (
                gettext("Granted: %(right)s") % {"right": kind},
                gettext("You may do it now; reload the page if needed."),
                NotificationLevel.SUCCESS,
            )

        return (
            gettext("Refused: %(right)s") % {"right": kind},
            gettext(
                "Your request was refused. Ask an administrator if you "
                "need to know why."
            ),
            NotificationLevel.WARNING,
        )

    return deliver(
        [request.user],
        channels=generic_settings.ACCESS_REQUEST_CHANNELS,
        message=message,
        url=request.page if request.page.startswith("/") else "",
        context=f"access request {request.pk}",
    )


def state(user: Any) -> list[dict[str, Any]]:
    """Each right given on request, as ``user`` stands with it."""
    from generic.grants.models import AccessRequest

    rows = []

    for kind in gated():
        held = may(user, kind)
        previous = None if held else latest(user, kind)
        retry_at = previous.last_asked_at + interval() if previous else None
        rows.append(
            {
                "kind": kind,
                "label": str(AccessRequest.Kind(kind).label),
                "held": held,
                "status": previous.status if previous else "",
                "askedAt": (
                    previous.last_asked_at.isoformat() if previous else None
                ),
                "retryAt": retry_at.isoformat() if retry_at else None,
            }
        )

    return rows


#: The settings holding each disclaimer.
DISCLAIMER_SETTINGS = {
    "export": "EXPORT_DISCLAIMER",
    "download": "DOWNLOAD_DISCLAIMER",
}


def disclaimer(kind: str) -> dict[str, str] | None:
    """The reminder shown before ``kind``, as the reader reads it.

    ``EXPORT_DISCLAIMER`` or ``DOWNLOAD_DISCLAIMER``: ``None`` (none),
    a text, or ``{"title", "text", "checkbox"}`` - each a plain or a
    ``gettext_lazy`` string, read here in the request's language.
    """
    from django.core.exceptions import ImproperlyConfigured
    from django.utils.encoding import force_str
    from django.utils.translation import gettext

    from generic.conf import generic_settings

    name = DISCLAIMER_SETTINGS[kind]
    value = getattr(generic_settings, name)

    if not value:
        return None

    if not isinstance(value, dict):
        value = {"text": value}

    unknown = set(value) - {"title", "text", "checkbox"}

    if unknown or not value.get("text"):
        raise ImproperlyConfigured(
            f"GENERIC[{name!r}] is a text, or a dict with 'text' and "
            f"optionally 'title' and 'checkbox'."
        )

    return {
        "title": force_str(
            value.get("title")
            or (
                gettext("Before you export")
                if kind == "export"
                else gettext("Before you download")
            )
        ),
        "text": force_str(value["text"]),
        "checkbox": force_str(
            value.get("checkbox")
            or gettext(
                "I have read this reminder and will handle the data "
                "accordingly."
            )
        ),
    }


def client(request: Any) -> dict[str, Any] | None:
    """What every page's script knows: the rights given on request it
    lacks, where to ask, and the reminders shown before an export or a
    download. ``None`` when there is none of that."""
    kinds = gated()
    user = user_of(request)

    if not getattr(user, "is_authenticated", False):
        return None

    disclaimers = {
        kind: text
        for kind in DISCLAIMER_SETTINGS
        if (text := disclaimer(kind)) is not None
    }

    if not kinds and not disclaimers:
        return None

    from django.urls import NoReverseMatch, reverse

    try:
        url = reverse("generic:access-requests") if kinds else ""
    except NoReverseMatch:
        url = ""

    return {
        "url": url,
        "missing": [kind for kind in kinds if not may(user, kind)],
        "disclaimers": disclaimers,
    }


__all__ = [
    "PERMISSIONS",
    "VALIDATE",
    "AlreadyHeld",
    "TooSoon",
    "ask",
    "client",
    "decide",
    "disclaimer",
    "gated",
    "grant",
    "may",
    "may_validate",
    "refuse",
    "state",
    "validators",
]

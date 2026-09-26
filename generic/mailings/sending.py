"""Sending one mailing: as each recipient, the resource's own export.

No rows are read here. For every recipient a request signed in as them
asks the resource's endpoint - the rows for the count, the export for
the file - with the mailing's state turned back into the parameters
the table itself would send. The column whitelist, ``get_queryset``,
the view permission and ``EXPORT_MAX_ROWS`` therefore decide, exactly
as they do on the page.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any
from urllib.parse import urlencode

from django.utils import timezone, translation
from django.utils.translation import gettext, ngettext

from generic.conf import generic_settings

logger = logging.getLogger(__name__)

#: What each format is sent as.
MIMETYPES = {
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    "csv": "text/csv",
}


class MailingProblem(Exception):
    """The mailing itself cannot be sent: its table, its layout."""


@dataclasses.dataclass
class Outcome:
    """What one sending did."""

    sent: int = 0
    empty: int = 0
    refused: int = 0
    failed: int = 0

    def describe(self) -> str:
        return gettext(
            "%(sent)s sent, %(empty)s empty, %(refused)s not allowed, "
            "%(failed)s failed"
        ) % dataclasses.asdict(self)


def resource_for(table: str) -> Any:
    """The resource a table key names, if it may be mailed."""
    from generic.sites import site

    for resource in site.get_resources():
        if resource.state_key == table:
            return resource if getattr(resource, "mailing", True) else None

    return None


def parameters(state: dict[str, Any]) -> dict[str, str]:
    """A saved table state, as the endpoint's query parameters."""
    state = state if isinstance(state, dict) else {}
    params: dict[str, str] = {}

    filters = state.get("filters")

    if isinstance(filters, dict) and filters.get("conditions"):
        params["filters"] = json.dumps(filters)

    search = state.get("search")

    if isinstance(search, str) and search.strip():
        params["search"] = search.strip()

    order = [
        ("-" if str(direction).lower() == "desc" else "") + str(column)
        for column, direction in (
            entry
            for entry in state.get("order") or ()
            if isinstance(entry, (list, tuple)) and len(entry) == 2
        )
    ]

    if order:
        params["ordering"] = ",".join(order)

    columns = [str(name) for name in state.get("columns") or () if name]

    if columns:
        params["columns"] = ",".join(columns)

    return params


def call(resource: Any, user: Any, action: str, params: dict[str, Any]) -> Any:
    """One request to the resource's endpoint, signed in as ``user``."""
    from django.test import RequestFactory
    from rest_framework.test import force_authenticate

    request = RequestFactory().get(resource.get_api_url(), params)
    force_authenticate(request, user=user)
    request.user = user
    view = resource.get_viewset_class().as_view({"get": action})

    return view(request)


def count_rows(resource: Any, user: Any, params: dict[str, Any]) -> int:
    """How many rows ``user`` would see, or raise ``MailingProblem``."""
    response = call(
        resource,
        user,
        "list",
        {**params, "draw": 1, "start": 0, "length": 1},
    )

    if response.status_code == 403:
        raise PermissionError

    if response.status_code != 200:
        detail = getattr(response, "data", None)
        raise MailingProblem(
            json.dumps(detail, default=str) if detail else str(response)
        )

    response.render()

    return int(json.loads(response.content).get("recordsFiltered", 0))


def export(
    resource: Any,
    user: Any,
    params: dict[str, Any],
    file_format: str,
) -> bytes:
    action = "export_csv" if file_format == "csv" else "export"
    response = call(resource, user, action, params)

    if response.status_code != 200:
        raise MailingProblem(str(getattr(response, "data", "")))

    return b"".join(response.streaming_content)


def check(mailing: Any, user: Any) -> None:
    """Refuse a mailing that could not be sent, before it is saved."""
    resource = resource_for(mailing.table)

    if resource is None:
        raise MailingProblem(gettext("This list cannot be sent by e-mail."))

    try:
        count_rows(resource, user, parameters(mailing.state))
    except PermissionError:
        raise MailingProblem(gettext("You may not see this list."))


def list_link(resource: Any, state: dict[str, Any]) -> str:
    """The list, filtered as the mailing is, as an absolute address."""
    from generic.delivery import absolute

    url = resource.get_list_url()
    filters = parameters(state).get("filters")

    if filters:
        url = f"{url}?{urlencode({'filters': filters})}"

    return absolute(url)


def send_to(
    mailing: Any,
    resource: Any,
    user: Any,
    outcome: Outcome,
) -> None:
    from generic.i18n import preferred_language

    params = parameters(mailing.state)

    with translation.override(preferred_language(user) or None):
        try:
            count = count_rows(resource, user, params)
        except PermissionError:
            outcome.refused += 1

            return

        if not count and not mailing.send_when_empty:
            outcome.empty += 1

            return

        content = export(resource, user, params, mailing.format)
        link = list_link(resource, mailing.state)
        lines = [
            ngettext(
                "%(count)s row of %(list)s, as of %(when)s.",
                "%(count)s rows of %(list)s, as of %(when)s.",
                count,
            )
            % {
                "count": count,
                "list": resource.get_label_plural(),
                "when": timezone.localtime().strftime("%Y-%m-%d %H:%M"),
            }
        ]
        name = (
            f"{resource.model_name}-{timezone.localdate():%Y%m%d}."
            f"{mailing.format}"
        )
        limit = generic_settings.MAILING_MAX_ATTACHMENT_SIZE
        attach = not limit or len(content) <= limit

        if not attach:
            lines.append(
                gettext(
                    "The file is too large to attach: open the list to "
                    "export it."
                )
            )

        if link:
            lines.append(gettext("The list: %(url)s") % {"url": link})

        if mail_with_attachment(
            user,
            subject=mailing.name,
            body="\n\n".join(lines),
            filename=name if attach else "",
            content=content if attach else b"",
            mimetype=MIMETYPES.get(mailing.format, "application/octet-stream"),
            context=f"mailing {mailing.pk}",
        ):
            outcome.sent += 1
        else:
            outcome.failed += 1


def mail_with_attachment(user: Any, **kwargs: Any) -> bool:
    from generic.delivery import mail_with_attachment as send

    return send(user, **kwargs)


def send(mailing: Any) -> Outcome:
    """Send ``mailing`` now, to each recipient as themselves.

    A table that is gone or a layout that no longer reads pauses the
    mailing and tells its owner, rather than failing every time.
    """
    outcome = Outcome()
    resource = resource_for(mailing.table)

    try:
        if resource is None:
            raise MailingProblem(
                gettext("This list cannot be sent by e-mail any more.")
            )

        for user in mailing.recipients():
            send_to(mailing, resource, user, outcome)
    except MailingProblem as problem:
        pause(mailing, str(problem))

        return outcome

    mailing.last_sent_at = timezone.now()
    mailing.last_error = ""
    mailing.save(update_fields=["last_sent_at", "last_error"])

    return outcome


def pause(mailing: Any, problem: str) -> None:
    """Stop a mailing that cannot work, and say so to its owner."""
    from generic.delivery import deliver
    from generic.events.models import NotificationLevel

    mailing.is_active = False
    mailing.last_error = problem
    mailing.save(update_fields=["is_active", "last_error"])
    logger.warning("Mailing %s paused: %s", mailing.pk, problem)

    if mailing.owner is None:
        return

    from generic.sites import site

    resource = site.get_resource(type(mailing))
    url = resource.get_change_url(mailing.pk) if resource else ""

    deliver(
        [mailing.owner],
        channels=("notification",),
        url=url,
        context=f"mailing {mailing.pk}",
        message=lambda: (
            gettext("Mailing paused: %(name)s") % {"name": mailing.name},
            gettext(
                "It could not be sent and is paused until it is "
                "corrected: %(problem)s"
            )
            % {"problem": problem},
            NotificationLevel.WARNING,
        ),
    )

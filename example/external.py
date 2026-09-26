"""The services the desk relies on, as their status API reports them.

This stands for a client of an external API. A real one would be::

    response = requests.get(STATUS_API_URL, timeout=5)
    response.raise_for_status()
    return response.json()["services"]

- and what comes back is the same thing as below: a list of dicts, dates
and times as text, a list where a service is in several regions, ``null``
where there is nothing to say. The framework reads it as it is; see
``ServiceResource`` in resources.py.

The answer is kept a minute in Django's cache: the table asks for its
rows on every page, sort and filter, and an external API is slow, has
quotas, and is sometimes down.
"""

from __future__ import annotations

import datetime
from typing import Any

from django.core.cache import cache
from django.utils import timezone

CACHE_KEY = "example.external.services"
CACHE_SECONDS = 60

#: id, name, provider, category, status, uptime over 90 days, response
#: time in ms, regions, critical for the desk, last incident (days ago),
#: checked (minutes ago), description.
SERVICES: tuple[tuple[Any, ...], ...] = (
    (
        "mailroom",
        "Mailroom",
        "Mailroom Ltd",
        "email",
        "operational",
        99.98,
        120,
        ["eu-west", "us-east"],
        True,
        26,
        2,
        "Sends every e-mail the desk writes, replies to customers "
        "included.",
    ),
    (
        "paylane",
        "Paylane",
        "Paylane Payments",
        "payments",
        "degraded",
        99.71,
        340,
        ["eu-west"],
        True,
        0,
        1,
        "Takes the payment of every paid support plan.\nCard payments "
        "are slower than usual; nothing is lost.",
    ),
    (
        "callbridge",
        "CallBridge",
        "CallBridge Telecom",
        "telephony",
        "operational",
        99.93,
        95,
        ["eu-west", "eu-central"],
        True,
        41,
        3,
        "The desk's telephone line and its call queue.",
    ),
    (
        "codehub",
        "CodeHub",
        "CodeHub Inc.",
        "code",
        "operational",
        99.99,
        210,
        ["us-east", "us-west"],
        False,
        63,
        5,
        "Where the product's code and its issue tracker live.",
    ),
    (
        "cloudnest",
        "CloudNest Compute",
        "CloudNest",
        "hosting",
        "partial_outage",
        99.40,
        560,
        ["eu-central"],
        True,
        0,
        1,
        "Runs the customer portal.\nSome requests from Central Europe "
        "time out while the provider moves traffic.",
    ),
    (
        "cloudnest-storage",
        "CloudNest Storage",
        "CloudNest",
        "hosting",
        "operational",
        99.97,
        140,
        ["eu-central", "eu-west"],
        False,
        12,
        4,
        "Keeps the attachments customers send with their tickets.",
    ),
    (
        "pingwatch",
        "PingWatch",
        "PingWatch",
        "monitoring",
        "operational",
        100.0,
        60,
        ["eu-west", "us-east", "ap-south"],
        False,
        None,
        1,
        "Watches the portal from three continents and pages whoever "
        "is on call.",
    ),
    (
        "chatterbox",
        "Chatterbox",
        "Chatterbox Apps",
        "chat",
        "maintenance",
        99.90,
        180,
        ["eu-west"],
        False,
        3,
        8,
        "The chat window on the website. Planned maintenance until " "noon.",
    ),
    (
        "smsgate",
        "SMSGate",
        "SMSGate",
        "telephony",
        "major_outage",
        98.20,
        None,
        ["eu-west"],
        True,
        0,
        2,
        "Sends the text messages telling customers their ticket was "
        "answered.\nNothing goes out at the moment.",
    ),
    (
        "ledgerly",
        "Ledgerly",
        "Ledgerly",
        "finance",
        "operational",
        99.95,
        230,
        ["eu-west"],
        False,
        90,
        15,
        "The accounts the billable hours end up in.",
    ),
    (
        "signpost",
        "Signpost",
        "Signpost Documents",
        "documents",
        "operational",
        99.89,
        300,
        ["us-east", "eu-west"],
        False,
        18,
        6,
        "Contracts and support plans, signed online.",
    ),
    (
        "mapkit",
        "MapKit",
        "MapKit Geo",
        "maps",
        "degraded",
        99.60,
        410,
        ["us-west", "ap-south"],
        False,
        1,
        4,
        "Shows where an on-site intervention is.",
    ),
    (
        "idgate",
        "IDGate",
        "IDGate Identity",
        "identity",
        "operational",
        99.995,
        80,
        ["eu-west", "us-east"],
        True,
        120,
        2,
        "Signs the agents in.",
    ),
    (
        "backupbay",
        "BackupBay",
        "BackupBay",
        "hosting",
        "operational",
        99.99,
        900,
        ["eu-central"],
        False,
        7,
        30,
        "Keeps a copy of everything, every night.",
    ),
)


def iso(moment: datetime.datetime) -> str:
    """A time as an API writes it: UTC, with a Z."""
    return (
        moment.astimezone(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def fetch_services() -> list[dict[str, Any]]:
    """What the status API answers, as it would arrive: JSON."""
    now = timezone.now()
    today = timezone.localdate()
    rows = []

    for (
        key,
        name,
        provider,
        category,
        status,
        uptime,
        response_ms,
        regions,
        critical,
        incident_days,
        checked_minutes,
        description,
    ) in SERVICES:
        rows.append(
            {
                "id": key,
                "name": name,
                "provider": provider,
                "category": category,
                "status": status,
                "uptime_90d": uptime,
                "response_ms": response_ms,
                "regions": list(regions),
                "critical": critical,
                "last_incident": (
                    (
                        today - datetime.timedelta(days=incident_days)
                    ).isoformat()
                    if incident_days is not None
                    else None
                ),
                "checked_at": iso(
                    now - datetime.timedelta(minutes=checked_minutes)
                ),
                "status_page": f"https://status.{key}.example.com/",
                "description": description,
            }
        )

    return rows


def services() -> list[dict[str, Any]]:
    """The services, from the cache while it is fresh."""
    return cache.get_or_set(CACHE_KEY, fetch_services, CACHE_SECONDS)


# ---------------------------------------------------------------------
# Incidents: the same API's other list
# ---------------------------------------------------------------------
#
# ``GET /incidents`` - every incident, each naming its service by id. A
# real API often answers ``GET /services/<id>/incidents`` as well;
# ``incidents_of`` stands for that one.

INCIDENTS_CACHE_KEY = "example.external.incidents"

#: id, service, title, severity, status, started (hours ago), lasted
#: (minutes; None while it goes on), summary.
INCIDENTS: tuple[tuple[Any, ...], ...] = (
    (
        "inc-2051",
        "smsgate",
        "No text messages sent",
        "critical",
        "investigating",
        1,
        None,
        "Every message is refused by the carrier's gateway. Customers "
        "are not told their ticket was answered; e-mail still is.",
    ),
    (
        "inc-2050",
        "paylane",
        "Card payments slower than usual",
        "minor",
        "investigating",
        2,
        None,
        "A payment takes up to twenty seconds to be confirmed. None "
        "fails, none is charged twice.",
    ),
    (
        "inc-2049",
        "cloudnest",
        "Timeouts from Central Europe",
        "major",
        "identified",
        5,
        None,
        "One data centre answers slowly; traffic is being moved to the "
        "others. The customer portal times out for some visitors.",
    ),
    (
        "inc-2047",
        "mapkit",
        "Map tiles slow to load",
        "minor",
        "monitoring",
        26,
        None,
        "A fix is deployed; the provider watches the load times before "
        "closing the incident.",
    ),
    (
        "inc-2044",
        "chatterbox",
        "Messages delivered twice",
        "minor",
        "resolved",
        3 * 24 + 4,
        40,
        "Some chat messages reached the agent twice. Nothing was lost.",
    ),
    (
        "inc-2041",
        "backupbay",
        "Nightly backup late",
        "minor",
        "resolved",
        7 * 24 + 6,
        240,
        "The backup finished at ten in the morning instead of four.",
    ),
    (
        "inc-2038",
        "cloudnest-storage",
        "Slow uploads",
        "minor",
        "resolved",
        12 * 24 + 2,
        55,
        "Attachments over 10 MB took minutes to upload.",
    ),
    (
        "inc-2036",
        "signpost",
        "Signing links expired early",
        "minor",
        "resolved",
        18 * 24 + 3,
        90,
        "Links sent for signature expired after an hour instead of a "
        "week; they were sent again.",
    ),
    (
        "inc-2033",
        "cloudnest",
        "A host restarted",
        "minor",
        "resolved",
        20 * 24 + 1,
        15,
        "The portal was unavailable for a quarter of an hour.",
    ),
    (
        "inc-2031",
        "mailroom",
        "Outgoing e-mail delayed",
        "minor",
        "resolved",
        26 * 24 + 5,
        48,
        "Replies to customers left up to half an hour late.",
    ),
    (
        "inc-2027",
        "smsgate",
        "Delivery delayed",
        "minor",
        "resolved",
        30 * 24 + 8,
        120,
        "Text messages arrived up to two hours late.",
    ),
    (
        "inc-2024",
        "callbridge",
        "Calls dropped after two minutes",
        "major",
        "resolved",
        41 * 24 + 3,
        72,
        "Every call was cut after two minutes. The desk called the "
        "customers back.",
    ),
    (
        "inc-2022",
        "paylane",
        "Payment page unavailable",
        "major",
        "resolved",
        45 * 24 + 9,
        35,
        "Nobody could renew a support plan for half an hour.",
    ),
    (
        "inc-2019",
        "codehub",
        "Issue tracker read-only",
        "minor",
        "resolved",
        63 * 24 + 2,
        25,
        "Issues could be read, not written.",
    ),
    (
        "inc-2015",
        "mailroom",
        "Bounces from one provider",
        "minor",
        "resolved",
        70 * 24 + 7,
        180,
        "One large e-mail provider refused the desk's messages for "
        "three hours.",
    ),
    (
        "inc-2011",
        "ledgerly",
        "Bank sync late",
        "minor",
        "resolved",
        90 * 24 + 4,
        300,
        "The day's payments reached the accounts in the evening.",
    ),
    (
        "inc-2004",
        "idgate",
        "Sign-in refused for some accounts",
        "critical",
        "resolved",
        120 * 24 + 1,
        20,
        "Agents with a new password could not sign in.",
    ),
)


def fetch_incidents() -> list[dict[str, Any]]:
    """What ``GET /incidents`` answers: JSON, times as text."""
    now = timezone.now()
    names = {row[0]: row[1] for row in SERVICES}
    rows = []

    for (
        key,
        service,
        title,
        severity,
        status,
        hours_ago,
        minutes,
        summary,
    ) in INCIDENTS:
        started = now - datetime.timedelta(hours=hours_ago)

        rows.append(
            {
                "id": key,
                "service": service,
                "service_name": names[service],
                "title": title,
                "severity": severity,
                "status": status,
                "started_at": iso(started),
                "resolved_at": (
                    iso(started + datetime.timedelta(minutes=minutes))
                    if minutes is not None
                    else None
                ),
                "duration_minutes": minutes,
                "summary": summary,
            }
        )

    return rows


def incidents() -> list[dict[str, Any]]:
    """Every incident, from the cache while it is fresh."""
    return cache.get_or_set(
        INCIDENTS_CACHE_KEY, fetch_incidents, CACHE_SECONDS
    )


def incidents_of(service: str) -> list[dict[str, Any]]:
    """What ``GET /services/<id>/incidents`` answers."""
    return [row for row in incidents() if row["service"] == service]


# ---------------------------------------------------------------------
# Runbooks: one long text per service, asked for on its own
# ---------------------------------------------------------------------
#
# ``GET /services/<id>/runbook`` - what the desk does when the service
# fails. Too long for the list, and only read on its own page: it is
# fetched when that page opens, not with every row of the table.

#: What differs from one kind of service to the next.
RUNBOOK_ADVICE = {
    "email": (
        "Replies stay in the outbox and leave on their own once the "
        "service is back: do not send them twice. For anything urgent, "
        "call the customer instead."
    ),
    "payments": (
        "Nobody is charged twice: a payment that did not go through is "
        "simply not there. Tell customers renewing a plan that their "
        "support continues meanwhile, and note their ticket so the "
        "renewal is checked the next day."
    ),
    "telephony": (
        "Put the outage message on the website's contact page and move "
        "the on-call agent to the chat. Customers who called are in the "
        "missed-call list once the line is back: call each of them."
    ),
    "hosting": (
        "The customer portal may be slow or down. Answer tickets by "
        "e-mail with the information the portal would have shown, and "
        "never promise a time the provider has not given."
    ),
}

RUNBOOK_DEFAULT = (
    "The desk keeps working without it. Mention the outage in the "
    "tickets it affects, and nowhere else."
)


def runbook_of(service: str) -> dict[str, Any]:
    """What ``GET /services/<id>/runbook`` answers."""
    row = next(item for item in SERVICES if item[0] == service)
    name, provider, category = row[1], row[2], row[3]
    critical = row[8]
    paragraphs = [
        f"{name} is provided by {provider}. When it fails, the first "
        f"thing to know is whether it is them or us: open their status "
        f"page, then the list of external services - a service whose "
        f"status is not Operational is theirs to fix.",
        (
            f"{name} is critical for the desk. The agent on call "
            f"announces the outage on the team channel within fifteen "
            f"minutes, with what customers will notice and what they "
            f"should do meanwhile, then opens a ticket to follow it."
            if critical
            else f"{name} is not critical for the desk. Nobody needs to "
            f"be woken up: the outage is followed during office hours."
        ),
        RUNBOOK_ADVICE.get(category, RUNBOOK_DEFAULT),
        f"Write to {provider} only through their status page or their "
        f"support portal, quoting the incident number when there is one. "
        f"Keep every message they send in the ticket: the monthly "
        f"review of the providers is written from it.",
        "When the service is back, check it yourself before saying so, "
        "then close the ticket with the time it came back and the "
        "customers it affected. The incident stays among the service's "
        "incidents, with its duration.",
    ]

    return {"runbook": "\n\n".join(paragraphs)}

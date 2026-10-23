"""The key figures the old planner served, at the same addresses and in
the same JSON, computed from the logbook's tasks and time.

    GET planner/api/kpi/?date=MM-YYYY     a month (this one by default)
    GET planner/api/kpi/year/?date=YYYY   a year (this one by default)

- ``cout``: closed tasks with an estimate, closed in the period - the
  time logged on them against the estimate, in days of 24 hours, as the
  old planner counted;
- ``delai``: the tickets (FNC) opened in the period, the mean number of
  days from their opening to their closing, by criticality;
- ``metier``: how many people used DES and COMET (``sync_kpi``);
- ``qualite``: how many tickets were opened, by criticality.

The criticalities keep the old planner's names as keys - Mineure,
Majeure, Bloquant - whatever the language, so whoever reads the JSON
reads the same keys.

The old endpoints asked for no sign-in. These neither, unless
``LOGBOOK_KPI_TOKEN`` is set: then a request must carry it, as
``Authorization: Token <token>`` or ``?token=<token>``.
"""

from __future__ import annotations

import datetime
import hmac
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from planner.models import KpiRecord, Task, TimeEntry

#: The old planner's names for the criticalities, in its order.
CRITICALITY_KEYS = (
    (Task.Criticality.MINOR, "Mineure"),
    (Task.Criticality.MAJOR, "Majeure"),
    (Task.Criticality.CRITICAL, "Bloquant"),
)

SECONDS_PER_DAY = 86400

BAD_DATE = {"erreur": "Date passée en argument incohérente"}


def month_view(request: Any) -> HttpResponse:
    refused = check_token(request)

    if refused is not None:
        return refused

    today = timezone.localdate()
    text = request.GET.get("date", today.strftime("%m-%Y"))

    try:
        start = datetime.date(
            year=int(text.split("-")[1]), month=int(text.split("-")[0]), day=1
        )
    except Exception:
        return JsonResponse(BAD_DATE)

    period = {"year": start.year, "month": start.month}

    return JsonResponse(
        figures(start.strftime("%m-%Y"), period, KpiRecord.Period.MONTH, start)
    )


def year_view(request: Any) -> HttpResponse:
    refused = check_token(request)

    if refused is not None:
        return refused

    today = timezone.localdate()
    text = request.GET.get("date", today.strftime("%Y"))

    try:
        start = datetime.date(year=int(text), month=1, day=1)
    except Exception:
        return JsonResponse(BAD_DATE)

    return JsonResponse(
        figures(
            start.strftime("%Y"),
            {"year": start.year},
            KpiRecord.Period.YEAR,
            start,
        )
    )


def check_token(request: Any) -> HttpResponse | None:
    expected = getattr(settings, "LOGBOOK_KPI_TOKEN", "") or ""

    if not expected:
        return None

    header = request.headers.get("Authorization", "")
    given = (
        header[len("Token ") :]
        if header.startswith("Token ")
        else request.GET.get("token", "")
    )

    if hmac.compare_digest(given.encode(), expected.encode()):
        return None

    return JsonResponse({"erreur": "Jeton absent ou invalide"}, status=401)


def within(prefix: str, period: dict[str, int]) -> Q:
    """Records whose ``prefix`` date falls in the period, in the local
    time zone: ``created_at__year=2026, created_at__month=10``."""
    return Q(**{f"{prefix}__{part}": value for part, value in period.items()})


def figures(
    label: str, period: dict[str, int], kind: str, start: datetime.date
) -> dict[str, Any]:
    record = KpiRecord.objects.filter(period=kind, date=start).first()
    tickets = Task.objects.filter(within("created_at", period), kind="FNC")
    counts: dict[str, int] = {}
    delays: dict[str, float] = {}

    for value, key in CRITICALITY_KEYS:
        some = tickets.filter(criticality=value)
        counts[key] = some.count()
        delays[key] = mean_delay(some)

    closed = (
        Task.objects.filter(within("done_at", period), status="done")
        .exclude(estimate=None)
        .exclude(estimate=0)
    )
    estimated = closed.aggregate(total=Sum("estimate"))["total"] or Decimal(
        "0"
    )
    spent = TimeEntry.objects.filter(task__in=closed).aggregate(
        total=Sum("hours")
    )["total"] or Decimal("0")
    days_spent = float(spent) * 3600 / SECONDS_PER_DAY
    days_estimated = float(estimated) * 3600 / SECONDS_PER_DAY

    if estimated:
        ratio = round(
            ((days_spent - days_estimated) / days_estimated) * 100, ndigits=2
        )
    else:
        ratio = 0

    return {
        "date": label,
        "cout": {
            "description": (
                "Ecart moyen entre le nombre de jours chiffrés vs réalisés"
            ),
            "ecart_jour": round(days_spent - days_estimated, 2),
            "pourcentage_depassement": ratio,
        },
        "delai": {
            "description": "Temps de traitement moyen des non conformités",
            **delays,
        },
        "metier": {
            "description": "Taux d'utilisation des outils",
            "des": {
                "description": "Nombre de connexion unique sur DES",
                "valeur": record.des_users if record else 0,
            },
            "comet": {
                "description": "Nombre de connexion unique sur COMET",
                "valeur": record.comet_users if record else 0,
            },
        },
        "qualite": {
            "description": "Nombre d'ouvertures de tickets de non-conformité",
            **counts,
        },
    }


def mean_delay(tickets: Any) -> float:
    """The mean number of days from opening to closing, counted on the
    local calendar as the old planner's dates were; 0 when none closed."""
    lengths = [
        (timezone.localdate(done) - timezone.localdate(opened)).days
        for opened, done in tickets.exclude(done_at=None).values_list(
            "created_at", "done_at"
        )
    ]

    if not lengths:
        return 0

    return round(sum(lengths) / len(lengths), 2)

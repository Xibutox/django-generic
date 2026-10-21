"""Read how many people used COMET and DES this month and this year,
and keep it for the key figures (planner/kpi.py) - what the old
planner's Celery task ``synchro_kpi`` did. Run it as often as the
figures should move: cron, the Windows task scheduler, or the
``scheduler`` service of compose.yaml.

    python manage.py sync_kpi
"""

from __future__ import annotations

from typing import Any

import urllib3
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from planner import tools
from planner.models import KpiRecord


class Command(BaseCommand):
    help = "Read the COMET and DES usage figures (tools' status/)."

    def handle(self, *args: Any, **options: Any) -> None:
        if tools.verify() is False:
            # Asked for: the old planner's internal certificates.
            urllib3.disable_warnings()

        try:
            with tools.comet() as comet:
                comet_status = comet.status()

            with tools.des() as des:
                des_status = des.status()
        except (tools.ToolError, OSError) as error:
            raise CommandError(str(error)) from error

        today = timezone.localdate()

        for period, date, key in (
            (KpiRecord.Period.MONTH, today.replace(day=1), "month"),
            (KpiRecord.Period.YEAR, today.replace(month=1, day=1), "year"),
        ):
            KpiRecord.objects.update_or_create(
                period=period,
                date=date,
                defaults={
                    "des_users": des_status.get(f"users_logged_this_{key}"),
                    "comet_users": comet_status.get(
                        f"users_logged_this_{key}"
                    ),
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"COMET {comet_status.get('users_logged_this_month')} / "
                f"DES {des_status.get('users_logged_this_month')} this month."
            )
        )

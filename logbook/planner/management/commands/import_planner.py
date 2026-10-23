"""Import the old planner's export (migration/export_planner.py) into
the logbook. Safe to run again: what was imported before is found by
its old id and updated, nothing is doubled.

    python manage.py import_planner export.json --user bastien
    python manage.py import_planner export.json --user bastien --dry-run

What goes where:

- Activite -> Project; Direction, Imputation -> the same; Etiquette ->
  Label; MatriceImputation -> the distribution matrix (replaced);
  KPIHistory / KPIYearHistory -> tool usage.
- Tache -> Task: a non-conformity is an FNC with its criticality
  (Mineure, Majeure, Bloquant -> minor, major, critical), any other a
  DM (``--other-kind AUT`` for AUT); Ouvert, En cours, Ferme -> to do,
  in progress, done; Basse, Moyenne, Haute -> low, normal, high; the
  opening date and the closing date are kept, so the key figures stay
  what they were. Each task is numbered (FNC-0001...) in the order it
  was opened.
- Emargement -> TimeEntry: the old entries have a day and a length but
  no hours and no person: they are laid one after the other from
  ``--start`` (08:00) on their day, given to ``--user``, and verified
  (``--unverified`` leaves them to check).

At the end the logbook's key figures are compared with the old API's
answers the export carries, month by month and year by year.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from planner import kpi
from planner.models import (
    Direction,
    Imputation,
    ImputationShare,
    KpiRecord,
    Label,
    Project,
    Task,
    TimeEntry,
)

STATUS = {1: Task.Status.TODO, 2: Task.Status.DOING, 3: Task.Status.DONE}
PRIORITY = {
    1: Task.Priority.LOW,
    2: Task.Priority.NORMAL,
    3: Task.Priority.HIGH,
}
CRITICALITY = {
    1: Task.Criticality.MINOR,
    2: Task.Criticality.MAJOR,
    3: Task.Criticality.CRITICAL,
}


class DryRun(Exception):
    """Raised to roll the import back after its report."""


class Command(BaseCommand):
    help = "Import the old planner's export (export_planner.py)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("path", help="The JSON file the export wrote.")
        parser.add_argument(
            "--user",
            required=True,
            help="Who the old time entries belong to (a username).",
        )
        parser.add_argument(
            "--other-kind",
            choices=("DM", "AUT"),
            default="DM",
            help="The kind of a task that is not a non-conformity.",
        )
        parser.add_argument(
            "--start",
            default="08:00",
            help="When each day's first entry starts (HH:MM).",
        )
        parser.add_argument(
            "--unverified",
            action="store_true",
            help="Leave the imported time to verify.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Do it all, report, then roll everything back.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path = Path(options["path"])

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise CommandError(f"{path}: {error}") from error

        if data.get("format") != "planner-export":
            raise CommandError(f"{path} is not an export_planner.py file.")

        try:
            self.user = get_user_model().objects.get(username=options["user"])
        except get_user_model().DoesNotExist:
            raise CommandError(
                f"No user {options['user']!r}: create it first "
                f"(manage.py createsuperuser)."
            ) from None

        try:
            hour, minute = (int(x) for x in options["start"].split(":"))
            self.start = datetime.time(hour, minute)
        except ValueError:
            raise CommandError("--start is HH:MM.") from None

        self.other_kind = options["other_kind"]
        self.verify = not options["unverified"]
        self.warnings: list[str] = []

        try:
            with transaction.atomic():
                self.run(data)
                self.report(data)

                if options["dry_run"]:
                    raise DryRun()
        except DryRun:
            self.stdout.write(self.style.WARNING("Dry run: nothing was kept."))

    # -- the import -------------------------------------------------------

    def run(self, data: dict[str, Any]) -> None:
        projects = {
            row["id"]: Project.objects.get_or_create(name=row["nom"])[0]
            for row in data.get("activites", [])
        }
        directions = {
            row["id"]: Direction.objects.get_or_create(name=row["nom"])[0]
            for row in data.get("directions", [])
        }
        imputations = {}

        for row in data.get("imputations", []):
            imputations[row["id"]] = Imputation.objects.update_or_create(
                number=row["numero_imputation"],
                defaults={
                    "name": row["nom"],
                    "direction": directions[row["direction"]],
                },
            )[0]

        labels = {
            row["id"]: Label.objects.get_or_create(name=row["nom"])[0]
            for row in data.get("etiquettes", [])
        }

        # The matrix is the old planner's: the same lines, no others.
        ImputationShare.objects.exclude(
            number__in=[row["numero"] for row in data.get("matrice", [])]
        ).delete()

        for row in data.get("matrice", []):
            ImputationShare.objects.update_or_create(
                number=row["numero"],
                defaults={"percentage": row["pourcentage"]},
            )

        for key, period in (
            ("kpi_mois", KpiRecord.Period.MONTH),
            ("kpi_annee", KpiRecord.Period.YEAR),
        ):
            for row in data.get(key, []):
                KpiRecord.objects.update_or_create(
                    period=period,
                    date=datetime.date.fromisoformat(row["date"]),
                    defaults={
                        "des_users": row["metier_des"],
                        "comet_users": row["metier_comet"],
                    },
                )

        tasks = self.tasks(data, projects, imputations, labels)
        self.time(data, tasks)

    def tasks(
        self,
        data: dict[str, Any],
        projects: dict[int, Project],
        imputations: dict[int, Imputation],
        labels: dict[int, Label],
    ) -> dict[int, Task]:
        found = {}
        rows = sorted(
            data.get("taches", []),
            key=lambda row: (row["date_ouverture"] or "9999", row["id"]),
        )

        for row in rows:
            task = Task.objects.filter(legacy_id=row["id"]).first() or Task(
                legacy_id=row["id"]
            )
            ticket = bool(row["non_conformite"])
            task.kind = Task.Kind.FNC if ticket else self.other_kind
            task.criticality = (
                CRITICALITY.get(row["severite"], Task.Criticality.MINOR)
                if ticket
                else ""
            )
            task.title = row["nom"][:200]
            task.description = row["description"] or ""
            task.status = STATUS.get(row["statut"], Task.Status.TODO)
            task.priority = PRIORITY.get(row["priorite"], Task.Priority.LOW)
            task.estimate = (
                (Decimal(row["temps_estime"]) / 3600).quantize(Decimal("0.01"))
                if row["temps_estime"] is not None
                else None
            )
            task.due_on = (
                datetime.date.fromisoformat(row["date_echeance"])
                if row["date_echeance"]
                else None
            )
            task.imputation = imputations.get(row["imputation"])

            if task.assignee_id is None:
                task.assignee = self.user

            task.save()
            task.projects.set(
                [projects[row["activite"]]]
                if row["activite"] in projects
                else []
            )
            task.labels.set(
                [labels[key] for key in row["etiquettes"] if key in labels]
            )

            # The dates the key figures read: the old ones, not today.
            opened = self.noon(row["date_ouverture"]) or task.created_at
            closed = None

            if task.status == Task.Status.DONE:
                closed = self.noon(row["date_fermeture"])
            elif row["date_fermeture"]:
                self.warnings.append(
                    f"{row['nom']!r}: a closing date but not closed - "
                    f"the date is not kept."
                )

            Task.objects.filter(pk=task.pk).update(
                created_at=opened, done_at=closed
            )
            found[row["id"]] = task

        return found

    def time(self, data: dict[str, Any], tasks: dict[int, Task]) -> None:
        days: dict[str, list[dict[str, Any]]] = {}

        for row in data.get("emargements", []):
            days.setdefault(row["date"], []).append(row)

        now = timezone.now()

        for day, rows in sorted(days.items()):
            rows.sort(key=lambda row: row["id"])
            total = sum(row["temps_passe"] or 0 for row in rows)
            first = datetime.datetime.combine(
                datetime.date.fromisoformat(day), self.start
            )

            # A day longer than what is left after the start begins at
            # midnight, so that it stays on its day.
            if total > (24 * 3600) - (
                self.start.hour * 3600 + self.start.minute * 60
            ):
                first = first.replace(hour=0, minute=0)

                if total > 24 * 3600:
                    self.warnings.append(
                        f"{day}: {total / 3600:.2f} h logged, more than a day."
                    )

            moment = timezone.make_aware(first)

            for row in rows:
                task = tasks.get(row["tache"])

                if task is None:
                    self.warnings.append(
                        f"Entry {row['id']}: its task {row['tache']} is not "
                        f"in the export - skipped."
                    )
                    continue

                length = datetime.timedelta(seconds=row["temps_passe"] or 0)
                entry = TimeEntry.objects.filter(
                    legacy_id=row["id"]
                ).first() or TimeEntry(legacy_id=row["id"], user=self.user)
                entry.task = task
                entry.started_at = moment
                entry.ended_at = moment + length
                entry.comment = row["commentaire"] or ""

                if self.verify and not entry.verified:
                    entry.verified = True
                    entry.verified_by = self.user
                    entry.verified_at = now

                entry.save()
                moment += length

    @staticmethod
    def noon(value: str | None) -> datetime.datetime | None:
        """A day as a moment: noon, so no time zone moves it."""
        if not value:
            return None

        return timezone.make_aware(
            datetime.datetime.combine(
                datetime.date.fromisoformat(value), datetime.time(12)
            )
        )

    # -- the report -------------------------------------------------------

    def report(self, data: dict[str, Any]) -> None:
        legacy_tasks = Task.objects.exclude(legacy_id=None)
        legacy_time = TimeEntry.objects.exclude(legacy_id=None)
        seconds = sum(
            (entry.ended_at - entry.started_at).total_seconds()
            for entry in legacy_time.only("started_at", "ended_at")
        )
        expected = data.get("totaux", {})

        self.stdout.write(
            f"Tasks: {legacy_tasks.count()} (export: "
            f"{expected.get('taches', '?')}), time entries: "
            f"{legacy_time.count()} (export: "
            f"{expected.get('emargements', '?')}), hours: "
            f"{seconds / 3600:.2f} (export: "
            f"{(expected.get('secondes') or 0) / 3600:.2f})."
        )

        for warning in self.warnings:
            self.stdout.write(self.style.WARNING(warning))

        answers = data.get("kpi_reponses") or {}
        differences = 0
        compared = 0

        for key, kind, parse in (
            ("mois", KpiRecord.Period.MONTH, month_period),
            ("annee", KpiRecord.Period.YEAR, year_period),
        ):
            for label, old in (answers.get(key) or {}).items():
                period, start = parse(label)
                new = json.loads(
                    json.dumps(kpi.figures(label, period, kind, start))
                )
                compared += 1

                if new != old:
                    differences += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"Key figures {label} differ:\n"
                            f"  old {json.dumps(old, ensure_ascii=False)}\n"
                            f"  new {json.dumps(new, ensure_ascii=False)}"
                        )
                    )

        if compared:
            style = self.style.ERROR if differences else self.style.SUCCESS
            self.stdout.write(
                style(
                    f"Key figures: {compared - differences} of {compared} "
                    f"periods identical to the old API."
                )
            )


def month_period(label: str) -> tuple[dict[str, int], datetime.date]:
    month, year = (int(part) for part in label.split("-"))

    return {"year": year, "month": month}, datetime.date(year, month, 1)


def year_period(label: str) -> tuple[dict[str, int], datetime.date]:
    return {"year": int(label)}, datetime.date(int(label), 1, 1)

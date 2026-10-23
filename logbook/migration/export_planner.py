"""Export everything the old planner holds into one JSON file, for the
logbook's ``import_planner`` command. It only reads.

Run it inside the old project, next to its manage.py - in its Docker
container, for instance:

    docker cp export_planner.py <container>:/app/export_planner.py
    docker exec <container> python export_planner.py /app/planner_export.json
    docker cp <container>:/app/planner_export.json .

The settings module is config.settings unless DJANGO_SETTINGS_MODULE
says otherwise. Durations are written in seconds, dates as YYYY-MM-DD.
"""

import datetime
import json
import os
import sys


def seconds(value):
    return None if value is None else int(round(value.total_seconds()))


def day(value):
    return None if value is None else value.isoformat()


def answers(tasks):
    """The old API's answers, month by month and year by year, from the
    first task to today: the import checks the logbook gives the same."""
    from django.test import RequestFactory

    try:
        from planner.api import KpiMonthView, KpiYearView
    except ImportError:
        return {}

    dates = [
        datetime.date.fromisoformat(value)
        for task in tasks
        for value in (task["date_ouverture"], task["date_fermeture"])
        if value
    ]

    if not dates:
        return {}

    factory = RequestFactory()
    today = datetime.date.today()
    month = min(dates).replace(day=1)
    found = {"mois": {}, "annee": {}}

    while month <= today:
        key = month.strftime("%m-%Y")
        view = KpiMonthView.as_view()
        response = view(factory.get("/", {"date": key}))
        found["mois"][key] = json.loads(response.content)
        month = (month + datetime.timedelta(days=32)).replace(day=1)

    for year in range(min(dates).year, today.year + 1):
        view = KpiYearView.as_view()
        response = view(factory.get("/", {"date": str(year)}))
        found["annee"][str(year)] = json.loads(response.content)

    return found


def main(path):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    sys.path.insert(0, os.getcwd())

    import django

    django.setup()

    from django.apps import apps

    def model(name):
        return apps.get_model("planner", name)

    Tache = model("Tache")
    Emargement = model("Emargement")

    tasks = []

    for task in Tache.objects.order_by("pk").prefetch_related("etiquettes"):
        tasks.append(
            {
                "id": task.pk,
                "nom": task.nom,
                "activite": task.activite_id,
                "imputation": task.imputation_id,
                "etiquettes": sorted(e.pk for e in task.etiquettes.all()),
                "temps_estime": seconds(task.temps_estime),
                "priorite": task.priorite,
                "statut": task.statut,
                "date_ouverture": day(task.date_ouverture),
                "date_echeance": day(task.date_echeance),
                "date_fermeture": day(task.date_fermeture),
                "description": task.description,
                "non_conformite": task.non_conformite,
                "severite": task.severite,
            }
        )

    entries = [
        {
            "id": entry.pk,
            "date": day(entry.date),
            "temps_passe": seconds(entry.temps_passe),
            "commentaire": entry.commentaire,
            "tache": entry.tache_id,
        }
        for entry in Emargement.objects.order_by("date", "pk")
    ]

    def history(name):
        return [
            {
                "date": day(row.date),
                "metier_des": row.metier_des,
                "metier_comet": row.metier_comet,
            }
            for row in model(name).objects.order_by("date", "pk")
        ]

    data = {
        "format": "planner-export",
        "version": 1,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "activites": [
            {"id": row.pk, "nom": row.nom}
            for row in model("Activite").objects.order_by("pk")
        ],
        "directions": [
            {"id": row.pk, "nom": row.nom}
            for row in model("Direction").objects.order_by("pk")
        ],
        "etiquettes": [
            {"id": row.pk, "nom": row.nom}
            for row in model("Etiquette").objects.order_by("pk")
        ],
        "imputations": [
            {
                "id": row.pk,
                "nom": row.nom,
                "numero_imputation": row.numero_imputation,
                "direction": row.direction_id,
            }
            for row in model("Imputation").objects.order_by("pk")
        ],
        "taches": tasks,
        "emargements": entries,
        "matrice": [
            {"numero": row.numero, "pourcentage": row.pourcentage}
            for row in model("MatriceImputation").objects.order_by("numero")
        ],
        "kpi_mois": history("KPIHistory"),
        "kpi_annee": history("KPIYearHistory"),
    }
    data["kpi_reponses"] = answers(tasks)
    data["totaux"] = {
        "taches": len(tasks),
        "emargements": len(entries),
        "secondes": sum(entry["temps_passe"] or 0 for entry in entries),
    }

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)

    print(
        f"{len(tasks)} taches, {len(entries)} emargements "
        f"({data['totaux']['secondes'] / 3600:.2f} h) -> {path}"
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "planner_export.json")

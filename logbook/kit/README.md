# The logbook, to replace the old planner

Everything the logbook needs to run on its own machine, and the two
scripts that move the old planner's data into it:

| File | What it is |
| --- | --- |
| `export_planner.py` | Script 1, run in the **old** planner: writes all its data to one JSON file. It only reads. |
| `logbook/` | The logbook: the site, the `planner` app, and script 2, `manage.py import_planner`. |
| `vendor/` | The framework, django-generic, as a wheel: nothing is fetched from GitHub. |
| `compose.yaml`, `Dockerfile`, `docker-entrypoint.sh` | The site (gunicorn), its PostgreSQL 18, and the scheduler that reads the COMET and DES figures. |
| `.env.example` | Every setting. Copy to `.env`. |

The old API is kept at the same addresses and answers the same JSON:

    GET /planner/api/kpi/?date=MM-YYYY
    GET /planner/api/kpi/year/?date=YYYY

## 1. Export the old planner

On the machine that runs the old planner, with its container up
(`docker ps` gives its name):

```bash
docker cp export_planner.py <container>:/app/export_planner.py
docker exec <container> python export_planner.py /app/planner_export.json
docker cp <container>:/app/planner_export.json .
```

It prints what it wrote: tasks, time entries, hours. The file also
carries the old API's answers for every month and year, so the import
can check the logbook gives the same figures.

## 2. Start the logbook

```bash
cp .env.example .env      # then fill it in: secret key, passwords, COMET/DES
docker compose up --build -d
```

The site is on http://localhost:4243 (`LOGBOOK_PORT`). The first start
creates the tables and the administrator named in `.env`.

## 3. Import

Put the export in `import/`, beside this file, then try it without
keeping anything:

```bash
mkdir -p import && cp planner_export.json import/
docker compose run --rm web python manage.py import_planner /import/planner_export.json --user admin --dry-run
```

It reports the tasks, entries and hours against the export's totals,
and the key figures month by month against the old API's. When it says
`Key figures: N of N periods identical to the old API.`, run it for real
(the same line without `--dry-run`). It can be run again: what it
imported before is updated, not doubled.

The choices it makes, and how to change them:

- an activity becomes a **project**; a task keeps its opening and
  closing dates, so the figures stay what they were;
- a non-conformity becomes an **FNC** with its criticality (Mineure,
  Majeure, Bloquant -> minor, major, critical); any other task a **DM**
  (`--other-kind AUT` makes them AUT);
- the old time entries have a day and a length but no hour and no
  person: they are given to `--user`, laid one after the other from
  08:00 (`--start 07:30`), and verified (`--unverified` leaves them to
  check);
- imputations, directions, the distribution matrix and the COMET/DES
  history come as they are.

## 4. Switch over

- Point whatever reads the old API at the logbook. To require a token,
  set `LOGBOOK_KPI_TOKEN` in `.env`; callers then send
  `Authorization: Token <value>` (or `?token=<value>`).
- The `scheduler` service reads COMET and DES every hour
  (`KPI_SYNC_EVERY`), as the old Celery task did. Once by hand:
  `docker compose run --rm web python manage.py sync_kpi`.
- The old planner's COMET and DES passwords were written in its code
  (`planner/interfaces/`): change them, and put the new ones in `.env`
  only.
- In the logbook: *Time > Time entries > Export imputations* is the old
  Excel export (7.4-hour days, same sheets); *Time > Workdays* is the
  old 8-hour calendar.

## Without Docker

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cd logbook
python manage.py migrate
python manage.py import_planner ../planner_export.json --user admin
python manage.py runserver
```

SQLite then, unless `POSTGRES_DB` is set.

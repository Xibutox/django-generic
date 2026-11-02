# syntax=docker/dockerfile:1
#
# The logbook in a container, from this checkout: the framework
# installed from the repository, the logbook on top, its demo, then
# runserver. For trying it on this machine, like the logbook itself;
# the standalone install, with PostgreSQL and gunicorn, is kit/.
#
# Built from the repository's root, which holds the framework:
#
#   docker compose -f logbook/compose.yaml up --build

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_DB_PATH=/data/db.sqlite3

# The framework with its Excel export (the imputation export), and
# requests, which sync_kpi reads COMET and DES with.
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY generic/ ./generic/
# The versions CI tested (scripts/lock.py).
COPY requirements/constraints.txt ./
RUN pip install -c constraints.txt ".[export]" "requests>=2.31" \
    && rm -rf /src

# The database lives in /data, a volume, so it outlives the container.
RUN useradd --create-home app && mkdir /data && chown app /data

WORKDIR /app
COPY logbook/ ./

USER app
EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_planner && python manage.py runserver 0.0.0.0:8000"]

# syntax=docker/dockerfile:1
#
# {{ title }}: one file, five images.
#
#   --target dev      the project with its test tools; compose.dev.yml
#                     mounts the source over /app and runs runserver.
#   --target prod     (the default) the application, run by Daphne as
#                     a user that owns nothing it could damage.
#   --target proxy    Caddy with the collected static files: HTTPS, the
#                     static files, the rest handed to Daphne.
#   --target backup   the encrypted backups and their restore: the
#                     Postgres client of the server's own version, and
#                     GnuPG (docker/backup/).
#
# The base images are pinned to a minor version through the build
# arguments below (ISO/IEC 27002 8.19, 8.32): raise them on purpose,
# rebuild, test, then deploy. `docker compose build --pull` takes the
# latest patch of each - the security fixes - on every release.

ARG PYTHON_IMAGE=python:3.13-slim
ARG POSTGRES_IMAGE=postgres:17
ARG CADDY_IMAGE=caddy:2.10-alpine

ARG BEAT_PACKAGES="django-celery-beat>=2.6"
ARG BEAT_DEPENDENCIES="cron-descriptor>=1.4,<2 python-crontab>=3.0 django-timezone-field>=7.0 tzdata"

# -- base ---------------------------------------------------------------

FROM ${PYTHON_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN useradd --create-home --uid 1000 app

# A Unicode font for the wiki's PDF, and the latest security fixes of
# the base image's own packages.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# The dependencies from the requirements and the framework's wheel
# alone, so a change to the code reuses this layer.
COPY requirements.txt requirements-dev.txt pyproject.toml README.md ./
COPY vendor/ ./vendor/
COPY {{ project }}/__init__.py ./{{ project }}/__init__.py
COPY {{ app }}/__init__.py ./{{ app }}/__init__.py

# -- dev ----------------------------------------------------------------

FROM base AS dev

ARG BEAT_PACKAGES
ARG BEAT_DEPENDENCIES

RUN pip install -r requirements-dev.txt \
    && pip install --no-deps ${BEAT_PACKAGES} \
    && pip install ${BEAT_DEPENDENCIES}

COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# -- app: the production install and its static files -------------------

FROM base AS app

ARG BEAT_PACKAGES
ARG BEAT_DEPENDENCIES

RUN pip install -r requirements.txt \
    && pip install --no-deps ${BEAT_PACKAGES} \
    && pip install ${BEAT_DEPENDENCIES}

COPY . .

# Collected with the production settings, hashed names. Placeholders
# stand in for the secrets, in this command only.
RUN DJANGO_SETTINGS_MODULE={{ project }}.settings.prod \
    DJANGO_SECRET_KEY=collectstatic-only \
    DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_URL=sqlite:////tmp/collectstatic.sqlite3 \
    REDIS_URL=redis://localhost:6379/0 \
    python manage.py collectstatic --noinput \
    && rm -f /tmp/collectstatic.sqlite3

# The only folders the application writes: its log and the uploaded
# files, both volumes. The code itself stays root's, read-only to it.
RUN mkdir -p /app/logs /app/media && chown app:app /app/logs /app/media

# -- proxy --------------------------------------------------------------

FROM ${CADDY_IMAGE} AS proxy

COPY docker/Caddyfile /etc/caddy/Caddyfile
COPY --from=app /app/staticfiles /srv/static

# -- backup -------------------------------------------------------------
#
# The same Postgres image as the database: pg_dump and pg_restore of
# its own version, and GnuPG already in it - nothing downloaded.

FROM ${POSTGRES_IMAGE} AS backup

COPY --chmod=755 docker/backup/backup.sh docker/backup/restore.sh \
     docker/backup/common.sh /usr/local/bin/
ENV GNUPGHOME=/tmp/gnupg
WORKDIR /backups
ENTRYPOINT ["/usr/local/bin/backup.sh"]
CMD ["schedule"]

# -- prod: the default target -------------------------------------------

FROM app AS prod

ENV DJANGO_SETTINGS_MODULE={{ project }}.settings.prod

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), 2)"]

CMD ["daphne", "--bind", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "{{ project }}.asgi:application"]

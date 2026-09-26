# syntax=docker/dockerfile:1
#
# One file, three images:
#
#   --target dev     every extra, the test tools and the Debug Toolbar.
#                    docker-compose.dev.yml mounts the source over /app
#                    and runs runserver, which reloads on every change.
#   --target proxy   Caddy with the collected static files: HTTPS, the
#                    static files, the rest handed to Daphne.
#   --target prod    (the default) the application alone - no test
#                    tools, no toolbar, the static files collected with
#                    hashed names - run by Daphne as a user that owns
#                    nothing it could damage.

ARG PYTHON_VERSION=3.12

# The scheduler behind the Schedules pages. Its own metadata still pins
# Django below 6.1, so it is installed without its dependencies, and
# those it does need are installed by name. Declared before the first
# stage and again in each that uses it: an ARG stops at its stage.
ARG BEAT_PACKAGES="cron-descriptor>=1.4 python-crontab>=3.0 django-timezone-field>=7.0 tzdata"

# -- base: what both Python images share --------------------------------

FROM python:${PYTHON_VERSION}-slim AS base

# PYTHONPATH puts the source tree first: the framework and the project
# are read from /app, whatever the dependency install put in
# site-packages.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN useradd --create-home --uid 1000 app

# The dependencies are installed from the metadata alone - pyproject,
# the files it names, and a stub of the package holding the version - so
# a change to the source reuses this layer.
COPY pyproject.toml README.md LICENSE ./
COPY generic/__init__.py ./generic/__init__.py

# -- dev ----------------------------------------------------------------

FROM base AS dev

ARG BEAT_PACKAGES

RUN pip install ".[export,import,api,events,tasks,postgres,wiki,dev]" \
    && pip install --no-deps "django-celery-beat>=2.6" \
    && pip install ${BEAT_PACKAGES}

# In the image too, so it runs the suite without a mount (CI does);
# docker-compose.dev.yml mounts the working copy over it.
COPY --chown=app:app . .

# The suite measures coverage by default, and writes its data where
# this user can: /app is root's in the image, and mounted, it is the
# host user's, who is not always uid 1000.
ENV COVERAGE_FILE=/tmp/.coverage

USER app
# 5678: debugpy, for `python debug.py --listen 0.0.0.0:5678`.
EXPOSE 8000 5678

# runserver, not Daphne: the same ASGI server (daphne is the first
# installed app), plus the reloader and the static files.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# -- app: the production install and its static files -------------------

FROM base AS app

ARG BEAT_PACKAGES

RUN pip install ".[export,import,api,events,tasks,postgres,wiki]" \
    && pip install --no-deps "django-celery-beat>=2.6" \
    && pip install ${BEAT_PACKAGES}

COPY . .

# Collected now, with the production settings, so every name carries a
# hash of its content. collectstatic reaches neither the database nor
# Redis: placeholders stand in for the secrets, in this command only.
RUN DJANGO_SETTINGS_MODULE=example_project.settings.prod \
    DJANGO_SECRET_KEY=collectstatic-only \
    DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_URL=sqlite:////tmp/collectstatic.sqlite3 \
    REDIS_URL=redis://localhost:6379/0 \
    python manage.py collectstatic --noinput \
    && rm -f /tmp/collectstatic.sqlite3

# -- proxy --------------------------------------------------------------

FROM caddy:2-alpine AS proxy

COPY docker/Caddyfile /etc/caddy/Caddyfile
COPY --from=app /app/staticfiles /srv/static

# -- prod: the default target -------------------------------------------

FROM app AS prod

# For every command run in this image - the web server, Celery, a
# `manage.py` typed into it - not only for the ones that default to it.
ENV DJANGO_SETTINGS_MODULE=example_project.settings.prod

USER app
EXPOSE 8000

# Daphne: HTTP and the WebSocket events. --proxy-headers takes the
# client's address from the proxy in front rather than the proxy's own.
CMD ["daphne", "--bind", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "example_project.asgi:application"]

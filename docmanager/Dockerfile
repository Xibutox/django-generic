# syntax=docker/dockerfile:1
#
# The document manager in containers, two images from one file:
#
#   --target web     the application, run by gunicorn (plain WSGI), on
#                    PostgreSQL, with Redis as its cache
#   --target nginx   nginx in front: HTTPS with a certificate it signs
#                    itself on its first start, the static files, the
#                    rest handed to gunicorn
#
# Built from the repository's root, which holds the framework:
#
#   docker compose -f docmanager/compose.yaml up --build

# -- web ----------------------------------------------------------------

FROM python:3.12-slim AS web

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_MEDIA_ROOT=/data/media \
    DJANGO_STATIC_ROOT=/app/staticfiles

# A Unicode font for the wiki's PDF and the stamps: without one they
# fall back on Latin-1 (docs/wiki.md#pdf).
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# The framework with the export and wiki extras, as the README installs
# it, and postgres (psycopg); the document manager's own libraries;
# gunicorn to serve it and the Redis client for the cache.
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY generic/ ./generic/
COPY docmanager/requirements.txt ./
RUN pip install ".[export,wiki,postgres]" -r requirements.txt \
    "gunicorn>=22" "redis>=5.0" \
    && rm -rf /src

WORKDIR /app
COPY docmanager/ ./
RUN python manage.py collectstatic --noinput

# The documents' files are in /data/media, a folder of the host mounted
# there (compose.yaml). The entrypoint, as root, hands it to this user
# - a folder Docker made on Linux is root's - then runs the command as
# app, who owns nothing else it could damage.
RUN useradd --create-home app && mkdir -p /data/media && chown app /data/media
COPY --chmod=755 docmanager/docker-entrypoint.sh /usr/local/bin/
ENTRYPOINT ["docker-entrypoint.sh"]

EXPOSE 8000

# The tables, then the demo (DEMO_DATA) or the first administrator
# (DJANGO_SUPERUSER_*), then gunicorn: docker-start.sh.
CMD ["sh", "docker-start.sh"]

# -- nginx --------------------------------------------------------------

# The Debian image, not Alpine: it comes with openssl, which signs the
# certificate (nginx/10-self-signed.sh).
FROM nginx:stable AS nginx

COPY docmanager/nginx/default.conf.template /etc/nginx/templates/
COPY --chmod=755 docmanager/nginx/10-self-signed.sh /docker-entrypoint.d/
COPY --from=web /app/staticfiles /srv/static

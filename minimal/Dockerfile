# syntax=docker/dockerfile:1
#
# The minimal example in a container: the framework installed from this
# checkout, the example on top, runserver. For local use, like the
# example itself; the production image is ../docker/Dockerfile.
#
# Built from the repository's root, which holds the framework:
#
#   docker compose -f minimal/compose.yaml up --build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_DB_PATH=/data/db.sqlite3 \
    DJANGO_MEDIA_ROOT=/data/media

# A Unicode font for the wiki's PDF: without one it falls back on
# Latin-1 (docs/wiki.md#pdf).
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# The framework, as its wheel installs it: the core - Django and Django
# REST framework - and the wiki extra, nh3, which cleans its pages, and
# fpdf2, which writes a wiki as a PDF. Then
# django-allauth, for signing in with Microsoft: on only when compose
# passes MICROSOFT_CLIENT_ID.
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY generic/ ./generic/
RUN pip install ".[wiki]" "django-allauth[socialaccount]>=65.0" \
    && rm -rf /src

# The database, the wiki's images and the products' documents live in
# /data, a volume, so they outlive the container.
RUN useradd --create-home app && mkdir /data && chown app /data

WORKDIR /app
COPY minimal/ ./

USER app
EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]

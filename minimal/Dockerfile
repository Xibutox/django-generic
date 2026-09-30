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
    DJANGO_DB_PATH=/data/db.sqlite3

# The framework, as its wheel installs it: the core alone, Django and
# Django REST framework.
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY generic/ ./generic/
RUN pip install . && rm -rf /src

# The database lives in /data, a volume, so it outlives the container.
RUN useradd --create-home app && mkdir /data && chown app /data

WORKDIR /app
COPY minimal/ ./

USER app
EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]

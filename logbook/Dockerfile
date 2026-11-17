# syntax=docker/dockerfile:1
#
# The logbook in a container, built from this checkout: the framework
# installed from the repository, gunicorn, the static files served by
# WhiteNoise, PostgreSQL beside it (compose.yaml). The same stack as
# the kit's (kit/), without its vendor/ wheel.
#
# Built from the repository's root, which holds the framework:
#
#   docker compose -f logbook/compose.yaml up --build -d
#
# Behind a proxy: HTTP_PROXY, HTTPS_PROXY and NO_PROXY in logbook/.env
# reach pip here as build arguments (compose.yaml); Docker keeps them
# out of the image.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_STATIC_ROOT=/app/staticfiles

# The framework with its Excel export and its PostgreSQL driver, as the
# kit's requirements.txt, then gunicorn, WhiteNoise and requests.
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY generic/ ./generic/
# The versions CI tested (scripts/lock.py).
COPY requirements/constraints.txt ./
RUN pip install -c constraints.txt ".[export,postgres]" \
    "gunicorn>=22" "whitenoise>=6.6" "requests>=2.31" \
    && rm -rf /src

WORKDIR /app
COPY logbook/ ./
RUN python manage.py collectstatic --noinput \
    && useradd --create-home app

COPY --chmod=755 logbook/kit/docker-entrypoint.sh /usr/local/bin/
USER app
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "logsite.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]

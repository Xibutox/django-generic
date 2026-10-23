# syntax=docker/dockerfile:1
#
# The logbook in a container: gunicorn, the static files served by
# WhiteNoise, PostgreSQL beside it (compose.yaml).
#
#   docker compose up --build -d

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_STATIC_ROOT=/app/staticfiles

WORKDIR /app
COPY requirements.txt ./
COPY vendor/ ./vendor/
RUN pip install -r requirements.txt

COPY logbook/ ./
RUN python manage.py collectstatic --noinput \
    && useradd --create-home app

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/
USER app
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "logsite.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]

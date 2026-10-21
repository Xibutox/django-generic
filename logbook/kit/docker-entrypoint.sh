#!/bin/sh
# Before the server: the tables, then the first administrator if the
# environment names one (DJANGO_SUPERUSER_USERNAME / _PASSWORD / _EMAIL).
# `docker compose run web python manage.py ...` runs any command after it.
set -eu

python manage.py migrate --noinput

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    python manage.py createsuperuser --noinput \
        --username "$DJANGO_SUPERUSER_USERNAME" \
        --email "${DJANGO_SUPERUSER_EMAIL:-}" 2>/dev/null || true
fi

exec "$@"

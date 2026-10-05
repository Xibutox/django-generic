#!/bin/sh
# The web container's command: the tables, then the demo or the first
# administrator, then gunicorn.
set -eu

python manage.py migrate --noinput

# DEMO_DATA=1 (the default): the demo's teams, people and documents -
# seed_documents leaves alone what is already there. 0: an empty
# document manager, for real use - with its roles all the same, the
# groups Editors, Readers, Quality and Managers.
if [ "${DEMO_DATA:-1}" = "1" ]; then
    python manage.py seed_documents
else
    python manage.py seed_documents --roles-only
fi

# The first administrator, from DJANGO_SUPERUSER_USERNAME, _PASSWORD and
# _EMAIL - only while there is nobody: changing them later changes no
# account.
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
    python manage.py shell -c "
from django.contrib.auth import get_user_model
raise SystemExit(0 if get_user_model().objects.exists() else 1)
" || python manage.py createsuperuser --noinput
fi

exec gunicorn docsite.wsgi --bind 0.0.0.0:8000 --workers 3 --timeout 300 \
    --forwarded-allow-ips '*' --access-logfile -

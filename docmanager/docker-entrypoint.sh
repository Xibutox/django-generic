#!/bin/sh
# The web container's entrypoint: started as root, it makes the
# documents' folder - a folder of the host - the app user's, then runs
# the command as that user. `docker compose exec web ...` skips it and
# runs as root.
set -eu

media="${DJANGO_MEDIA_ROOT:-/data/media}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$media"
    # Only what is not app's already. A folder of Windows, shared by
    # Docker Desktop, may refuse: it lets every container write anyway.
    find "$media" \! -user app -exec chown app:app {} + 2>/dev/null || true
    export HOME=/home/app
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi

exec "$@"

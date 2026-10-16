#!/usr/bin/env bash
# Restoring a backup of {{ title }} - `python ops.py restore`, which
# first takes a backup of the present state and stops the application.
#
#   restore.sh NAME|latest           the database and the uploaded files
#   restore.sh --test NAME|latest    a full restore into a throwaway
#                                    database, recorded in
#                                    restore-tests.log, nothing replaced
#
# The live database is replaced only once the backup has been restored
# in full beside it: a restore that fails half-way changes nothing.

. /usr/local/bin/common.sh

psql_admin() {
    PGOPTIONS='--client-min-messages=warning' \
        psql -X -v ON_ERROR_STOP=1 -d postgres "$@"
}

# The backup's database, restored into a new database named $2.
restore_database_into() {
    local dir="$1" target="$2"

    psql_admin -qc "DROP DATABASE IF EXISTS \"$target\""
    psql_admin -qc "CREATE DATABASE \"$target\" OWNER \"$PGUSER\""
    decrypt "$dir/database.dump.gpg" \
        | pg_restore --no-owner --no-privileges --exit-on-error \
            --single-transaction -d "$target"
}

restore_test() {
    require_passphrase
    local dir name target tables migrations files result=passed
    dir="$(resolve_backup "${1:-latest}")"
    name="$(basename "$dir")"
    target="restore_test_$(date -u +%Y%m%d%H%M%S)"

    log "$name: restore test into $target"
    verify_backup "$dir"
    if restore_database_into "$dir" "$target"; then
        tables="$(psql -XAt -d "$target" -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
        migrations="$(psql -XAt -d "$target" -c "SELECT count(*) FROM django_migrations")"
        [ "$migrations" -gt 0 ] || result=failed
    else
        result=failed
    fi
    files="$(decrypt "$dir/media.tar.gz.gpg" | tar -tzf - | grep -vc '/$' || true)"
    psql_admin -qc "DROP DATABASE IF EXISTS \"$target\""

    # The record an auditor asks for: when, which backup, what came back.
    printf '%s\t%s\t%s\ttables=%s\tmigrations=%s\tfiles=%s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$name" "$result" \
        "${tables:-0}" "${migrations:-0}" "$files" \
        >> "$BACKUPS/restore-tests.log"
    chown "$(stat -c %u:%g "$BACKUPS")" "$BACKUPS/restore-tests.log" 2> /dev/null || true
    log "$name: restore test $result (tables=${tables:-0}, migrations=${migrations:-0}, files=$files)"
    [ "$result" = passed ]
}

restore() {
    require_passphrase
    local dir name stamp staging
    dir="$(resolve_backup "$1")"
    name="$(basename "$dir")"
    stamp="$(date -u +%Y%m%d%H%M%S)"
    staging="${PGDATABASE}_restoring"

    verify_backup "$dir"

    log "$name: restoring the database beside the live one"
    restore_database_into "$dir" "$staging"

    log "$name: unpacking the uploaded files beside the live ones"
    mkdir -p "/media/.restoring-$stamp"
    decrypt "$dir/media.tar.gz.gpg" \
        | tar -xzf - --numeric-owner --same-owner -C "/media/.restoring-$stamp"

    log "$name: switching to the restored data"
    psql_admin -q > /dev/null <<SQL
SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity
WHERE datname IN ('$PGDATABASE', '$staging') AND pid <> pg_backend_pid();
ALTER DATABASE "$PGDATABASE" RENAME TO "${PGDATABASE}_replaced_$stamp";
ALTER DATABASE "$staging" RENAME TO "$PGDATABASE";
SQL
    find /media -mindepth 1 -maxdepth 1 ! -name ".restoring-$stamp" \
        -exec rm -rf -- {} +
    find "/media/.restoring-$stamp" -mindepth 1 -maxdepth 1 \
        -exec mv -t /media -- {} +
    rmdir "/media/.restoring-$stamp"

    # The database it replaced is in the backup ops.py took just before.
    psql_admin -qc "DROP DATABASE \"${PGDATABASE}_replaced_$stamp\""
    log "$name: restored"
}

case "${1:-}" in
    --test) restore_test "${2:-latest}" ;;
    ""|--help|-h)
        sed -n '2,/^$/{s/^# \{0,1\}//;p}' "$0" >&2
        exit 2
        ;;
    *) restore "$1" ;;
esac

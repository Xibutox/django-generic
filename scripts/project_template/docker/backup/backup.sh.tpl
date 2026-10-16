#!/usr/bin/env bash
# The backups of {{ title }}: the database and the uploaded files,
# together, encrypted. Run by the `backup` service of compose.prod.yml,
# and by `python ops.py backup | backups | verify | restore-test`.
#
#   backup.sh schedule        every day at BACKUP_TIME (the service)
#   backup.sh now             one backup, verified, then the old ones pruned
#   backup.sh list            the backups, newest last
#   backup.sh verify [NAME]   checksums, decryption, readability
#   backup.sh test [NAME]     a full restore into a throwaway database

. /usr/local/bin/common.sh

backup_now() {
    require_passphrase
    local stamp name dir
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    name="${NAME_PREFIX}-${stamp}"
    dir="$BACKUPS/$name.partial"

    mkdir -p "$dir"
    log "$name: database"
    pg_dump --format=custom --no-owner --no-privileges | encrypt \
        > "$dir/database.dump.gpg"
    log "$name: uploaded files"
    tar -czf - --numeric-owner -C /media . | encrypt > "$dir/media.tar.gz.gpg"

    {
        echo "# $name"
        echo "# created: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "# database: $PGDATABASE, $(pg_dump --version)"
        echo "# server: $(psql -XAtc 'SHOW server_version')"
        echo "# encryption: GnuPG symmetric, AES-256, passphrase BACKUP_PASSPHRASE"
        (cd "$dir" && sha256sum database.dump.gpg media.tar.gz.gpg)
    } > "$dir/MANIFEST"

    verify_backup "$dir"
    # Complete and checked: only now is it a backup.
    mv "$dir" "$BACKUPS/$name"
    chown -R "$(stat -c %u:%g "$BACKUPS")" "$BACKUPS/$name" 2> /dev/null || true
    log "$name: done, $(du -sh "$BACKUPS/$name" | cut -f1)"
    prune
}

# Older than BACKUP_KEEP_DAYS go; the newest is always kept, and so are
# the unfinished ones of a backup still being written.
prune() {
    local keep="${BACKUP_KEEP_DAYS:-30}" newest
    newest="$(list_backups | tail -n 1)"

    find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d \
        -name "${NAME_PREFIX}-*" ! -name '*.partial' ! -name "$newest" \
        -mtime +"$keep" -print0 \
        | while IFS= read -r -d '' old; do
            log "$(basename "$old"): older than $keep days, deleted"
            rm -rf -- "$old"
        done
    # A .partial a day old is a backup that died half-way.
    find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -name '*.partial' \
        -mtime +0 -exec rm -rf -- {} +
}

schedule() {
    local at="${BACKUP_TIME:-02:30}" test_day="${BACKUP_TEST_WEEKDAY:-7}"
    log "backups every day at $at ($TZ), kept ${BACKUP_KEEP_DAYS:-30} days," \
        "restore test on weekday $test_day"
    while true; do
        if [ "$(date +%H:%M)" = "$at" ]; then
            backup_now || log "the backup failed"
            if [ "$(date +%u)" = "$test_day" ]; then
                restore.sh --test latest || log "the restore test failed"
            fi
            sleep 60
        fi
        sleep 20
    done
}

case "${1:-}" in
    schedule) schedule ;;
    now) backup_now ;;
    list)
        list_backups | while read -r name; do
            printf '%s  %s\n' "$name" "$(du -sh "$BACKUPS/$name" | cut -f1)"
        done
        ;;
    verify)
        require_passphrase
        verify_backup "$(resolve_backup "${2:-latest}")"
        ;;
    test) exec restore.sh --test "${2:-latest}" ;;
    *)
        sed -n '2,/^$/{s/^# \{0,1\}//;p}' "$0" >&2
        exit 2
        ;;
esac

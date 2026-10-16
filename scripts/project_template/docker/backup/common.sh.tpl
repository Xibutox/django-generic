#!/usr/bin/env bash
# What backup.sh and restore.sh share: where the backups are, how a
# file is encrypted and decrypted, and how a backup is checked.
#
# A backup is a folder in /backups (BACKUP_DIR on the host):
#
#   {{ slug }}-20261016T023000Z/
#     database.dump.gpg    pg_dump's custom format, encrypted
#     media.tar.gz.gpg     the uploaded files (MEDIA_ROOT), encrypted
#     MANIFEST             when, which versions, and the SHA-256 of both
#
# Encrypted with GnuPG, AES-256, from BACKUP_PASSPHRASE (docker/prod.env):
# any machine with gpg reads it back - see README.md, "Restoring by hand".

set -euo pipefail
umask 077

BACKUPS=/backups
NAME_PREFIX="${BACKUP_NAME:-backup}"

log() {
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

fail() {
    log "ERROR: $*"
    exit 1
}

require_passphrase() {
    [ -n "${BACKUP_PASSPHRASE:-}" ] \
        || fail "BACKUP_PASSPHRASE is not set (docker/prod.env)"
    mkdir -p "$GNUPGHOME"
    chmod 700 "$GNUPGHOME"
    # Kept in memory (/tmp is a tmpfs), never on the backups' disk.
    PASSFILE="$(mktemp)"
    printf '%s' "$BACKUP_PASSPHRASE" > "$PASSFILE"
    trap 'rm -f "$PASSFILE"' EXIT
}

encrypt() {  # stdin -> stdout
    gpg --batch --quiet --yes --pinentry-mode loopback \
        --passphrase-file "$PASSFILE" \
        --symmetric --cipher-algo AES256 --s2k-digest-algo SHA512 \
        --s2k-mode 3 --s2k-count 65011712 --compress-algo none
}

decrypt() {  # file -> stdout
    gpg --batch --quiet --yes --pinentry-mode loopback \
        --passphrase-file "$PASSFILE" --decrypt "$1"
}

# The backups, oldest first: complete ones only, never a .partial.
list_backups() {
    find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d \
        -name "${NAME_PREFIX}-*" ! -name '*.partial' -printf '%f\n' \
        | sort
}

# A name, "latest", or nothing (= latest) -> the backup's folder.
resolve_backup() {
    local name="${1:-latest}"

    if [ "$name" = latest ]; then
        name="$(list_backups | tail -n 1)"
        [ -n "$name" ] || fail "no backup in $BACKUPS yet"
    fi

    name="$(basename "$name")"
    [ -f "$BACKUPS/$name/MANIFEST" ] || fail "no backup named $name"
    printf '%s\n' "$BACKUPS/$name"
}

# The checksums, then each file decrypted and read through: a backup
# that passes can be restored (ISO/IEC 27002 8.13).
verify_backup() {
    local dir="$1" name
    name="$(basename "$dir" .partial)"

    (cd "$dir" && grep -E '^[0-9a-f]{64}  ' MANIFEST | sha256sum --check --quiet) \
        || fail "$name: a checksum does not match"
    decrypt "$dir/database.dump.gpg" | pg_restore --list > /dev/null \
        || fail "$name: the database dump cannot be read"
    decrypt "$dir/media.tar.gz.gpg" | tar -tzf - > /dev/null \
        || fail "$name: the files archive cannot be read"
    log "$name: verified"
}

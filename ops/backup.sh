#!/usr/bin/env bash
# Back up database, uploaded files and .env into backups/<date>_<time>[-LABEL]/ (see ops/README.md).
#
#   ops/backup.sh [LABEL]
#
# BACKUP_DIR   where backups go (default: backups/ in this checkout)
# BACKUP_KEEP  keep only the newest N backups afterwards (default: keep all)
source "$(dirname "$0")/lib.sh"

label=${1:-}
[[ "$label" =~ ^[A-Za-z0-9_-]*$ ]] || die "label: letters, digits, - and _ only"
command -v rsync >/dev/null || die "rsync is needed for backups"

umask 077  # backups hold all data and the secrets in .env
mkdir -p "$BACKUP_DIR"
name=$(date +%Y-%m-%d_%H%M%S)${label:+-$label}
target=$BACKUP_DIR/$name
partial=$target.partial
previous=$(list_backups | tail -n 1)
mkdir "$partial"

info "Database -> $target/db.dump"
compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$partial/db.dump" \
    || die "pg_dump failed; is the db container running? ($COMPOSE ps)"
# Older podman-compose versions print their own messages into the dump.
[[ "$(head -c 5 "$partial/db.dump")" == PGDMP ]] || die "$partial/db.dump is not a PostgreSQL dump (podman-compose too old?)"

# After the database, so the files of every row in the dump are there.
info "Uploaded files -> $target/media/${previous:+ (unchanged files hard-linked to $(basename "$previous"))}"
rsync -a --delete ${previous:+--link-dest="$previous/media"} data/media/ "$partial/media/"

cp .env "$partial/env"
{
    echo "created: $(date -Iseconds)"
    echo "commit: $(git rev-parse HEAD)"
    echo "version: $(git describe --always --dirty)"
    echo "host: $(hostname)"
} > "$partial/info.txt"
mv "$partial" "$target"
info "Backup complete: $target"

if [[ -n "${BACKUP_KEEP:-}" ]]; then
    [[ "$BACKUP_KEEP" =~ ^[1-9][0-9]*$ ]] || die "BACKUP_KEEP must be a positive number"
    list_backups | awk -v keep="$BACKUP_KEEP" '{ all[NR] = $0 } END { for (i = 1; i <= NR - keep; i++) print all[i] }' |
        while read -r old; do
            info "Removing old backup $old"
            rm -rf "$old"
        done
fi

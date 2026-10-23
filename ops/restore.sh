#!/usr/bin/env bash
# Replace database and uploaded files with a backup of ops/backup.sh (see ops/README.md).
#
#   ops/restore.sh BACKUP [--yes] [--no-safety-backup]
#
# Takes a backup of the current state first (label pre-restore), unless --no-safety-backup
# (e.g. on a new server without data). .env is not replaced; the backup's copy is BACKUP/env.
source "$(dirname "$0")/lib.sh"

backup=
safety_backup=1
for arg in "$@"; do
    case "$arg" in
        --yes) export ASSUME_YES=1 ;;
        --no-safety-backup) safety_backup= ;;
        -*) die "unknown option $arg" ;;
        *) backup=$(absolute "${arg%/}") ;;
    esac
done
[[ -n "$backup" ]] || die "usage: ops/restore.sh BACKUP [--yes] [--no-safety-backup]"
[[ -f "$backup/db.dump" && -d "$backup/media" && -f "$backup/info.txt" ]] \
    || die "$backup is not a complete backup (db.dump, media/, info.txt)"
[[ "$(head -c 5 "$backup/db.dump")" == PGDMP ]] || die "$backup/db.dump is not a PostgreSQL dump"
command -v rsync >/dev/null || die "rsync is needed"

cat "$backup/info.txt"
commit=$(sed -n 's/^commit: //p' "$backup/info.txt")
if [[ -n "$commit" ]] && ! git merge-base --is-ancestor "$commit" HEAD 2>/dev/null; then
    warn "the backup was made with code that is not part of this checkout (newer, or another branch)."
    warn "Its database may not fit this code; check out $commit first (git checkout $commit)."
fi
confirm "Replace the database and data/media/ with this backup? The app is down meanwhile."

if [[ -n "$safety_backup" ]]; then
    info "Backing up the current state first"
    "$ROOT/ops/backup.sh" pre-restore || die "safety backup failed; fix it, or skip it with --no-safety-backup"
fi

info "Stopping the app"
compose down
compose up -d db
wait_for_db

info "Restoring the database"
compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" &&
                          createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"'
compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --exit-on-error' \
    < "$backup/db.dump"

info "Restoring uploaded files"
mkdir -p data/media
rsync -a --delete "$backup/media/" data/media/

info "Starting the app (applies migrations if the backup is older than the code)"
compose up -d
wait_for_app
cmp -s "$backup/env" .env || warn ".env differs from the backup's copy ($backup/env); check SECRET_KEY and passwords."
info "Restored $backup"

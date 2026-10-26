#!/usr/bin/env bash
# Update to the newest code and container images (see ops/README.md).
#
#   ops/update.sh [--no-backup]
#
# Backs up first (label pre-update), pulls the code (fast-forward only), pulls the database
# and nginx images, rebuilds the app image and recreates the containers; the app applies
# migrations on start.
source "$(dirname "$0")/lib.sh"

backup=1
for arg in "$@"; do
    case "$arg" in
        --no-backup) backup= ;;
        *) die "usage: ops/update.sh [--no-backup]" ;;
    esac
done

if ! git diff --quiet HEAD; then
    git status --short --untracked-files=no >&2
    die "this checkout has local changes (above); commit or stash them, so the update cannot overwrite them"
fi

if [[ -n "$backup" ]]; then
    "$ROOT/ops/backup.sh" pre-update
    before_backup=$(list_backups | tail -n 1)
fi

before=$(git rev-parse HEAD)
info "Pulling the code"
git pull --ff-only
git log --oneline "$before..HEAD"

info "Pulling images and building the app image"
compose pull db web redis
compose build --pull python worker ocr

info "Recreating the containers"
compose down
compose up -d
if ! (wait_for_app); then
    cat >&2 <<EOF

The update did not start. To go back to the previous version:
    git reset --hard $before
    $COMPOSE build python
    ops/restore.sh ${before_backup:-<the last backup before the update>}
EOF
    exit 1
fi
info "Updated $(git rev-parse --short "$before") -> $(git describe --always)"

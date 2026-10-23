# shellcheck shell=bash
# Shared by the scripts in ops/: they work on the checkout they are in, from any directory.
set -euo pipefail

CALLER_DIR=$PWD
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

# A path given relative to the directory the script was called from.
absolute() {
    case "$1" in
        /*) printf '%s\n' "$1" ;;
        *) printf '%s\n' "$CALLER_DIR/$1" ;;
    esac
}

BACKUP_DIR=$(absolute "${BACKUP_DIR:-$ROOT/backups}")

info() { printf '\033[1m==> %s\033[0m\n' "$*" >&2; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

# podman-compose on the server; COMPOSE="docker compose" works as well.
if [[ -z "${COMPOSE:-}" ]]; then
    if command -v podman-compose >/dev/null; then
        COMPOSE=podman-compose
    elif docker compose version >/dev/null 2>&1; then
        COMPOSE="docker compose"
    else
        die "neither podman-compose nor docker compose found (or set COMPOSE)"
    fi
fi

compose() {
    # shellcheck disable=SC2086  # "docker compose" is two words
    $COMPOSE "$@"
}

[[ -f .env ]] || die "$ROOT/.env missing: copy .env.example and edit it (see README.md)"

# Ask before destructive steps; ASSUME_YES=1 (or --yes) skips the question.
confirm() {
    [[ "${ASSUME_YES:-}" == 1 ]] && return
    local answer
    read -r -p "$1 Type yes to continue: " answer
    [[ "$answer" == yes ]] || die "aborted"
}

wait_for_db() {
    local _
    for _ in $(seq 60); do
        compose exec -T db sh -c 'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1 && return
        sleep 1
    done
    die "the database did not get ready; see: $COMPOSE logs db"
}

# Waits until the app has migrated and answers /healthz (imzam/health.py).
wait_for_app() {
    local _
    for _ in $(seq 180); do
        if compose exec -T python curl -fsS -o /dev/null http://localhost:8000/healthz >/dev/null 2>&1 &&
            compose exec -T python ./manage.py migrate --check >/dev/null 2>&1; then
            return
        fi
        sleep 1
    done
    compose logs --tail 40 python >&2 || true
    die "the app did not start within 3 minutes (log above)"
}

# Complete backups, oldest first (a backup in progress ends in .partial).
list_backups() {
    [[ -d "$BACKUP_DIR" ]] || return 0
    find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d ! -name '*.partial' -exec test -f '{}/info.txt' ';' -print | sort
}

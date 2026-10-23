#!/usr/bin/env bash
# Run a Django management command in the app container, e.g. ops/manage.sh createsuperuser
source "$(dirname "$0")/lib.sh"

[[ $# -gt 0 ]] || die "usage: ops/manage.sh COMMAND [ARGS...]  (list: ops/manage.sh help)"
tty=-T
[[ -t 0 && -t 1 ]] && tty=
compose exec $tty python ./manage.py "$@"

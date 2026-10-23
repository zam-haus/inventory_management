#!/usr/bin/env bash
# Export the inventory without personal data for development databases (see docs/data-export.md).
#
#   ops/export.sh [--no-media]
#
# Writes exports/inventory-export-<date>.tar; --no-media leaves out photos and documents.
source "$(dirname "$0")/lib.sh"

mkdir -p exports
name=inventory-export-$(date +%Y-%m-%d_%H%M%S).tar
# exports/ is /code/exports in the app container (docker-compose.yml).
compose exec -T python ./manage.py export_public_data "/code/exports/$name" "$@"
info "Written: exports/$name"
info "Before publishing it, check the warnings above and docs/data-export.md."

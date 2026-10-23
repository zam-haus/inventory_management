#!/bin/bash
# Stop on a failed step: never serve with an unmigrated database.
set -e

./manage.py collectstatic --noinput
./manage.py migrate
# exec: gunicorn gets the stop signal and shuts down gracefully.
# Requests longer than GUNICORN_TIMEOUT are aborted; nginx.conf waits as long (proxy_read_timeout).
exec gunicorn imzam.wsgi -b 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" --timeout "${GUNICORN_TIMEOUT:-120}"

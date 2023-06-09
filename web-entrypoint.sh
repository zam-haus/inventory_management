#!/bin/bash

./manage.py compilemessages
./manage.py collectstatic --noinput
./manage.py migrate
./manage.py celery_worker run --background
gunicorn imzam.wsgi -b 0.0.0.0:8000

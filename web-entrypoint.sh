#!/bin/bash

./manage.py collectstatic --noinput
./manage.py migrate
gunicorn imzam.wsgi -b 0.0.0.0:8000
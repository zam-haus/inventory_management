"""Celery for background work (label printing on network printers): celery -A imzam worker."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "imzam.settings")

app = Celery("imzam")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

"""The inventory project; Celery is loaded with Django so tasks find their app."""
from .celery import app as celery_app

__all__ = ("celery_app",)
